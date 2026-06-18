"""Pruebas de la herramienta de scraping web (sin red, vía MockTransport)."""

from __future__ import annotations

import httpx
import pytest

from agente.infra.tools.scraper import WebScraperTool

_PAGE = """\
<html>
  <head>
    <title>Producto</title>
    <style>.x { color: red }</style>
    <script>var a = 1;</script>
  </head>
  <body>
    <h1>Auriculares Pro</h1>
    <p>Precio: 99,90 EUR</p>
    <p>En stock</p>
    <a href="/comprar">Comprar ahora</a>
    <a href="https://otra.com/info">Más info</a>
  </body>
</html>
"""


def _tool(handler, **over) -> WebScraperTool:
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport, follow_redirects=False)
    # allow_private evita la resolución DNS / chequeo SSRF en pruebas con host falso.
    kwargs = dict(allow_private=True)
    kwargs.update(over)
    return WebScraperTool(client=http, **kwargs)


def _html_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, html=_PAGE)


def test_text_mode_extracts_readable_text():
    tool = _tool(_html_handler)
    res = tool.run(url="http://test.local/producto", mode="text")
    assert res.ok
    assert "Auriculares Pro" in res.content
    assert "99,90 EUR" in res.content
    # Script y style no deben aparecer.
    assert "var a = 1" not in res.content
    assert "color: red" not in res.content


def test_text_is_default_mode():
    tool = _tool(_html_handler)
    res = tool.run(url="http://test.local/producto")
    assert res.ok and "Auriculares Pro" in res.content


def test_links_mode_resolves_relative_urls():
    tool = _tool(_html_handler)
    res = tool.run(url="http://test.local/producto", mode="links")
    assert res.ok
    assert "http://test.local/comprar" in res.content  # relativa resuelta
    assert "https://otra.com/info" in res.content
    assert "Comprar ahora" in res.content


def test_html_mode_returns_raw():
    tool = _tool(_html_handler)
    res = tool.run(url="http://test.local/producto", mode="html")
    assert res.ok
    assert "<h1>Auriculares Pro</h1>" in res.content


def test_non_html_content_type_returns_note():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"\x89PNG...", headers={"content-type": "image/png"})

    tool = _tool(handler)
    res = tool.run(url="http://test.local/img.png")
    assert res.ok
    assert "no devolvió contenido" in res.content.lower()


def test_follows_redirects_and_revalidates():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/start":
            return httpx.Response(302, headers={"location": "http://test.local/final"})
        return httpx.Response(200, html="<p>destino</p>")

    tool = _tool(handler)
    res = tool.run(url="http://test.local/start")
    assert res.ok and "destino" in res.content


def test_blocks_non_http_scheme():
    tool = _tool(_html_handler)
    res = tool.run(url="file:///etc/passwd")
    assert not res.ok
    assert "esquema" in res.error.lower()


def test_blocks_loopback_address():
    # Sin allow_private: la IP de loopback literal debe rechazarse (sin DNS).
    tool = _tool(_html_handler, allow_private=False)
    res = tool.run(url="http://127.0.0.1/admin")
    assert not res.ok
    assert "interna" in res.error.lower() or "privada" in res.error.lower()


def test_blocks_private_network():
    tool = _tool(_html_handler, allow_private=False)
    res = tool.run(url="http://10.0.0.5/secret")
    assert not res.ok


def test_requires_url():
    tool = _tool(_html_handler)
    assert not tool.run().ok
    assert not tool.run(url="").ok


def test_rejects_invalid_mode():
    tool = _tool(_html_handler)
    res = tool.run(url="http://test.local/x", mode="pdf")
    assert not res.ok
    assert "mode" in res.error.lower()


def test_network_error_is_caught():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    tool = _tool(handler)
    res = tool.run(url="http://test.local/x")
    assert not res.ok
    assert "red" in res.error.lower()
