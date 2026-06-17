"""Pruebas de la memoria de sesión en RAM."""

from __future__ import annotations

from agente.core.types import Message, Role, ToolCall
from agente.infra.memory.in_memory import InMemoryMemory, estimate_tokens


def _msg(role: Role, content: str) -> Message:
    return Message(role=role, content=content)


def test_add_and_messages_roundtrip():
    mem = InMemoryMemory()
    mem.add(_msg(Role.SYSTEM, "sys"))
    mem.add(_msg(Role.USER, "hola"))
    msgs = mem.messages()
    assert [m.role for m in msgs] == [Role.SYSTEM, Role.USER]


def test_clear():
    mem = InMemoryMemory()
    mem.add(_msg(Role.USER, "hola"))
    mem.clear()
    assert mem.messages() == []


def test_truncation_keeps_system_and_recent():
    # Presupuesto minúsculo para forzar truncado.
    mem = InMemoryMemory(max_context_tokens=40)
    mem.add(_msg(Role.SYSTEM, "system"))
    for i in range(20):
        mem.add(_msg(Role.USER, f"mensaje numero {i} con bastante texto de relleno"))

    msgs = mem.messages()
    # El system siempre se conserva.
    assert msgs[0].role == Role.SYSTEM
    # No se devuelve todo el historial.
    assert len(msgs) < 21
    # El último mensaje añadido sobrevive.
    assert "numero 19" in msgs[-1].content


def test_truncation_drops_orphan_tool_messages():
    mem = InMemoryMemory(max_context_tokens=30)
    mem.add(_msg(Role.SYSTEM, "s"))
    mem.add(
        Message(
            role=Role.ASSISTANT,
            tool_calls=[ToolCall(id="1", name="calc", arguments={"x": 1})],
        )
    )
    mem.add(Message(role=Role.TOOL, content="resultado largo " * 5, tool_call_id="1", name="calc"))
    mem.add(_msg(Role.USER, "otra cosa mas reciente"))

    msgs = mem.messages()
    non_system = [m for m in msgs if m.role != Role.SYSTEM]
    # El primer no-system nunca debe ser un TOOL huérfano.
    if non_system:
        assert non_system[0].role != Role.TOOL


def test_estimate_tokens():
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd") >= 1
