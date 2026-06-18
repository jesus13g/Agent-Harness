"""Herramienta de scraping web: descarga una URL y extrae su contenido.

Complementa a `WebSearchTool` (que solo da un resumen): esta herramienta
descarga una página concreta y devuelve su texto legible o sus enlaces, de modo
que el agente pueda leer fichas de producto, artículos, listados, etc.

Seguridad:
- Solo se permiten esquemas ``http`` y ``https``.
- Protección **SSRF**: se resuelve el host y se rechazan direcciones privadas,
  loopback, link-local o reservadas (p. ej. ``localhost``, ``127.0.0.1``,
  ``169.254.x``, redes internas). Esto evita que el agente alcance servicios
  internos o metadatos de la nube. Se puede desactivar con ``allow_private``
  (solo para pruebas o entornos controlados).
- Las redirecciones se siguen manualmente y se revalida el host en cada salto,
  para que una redirección no esquive la comprobación SSRF.
- Tamaño de descarga acotado (`_MAX_BYTES`) y la extracción se hace con la
  librería estándar (`html.parser`), sin dependencias extra.
"""

from __future__ import annotations

import ipaddress
import socket
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from agente.core.types import ToolResult
from agente.ports.tool import Tool

_MAX_BYTES = 2_000_000
_MAX_TEXT_CHARS = 20_000
_MAX_LINKS = 100
_MAX_REDIRECTS = 5

# Etiquetas cuyo contenido no es texto legible.
_SKIP_TAGS = {"script", "style", "noscript", "template", "head"}
# Etiquetas de bloque: al cerrarlas insertamos un salto de línea.
_BLOCK_TAGS = {
    "p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
    "section", "article", "header", "footer", "ul", "ol", "table",
}


