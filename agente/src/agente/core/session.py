"""Estado de una sesión/tarea del agente."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from agente.core.types import Message
from agente.ports.memory import Memory


def new_session_id() -> str:
    return uuid.uuid4().hex


@dataclass
class Session:
    """Una conversación viva: su id y su memoria asociada."""

    id: str
    memory: Memory
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def history(self) -> list[Message]:
        return self.memory.messages()
