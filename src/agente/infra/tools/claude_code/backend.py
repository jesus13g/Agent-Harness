"""Abstracción del backend de un agente de programación (puerto interno).

La herramienta `ClaudeCodeTool` no depende del SDK de Claude Code directamente,
sino de este contrato mínimo (`CodeAgentBackend`). Así el adaptador concreto
(`ClaudeAgentSdkBackend`) es sustituible y la herramienta es testeable con un
doble, sin necesidad del SDK ni de red (DIP/ISP).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class CodeAgentResult:
    """Resultado normalizado de delegar una tarea a un agente de programación."""

    output: str
    ok: bool = True
    cost_usd: float | None = None
    num_turns: int | None = None
    error: str | None = None


class CodeAgentBackend(Protocol):
    """Contrato mínimo de un backend capaz de ejecutar una tarea de programación.

    Es síncrono a propósito: la herramienta que lo usa implementa el puerto
    `Tool`, cuyo `run()` es síncrono. Cualquier asincronía (p. ej. el SDK de
    Claude Code) queda encapsulada dentro del adaptador concreto.
    """

    def run_task(self, task: str, *, cwd: str | None) -> CodeAgentResult:
        """Ejecuta la tarea y devuelve su resultado normalizado."""
        ...


class CodeAgentUnavailable(Exception):
    """El backend no está disponible en el entorno (falta el SDK o el CLI)."""
