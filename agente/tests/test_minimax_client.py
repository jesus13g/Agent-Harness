"""Pruebas del adaptador MiniMax usando un transporte HTTP simulado."""

from __future__ import annotations

import json

import httpx
import pytest

from agente.config.settings import Settings
from agente.core.types import Message, Role, ToolCall, ToolSpec
from agente.errors import ConfigError, LLMError
from agente.infra.minimax_client import MiniMaxClient


def _settings(**over) -> Settings:
    base = dict(minimax_api_key="k", max_retries=2, request_timeout=5)
    base.update(over)
    return Settings(**base)


def _client(handler) -> MiniMaxClient:
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport, base_url="https://api.minimax.io/v1")
    return MiniMaxClient(_settings(), client=http)


def test_requires_api_key():
    client = MiniMaxClient(Settings(minimax_api_key=""))
    with pytest.raises(ConfigError):
        client.complete([Message(role=Role.USER, content="hola")])


def test_parses_text_response():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["model"]  # se envía el modelo
        assert body["messages"][0]["role"] == "user"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": "hola humano"}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
            },
        )

    resp = _client(handler).complete([Message(role=Role.USER, content="hola")])
    assert resp.content == "hola humano"
    assert not resp.wants_tools
    assert resp.usage.total_tokens == 5


def test_parses_tool_call_response():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "calculator",
                                        "arguments": '{"expression": "2+2"}',
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            },
        )

    tools = [ToolSpec(name="calculator", description="calc", parameters={"type": "object"})]
    resp = _client(handler).complete([Message(role=Role.USER, content="suma")], tools)

    assert resp.wants_tools
    call = resp.tool_calls[0]
    assert call.name == "calculator"
    assert call.arguments == {"expression": "2+2"}


def test_4xx_raises_llm_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="unauthorized")

    with pytest.raises(LLMError):
        _client(handler).complete([Message(role=Role.USER, content="hola")])


def test_5xx_is_retried_then_succeeds():
    state = {"calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["calls"] += 1
        if state["calls"] == 1:
            return httpx.Response(503, text="busy")
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "ok"}}]}
        )

    resp = _client(handler).complete([Message(role=Role.USER, content="hola")])
    assert resp.content == "ok"
    assert state["calls"] == 2  # reintentó una vez


def test_missing_choices_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [], "base_resp": {"status_code": 0}})

    with pytest.raises(LLMError):
        _client(handler).complete([Message(role=Role.USER, content="hola")])


def test_base_resp_error_gives_friendly_message():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"base_resp": {"status_code": 1008, "status_msg": "insufficient balance"}},
        )

    with pytest.raises(LLMError, match="Saldo insuficiente"):
        _client(handler).complete([Message(role=Role.USER, content="hola")])


def test_encodes_tool_and_assistant_messages():
    """Comprueba la traducción de mensajes con tool_calls y resultados tool."""
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "fin"}}]})

    messages = [
        Message(
            role=Role.ASSISTANT,
            content=None,
            tool_calls=[ToolCall(id="call_1", name="calculator", arguments={"expression": "2+2"})],
        ),
        Message(role=Role.TOOL, content="4", tool_call_id="call_1", name="calculator"),
    ]
    _client(handler).complete(messages)

    sent = captured["body"]["messages"]
    assistant_msg = sent[0]
    assert assistant_msg["role"] == "assistant"
    assert assistant_msg["tool_calls"][0]["function"]["name"] == "calculator"
    # Los argumentos viajan como string JSON.
    assert json.loads(assistant_msg["tool_calls"][0]["function"]["arguments"]) == {
        "expression": "2+2"
    }

    tool_msg = sent[-1]
    assert tool_msg["role"] == "tool"
    assert tool_msg["tool_call_id"] == "call_1"
    assert tool_msg["name"] == "calculator"
