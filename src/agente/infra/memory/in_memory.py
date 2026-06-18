"""Memoria de sesión en RAM con gestión básica del límite de contexto.

Estrategia: los mensajes `system` se conservan siempre; del resto se mantiene
el sufijo más reciente que quepa en el presupuesto de tokens (truncado de los
más antiguos). Se evita dejar mensajes `tool` huérfanos al principio, porque
la API exige que cada resultado de herramienta siga a su llamada.
"""

from __future__ import annotations

from agente.core.types import Message, Role
from agente.ports.memory import Memory


def estimate_tokens(text: str | None) -> int:
    """Heurística barata: ~4 caracteres por token."""
    if not text:
        return 0
    return max(1, len(text) // 4)


def _message_tokens(message: Message) -> int:
    total = estimate_tokens(message.content)
    for call in message.tool_calls:
        total += estimate_tokens(call.name) + estimate_tokens(str(call.arguments))
    return total + 4  # sobrecarga por mensaje (rol, separadores)


class InMemoryMemory(Memory):
    """Historial de conversación volátil con truncado por presupuesto de tokens."""

    def __init__(self, max_context_tokens: int = 100_000) -> None:
        self._messages: list[Message] = []
        self._max_context_tokens = max_context_tokens

    def add(self, message: Message) -> None:
        self._messages.append(message)

    def messages(self) -> list[Message]:
        return self._fit_to_budget(self._messages)

    def all_messages(self) -> list[Message]:
        """Historial completo sin truncar (para inspección/depuración)."""
        return list(self._messages)

    def clear(self) -> None:
        self._messages.clear()

    # ------------------------------------------------------------------ #

    def _fit_to_budget(self, messages: list[Message]) -> list[Message]:
        system = [m for m in messages if m.role == Role.SYSTEM]
        rest = [m for m in messages if m.role != Role.SYSTEM]

        budget = self._max_context_tokens - sum(_message_tokens(m) for m in system)

        # Recorrer de lo más reciente a lo más antiguo acumulando hasta el tope.
        kept_reversed: list[Message] = []
        used = 0
        for message in reversed(rest):
            cost = _message_tokens(message)
            if used + cost > budget and kept_reversed:
                break
            kept_reversed.append(message)
            used += cost

        kept = list(reversed(kept_reversed))

        # No dejar resultados de herramienta sin su llamada previa.
        while kept and kept[0].role == Role.TOOL:
            kept.pop(0)

        return system + kept
