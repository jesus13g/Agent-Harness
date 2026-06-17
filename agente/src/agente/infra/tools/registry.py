"""Registro de herramientas.

Mantiene el catálogo disponible, genera los esquemas que se pasan al modelo y
resuelve nombre → ejecución. Añadir una herramienta = registrarla aquí o
inyectarla; el orquestador no cambia.
"""

from __future__ import annotations

from typing import Any

from agente.config.settings import Settings
from agente.core.types import ToolResult, ToolSpec
from agente.observability.logging import get_logger
from agente.ports.tool import Tool

_log = get_logger("agente.tools")


class ToolRegistry:
    """Catálogo de herramientas indexado por nombre."""

    def __init__(self, tools: list[Tool] | None = None) -> None:
        self._tools: dict[str, Tool] = {}
        for tool in tools or []:
            self.register(tool)

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Herramienta duplicada: {tool.name!r}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools)

    def specs(self) -> list[ToolSpec]:
        """Esquemas para pasar al modelo."""
        return [tool.spec() for tool in self._tools.values()]

    def execute(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """Ejecuta una herramienta por nombre, capturando cualquier fallo.

        Nunca lanza: un fallo se devuelve como `ToolResult.failure`, de modo
        que el orquestador pueda reinyectarlo al modelo para que se recupere.
        """
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult.failure(
                f"Herramienta desconocida: {name!r}. Disponibles: {self.names()}"
            )
        try:
            result = tool.run(**arguments)
            _log.debug("tool.executed", tool=name, ok=result.ok)
            return result
        except TypeError as exc:
            # Argumentos que no encajan con la firma de run().
            return ToolResult.failure(f"Argumentos inválidos para {name!r}: {exc}")
        except Exception as exc:  # noqa: BLE001 — frontera de seguridad
            _log.warning("tool.unhandled_error", tool=name, error=str(exc))
            return ToolResult.failure(f"La herramienta {name!r} falló: {exc}")


def build_default_registry(settings: Settings) -> ToolRegistry:
    """Construye el registro con las herramientas base habilitadas por config."""
    # Import local para evitar ciclos y mantener ligero el módulo.
    from agente.infra.tools.calculator import CalculatorTool
    from agente.infra.tools.filesystem import FileSystemTool
    from agente.infra.tools.web_search import WebSearchTool

    if settings.fs_access_mode == "system":
        fs_tool = FileSystemTool(
            system_access=True, block_secrets=settings.fs_block_secrets
        )
    else:
        fs_tool = FileSystemTool(
            root=settings.fs_root, block_secrets=settings.fs_block_secrets
        )

    tools: list[Tool] = [
        CalculatorTool(),
        fs_tool,
    ]
    if settings.enable_web_search:
        tools.append(WebSearchTool())
    return ToolRegistry(tools)
