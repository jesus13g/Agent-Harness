"""Modelos de dominio compartidos por todo el núcleo.

Son tipos puros (Pydantic), sin dependencias de infraestructura. Tanto los
puertos como los adaptadores hablan en términos de estos tipos.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Role(str, Enum):
    """Rol de un mensaje dentro de la conversación."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ToolCall(BaseModel):
    """Petición del modelo para invocar una herramienta."""

    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class Message(BaseModel):
    """Un mensaje del historial de conversación.

    - `tool_calls`: presente en mensajes `assistant` que piden herramientas.
    - `tool_call_id` / `name`: presentes en mensajes `tool` (resultado de una
      herramienta), enlazan el resultado con la llamada que lo originó.
    """

    role: Role
    content: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_call_id: str | None = None
    name: str | None = None


class ToolSpec(BaseModel):
    """Descripción de una herramienta que se pasa al modelo (function schema)."""

    name: str
    description: str
    parameters: dict[str, Any]


class ToolResult(BaseModel):
    """Resultado de ejecutar una herramienta."""

    ok: bool = True
    content: str = ""
    error: str | None = None

    @classmethod
    def success(cls, content: str) -> ToolResult:
        return cls(ok=True, content=content)

    @classmethod
    def failure(cls, error: str) -> ToolResult:
        return cls(ok=False, error=error)

    def to_message_content(self) -> str:
        """Texto que se reinyecta como mensaje `tool` para el modelo."""
        if self.ok:
            return self.content
        return f"ERROR: {self.error}"


class Usage(BaseModel):
    """Consumo de tokens acumulable."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
        )


class LLMResponse(BaseModel):
    """Respuesta normalizada del modelo (texto final o petición de herramienta)."""

    content: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    finish_reason: str | None = None
    usage: Usage = Field(default_factory=Usage)
    raw: dict[str, Any] | None = None

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


class StepType(str, Enum):
    LLM = "llm"
    TOOL = "tool"


class Step(BaseModel):
    """Una entrada de la traza de ejecución del orquestador."""

    index: int
    type: StepType
    detail: dict[str, Any] = Field(default_factory=dict)


class AgentResult(BaseModel):
    """Resultado final de ejecutar una tarea."""

    session_id: str
    output: str | None = None
    steps: list[Step] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    completed: bool = True
    error: str | None = None
