"""Puerto del modelo de lenguaje.

Aísla el núcleo del proveedor concreto (MiniMax, OpenAI, local…). Cambiar de
proveedor = escribir otro adaptador; el núcleo no se toca.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from agente.core.types import LLMResponse, Message, ToolSpec


class LLMClient(ABC):
    """Contrato mínimo de un cliente de LLM."""

    @abstractmethod
    def complete(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        *,
        tool_choice: str | None = None,
    ) -> LLMResponse:
        """Envía el historial al modelo y devuelve la respuesta normalizada.

        La respuesta es o bien texto final (`content`) o bien una o más
        peticiones de herramienta (`tool_calls`).

        `tool_choice` (opcional) fuerza el uso de una herramienta concreta por su
        nombre; `None` deja que el modelo decida ("auto"). El adaptador concreto
        lo traduce al formato de su API.
        """
        raise NotImplementedError
