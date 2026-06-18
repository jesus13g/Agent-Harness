"""Planificación / descomposición de tareas.

Punto de extensión para estrategias de planificación más sofisticadas
(plan-and-execute, árbol de tareas, etc.). En la base, la planificación recae
en el propio modelo guiado por el *system prompt*, así que el planner solo
prepara el mensaje de sistema. Mantenerlo aquí deja un sitio claro donde
inyectar lógica de descomposición explícita en el futuro.
"""

from __future__ import annotations

from agente.core.prompts import ORCHESTRATOR_SYSTEM_PROMPT
from agente.core.types import Message, Role


class Planner:
    """Estrategia de planificación. La base delega en el modelo."""

    def __init__(self, system_prompt: str = ORCHESTRATOR_SYSTEM_PROMPT) -> None:
        self._system_prompt = system_prompt

    def system_message(self) -> Message:
        """Mensaje de sistema que orienta el comportamiento del orquestador."""
        return Message(role=Role.SYSTEM, content=self._system_prompt)
