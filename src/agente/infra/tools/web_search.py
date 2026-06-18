"""Herramienta de búsqueda web.

Implementación base sin clave de API usando la *Instant Answer API* de
DuckDuckGo. Es deliberadamente simple: devuelve el resumen y temas relacionados.
Para producción conviene sustituirla por un proveedor con resultados completos
(Bing, Brave, Tavily, SerpAPI…), lo cual es solo escribir otra `Tool`.
"""

from __future__ import annotations

from typing import Any

import httpx

from agente.core.types import ToolResult
from agente.ports.tool import Tool

_ENDPOINT = "https://api.duckduckgo.com/"
_MAX_RESULTS = 5


class WebSearchTool(Tool):
    name = "web_search"
    description = (
        "Busca información en la web y devuelve un resumen y enlaces relevantes. "
        "Úsala cuando necesites datos actuales o que no conoces. Indica una "
        "consulta concisa en lenguaje natural."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Términos de búsqueda en lenguaje natural.",
            }
        },
        "required": ["query"],
    }

    def __init__(self, *, client: httpx.Client | None = None, timeout: float = 15.0) -> None:
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=timeout)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def run(self, **kwargs: Any) -> ToolResult:
        query = kwargs.get("query")
        if not isinstance(query, str) or not query.strip():
            return ToolResult.failure("Se requiere 'query' (string no vacío).")

        try:
            resp = self._client.get(
                _ENDPOINT,
                params={
                    "q": query,
                    "format": "json",
                    "no_html": "1",
                    "skip_disambig": "1",
                },
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as exc:
            return ToolResult.failure(f"Fallo de red en la búsqueda: {exc}")
        except ValueError as exc:
            return ToolResult.failure(f"Respuesta de búsqueda no válida: {exc}")

        return ToolResult.success(self._format(query, data))

    # ------------------------------------------------------------------ #

    @staticmethod
    def _format(query: str, data: dict[str, Any]) -> str:
        lines: list[str] = []

        abstract = (data.get("AbstractText") or "").strip()
        if abstract:
            source = data.get("AbstractSource") or ""
            url = data.get("AbstractURL") or ""
            lines.append(f"Resumen ({source}): {abstract}")
            if url:
                lines.append(f"Fuente: {url}")

        answer = (data.get("Answer") or "").strip()
        if answer:
            lines.append(f"Respuesta directa: {answer}")

        related = _flatten_related(data.get("RelatedTopics") or [])
        if related:
            lines.append("Temas relacionados:")
            for item in related[:_MAX_RESULTS]:
                lines.append(f"  - {item}")

        if not lines:
            return (
                f"Sin resultados estructurados para {query!r}. "
                "DuckDuckGo Instant Answer no siempre cubre todas las consultas; "
                "considera reformular o usar un proveedor de búsqueda completo."
            )
        return "\n".join(lines)


def _flatten_related(topics: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for topic in topics:
        if "Text" in topic:
            text = topic.get("Text", "").strip()
            url = topic.get("FirstURL", "")
            out.append(f"{text} ({url})" if url else text)
        elif "Topics" in topic:  # subgrupos anidados
            out.extend(_flatten_related(topic["Topics"]))
    return out