class WebScraperTool(Tool):
    name = "web_scraper"
    description = (
        "Descarga una página web (URL http/https) y extrae su contenido. "
        "Úsala cuando necesites leer el contenido real de una página concreta: "
        "una ficha de producto, un artículo, un listado, precios, etc. "
        "Modos: 'text' (texto legible, por defecto), 'links' (enlaces de la "
        "página con su texto) y 'html' (HTML en bruto, truncado). "
        "Para encontrar la URL primero, usa la búsqueda web."
    )
    parameters = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "URL completa a descargar, p. ej. 'https://ejemplo.com/producto'.",
            },
            "mode": {
                "type": "string",
                "enum": ["text", "links", "html"],
                "description": (
                    "Qué extraer: 'text' (texto legible, por defecto), 'links' "
                    "(enlaces) o 'html' (HTML en bruto)."
                ),
            },
        },
        "required": ["url"],
    }

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        timeout: float = 20.0,
        allow_private: bool = False,
    ) -> None:
        self._owns_client = client is None
        # follow_redirects=False: las gestionamos a mano para revalidar el host.
        self._client = client or httpx.Client(timeout=timeout, follow_redirects=False)
        self._allow_private = allow_private

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def run(self, **kwargs: Any) -> ToolResult:
        url = kwargs.get("url")
        mode = kwargs.get("mode") or "text"

        if not isinstance(url, str) or not url.strip():
            return ToolResult.failure("Se requiere 'url' (string no vacío).")
        if mode not in ("text", "links", "html"):
            return ToolResult.failure("'mode' debe ser 'text', 'links' o 'html'.")

        try:
            final_url, html = self._fetch(url.strip())
        except _UnsafeUrl as exc:
            return ToolResult.failure(str(exc))
        except httpx.HTTPError as exc:
            return ToolResult.failure(f"Fallo de red al descargar {url!r}: {exc}")

        if html is None:
            return ToolResult.success(
                f"La URL {final_url!r} no devolvió contenido HTML/texto procesable."
            )

        if mode == "html":
            return ToolResult.success(_truncate(html, _MAX_BYTES // 4))
        if mode == "links":
            return ToolResult.success(extract_links(final_url, html))
        return ToolResult.success(extract_text(html))

    # ------------------------------------------------------------------ #
    # Descarga con validación SSRF y redirecciones manuales
    # ------------------------------------------------------------------ #

    def _fetch(self, url: str) -> tuple[str, str | None]:
        """Descarga la URL siguiendo redirecciones, validando cada salto.

        Devuelve (url_final, html) donde html es None si el contenido no es
        texto/HTML procesable.
        """
        current = url
        for _ in range(_MAX_REDIRECTS + 1):
            guard_url(current, allow_private=self._allow_private)
            resp = self._client.get(current)

            if resp.is_redirect:
                location = resp.headers.get("location")
                if not location:
                    break
                current = urljoin(current, location)
                continue

            resp.raise_for_status()

            content_type = resp.headers.get("content-type", "").lower()
            if not any(t in content_type for t in ("html", "text", "xml")):
                return current, None

            raw = resp.content[:_MAX_BYTES]
            text = raw.decode(resp.encoding or "utf-8", errors="replace")
            return current, text

        raise _UnsafeUrl(f"Demasiadas redirecciones al descargar {url!r}.")


# ---------------------------------------------------------------------- #
# Funciones reutilizables (compartidas con la variante de navegador)
# ---------------------------------------------------------------------- #


def guard_url(url: str, *, allow_private: bool = False) -> None:
    """Valida una URL frente a esquema no permitido y SSRF.

    Lanza `_UnsafeUrl` si la URL no es http/https o si el host resuelve a una
    dirección interna/privada (salvo que `allow_private` sea True).
    """
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise _UnsafeUrl(
            f"Esquema no permitido: {parts.scheme!r}. Solo se admiten http y https."
        )
    host = parts.hostname
    if not host:
        raise _UnsafeUrl(f"URL sin host válido: {url!r}.")
    if allow_private:
        return
    for ip in _resolve(host):
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise _UnsafeUrl(
                f"Acceso bloqueado a dirección interna/privada ({host} -> {ip})."
            )


def _resolve(host: str) -> list[ipaddress._BaseAddress]:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise _UnsafeUrl(f"No se pudo resolver el host {host!r}: {exc}") from exc
    addrs: list[ipaddress._BaseAddress] = []
    for info in infos:
        sockaddr = info[4]
        try:
            addrs.append(ipaddress.ip_address(sockaddr[0]))
        except ValueError:
            continue
    if not addrs:
        raise _UnsafeUrl(f"El host {host!r} no resolvió a ninguna IP.")
    return addrs


def extract_text(html: str) -> str:
    """Extrae el texto legible de un documento HTML."""
    parser = _TextExtractor()
    parser.feed(html)
    text = parser.get_text()
    if not text:
        return "(la página no contiene texto legible)"
    return _truncate(text, _MAX_TEXT_CHARS)


def extract_links(base_url: str, html: str) -> str:
    """Extrae los enlaces (texto + URL absoluta) de un documento HTML."""
    parser = _LinkExtractor()
    parser.feed(html)
    if not parser.links:
        return "(la página no contiene enlaces)"
    lines: list[str] = []
    seen: set[str] = set()
    for text, href in parser.links:
        absolute = urljoin(base_url, href)
        if not absolute.startswith(("http://", "https://")):
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        label = text.strip() or "(sin texto)"
        lines.append(f"- {label}: {absolute}")
        if len(lines) >= _MAX_LINKS:
            lines.append(f"(enlaces truncados a {_MAX_LINKS})")
            break
    return "\n".join(lines)


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... (truncado a {limit} caracteres)"


class _TextExtractor(HTMLParser):
    """Extrae texto legible: ignora script/style y separa bloques con saltos."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag in _BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._chunks.append(data)

    def get_text(self) -> str:
        raw = "".join(self._chunks)
        # Colapsar espacios por línea y eliminar líneas vacías repetidas.
        lines = [" ".join(line.split()) for line in raw.splitlines()]
        out: list[str] = []
        for line in lines:
            if line:
                out.append(line)
            elif out and out[-1] != "":
                out.append("")
        return "\n".join(out).strip()


class _LinkExtractor(HTMLParser):
    """Recolecta (texto, href) de las etiquetas <a>."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._current_href: str | None = None
        self._current_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self._current_href = href
                self._current_text = []

    def handle_data(self, data: str) -> None:
        if self._current_href is not None:
            self._current_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._current_href is not None:
            self.links.append(("".join(self._current_text), self._current_href))
            self._current_href = None
            self._current_text = []


class _UnsafeUrl(Exception):
    """La URL solicitada está bloqueada (esquema, host privado, SSRF)."""
