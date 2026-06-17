"""Smoke test de la TUI (Textual) sin red, con LLM programado.

Usa el piloto de Textual dentro de `asyncio.run` para no depender de
pytest-asyncio. Inyecta un AgentService con `ScriptedLLM` (de conftest).
"""

from __future__ import annotations

import asyncio

from agente.core.types import LLMResponse, Role, ToolCall
from agente.infra.tools.calculator import CalculatorTool
from agente.infra.tools.registry import ToolRegistry
from agente.interfaces.tui_app import AgenteTUI
from agente.service.agent_service import AgentService

from tests.conftest import ScriptedLLM


def test_tui_processes_a_turn(settings):
    llm = ScriptedLLM(
        [
            LLMResponse(
                tool_calls=[
                    ToolCall(id="c1", name="calculator", arguments={"expression": "2+2"})
                ]
            ),
            LLMResponse(content="Cuatro."),
        ]
    )
    service = AgentService(settings, llm=llm, tools=ToolRegistry([CalculatorTool()]))
    app = AgenteTUI(service=service)

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("#prompt").value = "suma 2 y 2"
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()

    asyncio.run(scenario())

    history = service.get_history(app._session_id)
    assert any(
        m.role == Role.ASSISTANT and m.content == "Cuatro." for m in history
    )
    assert app._total_tokens >= 0


def test_tui_mounts_and_lists_tools(settings):
    service = AgentService(settings, llm=ScriptedLLM([]), tools=ToolRegistry([CalculatorTool()]))
    app = AgenteTUI(service=service)

    async def scenario() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            # El panel lateral muestra la herramienta registrada.
            side = app.query_one("#side").render()
            assert "calculator" in str(side)
            # Se creó una sesión al montar.
            assert app._session_id

    asyncio.run(scenario())
