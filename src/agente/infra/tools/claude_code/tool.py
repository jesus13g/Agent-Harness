"""Herramienta `claude_code`: delega tareas de programación a un agente Claude Code.

Adaptador fino sobre el puerto `Tool`. Solo se ocupa de: validar la entrada,
invocar el backend inyectado (DIP) y formatear la salida como `ToolResult`. Toda
la lógica del SDK vive en el backend; el saneo, en `sanitize`.
"""

from __future__ import annotations

from typing import Any

from agente.core.types import ToolResult
from agente.infra.tools.claude_code.backend import CodeAgentBackend, CodeAgentUnavailable
from agente.infra.tools.claude_code.sanitize import clean_task
from agente.observability.logging import get_logger
from agente.ports.tool import Tool

_log = get_logger("agente.tools.claude_code")


class ClaudeCodeTool(Tool):
    name = "claude_code"
    description = (
        "Delega una tarea de PROGRAMACIÓN compleja a un agente Claude Code "
        "autónomo, que puede leer y escribir ficheros y ejecutar comandos en el "
        "directorio de trabajo. Úsala cuando la tarea requiera escribir o "
        "modificar código real: implementar una feature, refactorizar varios "
        "ficheros, escribir o arreglar tests, depurar un fallo. Describe la "
        "tarea de forma completa y autocontenida en una sola instrucción; el "
        "agente trabaja solo y devuelve un resumen de lo que hizo. No la uses "
        "para preguntas simples ni cálculos."
    )
    parameters = {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": (
                    "Tarea de programación completa y autocontenida, p. ej. "
                    "'crea un módulo utils.py con una función slugify y su test'."
                ),
            }
        },
        "required": ["task"],
    }

    def __init__(self, backend: CodeAgentBackend, *, cwd: str | None = None) -> None:
        self._backend = backend
        self._cwd = cwd

    def run(self, **kwargs: Any) -> ToolResult:
        task = clean_task(kwargs.get("task"))
        if not task:
            return ToolResult.failure("Se requiere 'task' (string no vacío).")

        try:
            result = self._backend.run_task(task, cwd=self._cwd)
        except CodeAgentUnavailable as exc:
            return ToolResult.failure(str(exc))
        except Exception as exc:  # noqa: BLE001 — frontera; nunca propagar al bucle
            _log.warning("claude_code.error", error=str(exc))
            return ToolResult.failure(f"Claude Code falló: {exc}")

        _log.info(
            "claude_code.done",
            ok=result.ok,
            cost_usd=result.cost_usd,
            num_turns=result.num_turns,
        )
        if result.ok:
            return ToolResult.success(result.output)
        return ToolResult.failure(result.error or result.output or "Claude Code falló.")
