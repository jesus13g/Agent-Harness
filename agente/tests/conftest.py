"""Utilidades y dobles de prueba compartidos."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from agente.config.settings import Settings
from agente.core.types import LLMResponse, Message, ToolSpec
from agente.ports.llm_client import LLMClient


class ScriptedLLM(LLMClient):
    """LLM falso que devuelve respuestas predefinidas, una por llamada.

    Permite probar el orquestador sin red. Registra los `messages`/`tools`
    recibidos en cada llamada para poder hacer aserciones.
    """

    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[list[Message], list[ToolSpec] | None]] = []

    def complete(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
    ) -> LLMResponse:
        self.calls.append((list(messages), tools))
        if not self._responses:
            raise AssertionError("ScriptedLLM se quedó sin respuestas programadas.")
        return self._responses.pop(0)


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        minimax_api_key="test-key",
        fs_root=str(tmp_path / "workspace"),
        max_steps=5,
        enable_web_search=False,
        log_format="console",
    )


@pytest.fixture
def workspace(tmp_path) -> Iterator[str]:
    root = tmp_path / "workspace"
    root.mkdir()
    yield str(root)
