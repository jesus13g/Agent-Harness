"""Pruebas de BrowserScraperTool con un renderer inyectado (sin Playwright)."""

from __future__ import annotations

import pytest

from agente.infra.tools.browser import BrowserScraperTool

_RENDERED = """\
<html><body>
  <h1>Producto JS</h1>
  <p class="precio">149,00 EUR</p>
  <a href="/ficha">Ver ficha</a>
</body></html>
"""


def _renderer(html: str = _RENDERED, final_url: str = "http://test.local/p"):
    def render(url: str) -> tuple[str, str]:
        return final_url, html

    return render


def test_text_mode_extracts_rendered_content():
    tool = BrowserScraperTool(allow_private=True, renderer=_renderer())
    res = tool.run(url="http://test.local/p", mode="text")
    assert res.ok
    assert "Producto JS" in res.content
    assert "149,00 EUR" in res.content


def test_links_mode_resolves_relative():
    tool = BrowserScraperTool(allow_private=True, renderer=_renderer())
    res = tool.run(url="http://test.local/p", mode="links")
    assert res.ok
    assert "http://test.local/ficha" in res.content


def test_html_mode_returns_rendered_html():
    tool = BrowserScraperTool(allow_private=True, renderer=_renderer())
    res = tool.run(url="http://test.local/p", mode="html")
    assert res.ok
    assert "<h1>Producto JS</h1>" in res.content


def test_guards_initial_url_scheme():
    tool = BrowserScraperTool(allow_private=True, renderer=_renderer())
    res = tool.run(url="file:///etc/passwd")
    assert not res.ok
    assert "esquema" in res.error.lower()


def test_blocks_loopback_before_rendering():
    called = {"n": 0}

    def render(url: str) -> tuple[str, str]:
        called["n"] += 1
        return url, "<p>x</p>"

    tool = BrowserScraperTool(allow_private=False, renderer=render)
    res = tool.run(url="http://127.0.0.1/admin")
    assert not res.ok
    # El renderer ni siquiera debe invocarse: la guardia corta antes.
    assert called["n"] == 0


def test_revalidates_final_url():
    # La navegación acaba en un host privado -> debe bloquearse al revalidar.
    tool = BrowserScraperTool(
        allow_private=False,
        renderer=_renderer(final_url="http://10.0.0.1/internal"),
    )
    # URL inicial pública (allow_private=False, pero 8.8.8.8 es público y no hace DNS).
    res = tool.run(url="http://8.8.8.8/start")
    assert not res.ok
    assert "interna" in res.error.lower() or "privada" in res.error.lower()


def test_render_failure_is_caught():
    def render(url: str) -> tuple[str, str]:
        raise RuntimeError("timeout navegando")

    tool = BrowserScraperTool(allow_private=True, renderer=render)
    res = tool.run(url="http://test.local/p")
    assert not res.ok
    assert "renderizar" in res.error.lower()


def test_requires_url():
    tool = BrowserScraperTool(allow_private=True, renderer=_renderer())
    assert not tool.run().ok


def test_rejects_invalid_mode():
    tool = BrowserScraperTool(allow_private=True, renderer=_renderer())
    res = tool.run(url="http://test.local/p", mode="pdf")
    assert not res.ok
    assert "mode" in res.error.lower()


def test_rejects_invalid_wait_until():
    with pytest.raises(ValueError):
        BrowserScraperTool(wait_until="whenever")
