"""Pruebas del orquestador y de la fachada (sin red, con LLM programado)."""

from __future__ import annotations

from agente.core.orchestrator import Orchestrator
from agente.core.types import LLMResponse, Role, ToolCall, Usage
from agente.infra.memory.in_memory import InMemoryMemory
from agente.infra.tools.calculator import CalculatorTool
from agente.infra.tools.registry import ToolRegistry
from agente.service.agent_service import AgentService

from tests.conftest import ScriptedLLM


def _registry() -> ToolRegistry:
    return ToolRegistry([CalculatorTool()])


def test_direct_final_answer(settings):
    llm = ScriptedLLM([LLMResponse(content="La respuesta es 42.")])
    orch = Orchestrator(llm, _registry(), settings)
    result = orch.run(InMemoryMemory(), "¿cuál es la respuesta?", session_id="s1")

    assert result.completed
    assert result.output == "La respuesta es 42."
    # Un solo paso LLM.
    assert len([s for s in result.steps if s.type.value == "llm"]) == 1


def test_tool_then_final(settings):
    llm = ScriptedLLM(
        [
            LLMResponse(
                tool_calls=[ToolCall(id="c1", name="calculator", arguments={"expression": "6*7"})],
                usage=Usage(total_tokens=10),
            ),
            LLMResponse(content="Son 42.", usage=Usage(total_tokens=5)),
        ]
    )
    memory = InMemoryMemory()
    orch = Orchestrator(llm, _registry(), settings)
    result = orch.run(memory, "multiplica 6 por 7", session_id="s2")

    assert result.completed
    assert result.output == "Son 42."
    assert result.usage.total_tokens == 15

    # La memoria contiene el resultado de la herramienta (=42) reinyectado.
    contents = [m.content for m in memory.all_messages() if m.role == Role.TOOL]
    assert "42" in contents[0]


def test_max_steps_reached(settings):
    settings.max_steps = 2
    # Siempre pide herramienta -> nunca termina.
    always_tool = [
        LLMResponse(tool_calls=[ToolCall(id=f"c{i}", name="calculator", arguments={"expression": f"{i}+1"})])
        for i in range(5)
    ]
    orch = Orchestrator(ScriptedLLM(always_tool), _registry(), settings)
    result = orch.run(InMemoryMemory(), "bucle", session_id="s3")

    assert not result.completed
    assert "Límite de pasos" in result.error


def test_loop_detection(settings):
    # Misma llamada idéntica repetida -> debe detectarse el bucle.
    same = [
        LLMResponse(tool_calls=[ToolCall(id=f"c{i}", name="calculator", arguments={"expression": "1+1"})])
        for i in range(5)
    ]
    orch = Orchestrator(ScriptedLLM(same), _registry(), settings)
    result = orch.run(InMemoryMemory(), "repite", session_id="s4")

    assert not result.completed
    assert "Bucle detectado" in result.error


def test_tool_error_is_reinjected(settings):
    llm = ScriptedLLM(
        [
            LLMResponse(tool_calls=[ToolCall(id="c1", name="calculator", arguments={"expression": "1/0"})]),
            LLMResponse(content="No se puede dividir por cero."),
        ]
    )
    memory = InMemoryMemory()
    orch = Orchestrator(llm, _registry(), settings)
    result = orch.run(memory, "divide 1 entre 0", session_id="s5")

    assert result.completed
    tool_msgs = [m.content for m in memory.all_messages() if m.role == Role.TOOL]
    assert "ERROR" in tool_msgs[0]


# --- Fachada ---------------------------------------------------------------


def test_agent_service_end_to_end(settings):
    llm = ScriptedLLM(
        [
            LLMResponse(tool_calls=[ToolCall(id="c1", name="calculator", arguments={"expression": "2+2"})]),
            LLMResponse(content="Cuatro."),
        ]
    )
    service = AgentService(settings, llm=llm, tools=_registry())

    session_id = service.create_session()
    result = service.run_task(session_id, "suma 2 y 2")

    assert result.completed and result.output == "Cuatro."
    history = service.get_history(session_id)
    # system + user + assistant(tool) + tool + assistant(final)
    assert history[0].role == Role.SYSTEM
    assert any(m.role == Role.USER for m in history)


def test_agent_service_unknown_session_raises(settings):
    from agente.errors import SessionNotFoundError

    service = AgentService(settings, llm=ScriptedLLM([]), tools=_registry())
    try:
        service.run_task("inexistente", "hola")
    except SessionNotFoundError:
        pass
    else:  # pragma: no cover
        raise AssertionError("Debió lanzar SessionNotFoundError")
