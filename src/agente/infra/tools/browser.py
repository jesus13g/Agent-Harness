"""Herramienta de scraping con navegador (Playwright).

Variante de `WebScraperTool` para páginas cuyo contenido se genera con
JavaScript (SPAs, listados que cargan por XHR, precios renderizados en cliente).
A diferencia del scraper HTTP, aquí se lanza un navegador headless (Chromium),
se ejecuta el JS de la página y se extrae el HTML ya renderizado.

Coste: Playwright es una dependencia pesada y opcional. Se importa de forma
perezosa, de modo que el resto del paquete funciona aunque no esté instalado.

Instalación:
    pip install "agente[browser]"
    playwright install chromium

Seguridad (SSRF): se reutiliza `guard_url` del scraper HTTP. Se valida la URL
inicial y la final (tras redirecciones/navegación). Además, con `allow_private`
desactivado (por defecto), se interceptan las peticiones del navegador y se
abortan las dirigidas a hosts internos/privados. Aun así, la frontera de un
navegador es intrínsecamente más amplia que la de una descarga HTTP simple:
úsala solo con URLs en las que confíes razonablemente.
"""

from __future__ import annotations

from typing import Any, Callable

from agente.core.types import ToolResult
from agente.infra.tools.scraper import (
    _MAX_BYTES,
    _UnsafeUrl,
    _truncate,
    extract_links,
    extract_text,
    guard_url,
)
from agente.observability.logging import get_logger
from agente.ports.tool import Tool

_log = get_logger("agente.tools.browser")

_DEFAULT_TIMEOUT = 30.0
_WAIT_STATES = ("load", "domcontentloaded", "networkidle")

# Un renderer recibe la URL y devuelve (url_final, html_renderizado).
Renderer = Callable[[str], tuple[str, str]]


class BrowserScraperTool(Tool):
    name = "browser_scraper"
    description = (
        "Descarga una página web ejecutando su JavaScript en un navegador "
        "headless y devuelve el contenido YA RENDERIZADO. Úsala cuando "
        "'web_scraper' devuelva una página vacía o sin los datos esperados "
        "porque el contenido se carga dinámicamente (tiendas, SPAs, listados "
        "que cargan por JavaScript). Es más lenta que 'web_scraper': prefiérela "
        "solo cuando la descarga HTTP simple no baste. Modos: 'text' (por "
        "defecto), 'links' y 'html'. Opcional 'wait_for': selector CSS que "
        "esperar antes de leer (p. ej. '.precio')."
    )
    parameters = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "URL completa (http/https) a renderizar.",
            },
            "mode": {
                "type": "string",
                "enum": ["text", "links", "html"],
                "description": "Qué extraer: 'text' (por defecto), 'links' o 'html'.",
            },
            "wait_for": {
                "type": "string",
                "description": (
                    "Selector CSS opcional a esperar antes de leer el contenido, "
                    "p. ej. '#precio' o '.producto'. Útil si los datos tardan en "
                    "aparecer."
                ),
            },
        },
        "required": ["url"],
    }

    def __init__(
        self,
        *,
        allow_private: bool = False,
        timeout: float = _DEFAULT_TIMEOUT,
        wait_until: str = "networkidle",
        renderer: Renderer | None = None,
    ) -> None:
        if wait_until not in _WAIT_STATES:
            raise ValueError(f"wait_until debe ser uno de {_WAIT_STATES}.")
        self._allow_private = allow_private
        self._timeout = timeout
        self._wait_until = wait_until
        # Renderer inyectable: en pruebas se pasa un doble; en producción es None
        # y se usa Playwright bajo demanda.
        self._renderer = renderer

    def run(self, **kwargs: Any) -> ToolResult:
        url = kwargs.get("url")
        mode = kwargs.get("mode") or "text"
        wait_for = kwargs.get("wait_for")

        if not isinstance(url, str) or not url.strip():
            return ToolResult.failure("Se requiere 'url' (string no vacío).")
        if mode not in ("text", "links", "html"):
            return ToolResult.failure("'mode' debe ser 'text', 'links' o 'html'.")
        if wait_for is not None and not isinstance(wait_for, str):
            return ToolResult.failure("'wait_for' debe ser un selector CSS (string).")

        url = url.strip()
        try:
            guard_url(url, allow_private=self._allow_private)
        except _UnsafeUrl as exc:
            return ToolResult.failure(str(exc))

        try:
            final_url, html = self._render(url, wait_for)
        except _UnsafeUrl as exc:
            return ToolResult.failure(str(exc))
        except _BrowserUnavailable as exc:
            return ToolResult.failure(str(exc))
        except Exception as exc:  # noqa: BLE001 — frontera; nunca propagar al bucle
            _log.warning("browser.render_error", url=url, error=str(exc))
            return ToolResult.failure(f"Fallo al renderizar {url!r} con el navegador: {exc}")

        # Revalidar el host tras posibles redirecciones/navegación.
        try:
            guard_url(final_url, allow_private=self._allow_private)
        except _UnsafeUrl as exc:
            return ToolResult.failure(str(exc))

        if mode == "html":
            return ToolResult.success(_truncate(html, _MAX_BYTES // 4))
        if mode == "links":
            return ToolResult.success(extract_links(final_url, html))
        return ToolResult.success(extract_text(html))

    # ------------------------------------------------------------------ #

    def _render(self, url: str, wait_for: str | None) -> tuple[str, str]:
        if self._renderer is not None:
            return self._renderer(url)
        return self._playwright_render(url, wait_for)

    def _playwright_render(self, url: str, wait_for: str | None) -> tuple[str, str]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover - depende del entorno
            raise _BrowserUnavailable(
                "Playwright no está instalado. Instálalo con "
                "'pip install \"agente[browser]\"' y luego "
                "'playwright install chromium'."
            ) from exc

        timeout_ms = int(self._timeout * 1000)
        allow_private = self._allow_private

        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=True)
            except Exception as exc:  # pragma: no cover - depende del entorno
                raise _BrowserUnavailable(
                    "No se pudo lanzar Chromium. ¿Has ejecutado "
                    "'playwright install chromium'? Detalle: " + str(exc)
                ) from exc

            try:
                page = browser.new_page()

                # Bloquear subrecursos hacia hosts internos/privados (SSRF).
                if not allow_private:
                    def _route(route: Any) -> None:
                        try:
                            guard_url(route.request.url, allow_private=False)
                        except _UnsafeUrl:
                            route.abort()
                        except Exception:  # noqa: BLE001 - nunca romper la navegación
                            route.continue_()
                        else:
                            route.continue_()

                    page.route("**/*", _route)

                page.goto(url, timeout=timeout_ms, wait_until=self._wait_until)
                if wait_for:
                    page.wait_for_selector(wait_for, timeout=timeout_ms)
                html = page.content()
                final_url = page.url
                return final_url, html
            finally:
                browser.close()


class _BrowserUnavailable(Exception):
    """El navegador (Playwright/Chromium) no está disponible en el entorno."""
