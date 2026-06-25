"""Adaptador del modelo MiniMax (endpoint chatcompletion_v2, estilo OpenAI).

Traduce los tipos de dominio (`Message`, `ToolSpec`) al formato de la API y la
respuesta de vuelta a `LLMResponse`. Incluye reintentos con backoff ante fallos
transitorios.

Endpoint: ``{base_url}/text/chatcompletion_v2``
Modelos:  MiniMax-M2 / MiniMax-M2.5 / MiniMax-M2.7
"""

from __future__ import annotations

import json
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from agente.config.settings import Settings
from agente.core.types import LLMResponse, Message, Role, ToolCall, ToolSpec, Usage
from agente.errors import ConfigError, LLMError
from agente.observability.logging import get_logger
from agente.ports.llm_client import LLMClient

_log = get_logger("agente.minimax")


class _RetryableHTTPError(Exception):
    """Error transitorio (red o 5xx) que justifica reintento."""


class MiniMaxClient(LLMClient):
    """Cliente HTTP del endpoint chatcompletion_v2 de MiniMax."""

    def __init__(self, settings: Settings, *, client: httpx.Client | None = None) -> None:
        self._settings = settings
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url=settings.minimax_base_url.rstrip("/"),
            timeout=settings.request_timeout,
            headers={
                "Authorization": f"Bearer {settings.minimax_api_key}",
                "Content-Type": "application/json",
            },
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> MiniMaxClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------ #
    # API pública del puerto
    # ------------------------------------------------------------------ #

    def complete(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        *,
        tool_choice: str | None = None,
    ) -> LLMResponse:
        if not self._settings.has_api_key:
            raise ConfigError(
                "Falta AGENTE_MINIMAX_API_KEY. Define la clave en el entorno o en .env."
            )

        payload: dict[str, Any] = {
            "model": self._settings.model,
            "messages": [self._encode_message(m) for m in messages],
            "temperature": self._settings.temperature,
            "max_tokens": self._settings.max_tokens,
        }
        if tools:
            payload["tools"] = [self._encode_tool(t) for t in tools]
            # Forzar una herramienta concreta o dejar que el modelo decida.
            payload["tool_choice"] = (
                {"type": "function", "function": {"name": tool_choice}}
                if tool_choice
                else "auto"
            )

        data = self._post_with_retries(payload)
        return self._decode_response(data)

    # ------------------------------------------------------------------ #
    # HTTP + reintentos
    # ------------------------------------------------------------------ #

    def _post_with_retries(self, payload: dict[str, Any]) -> dict[str, Any]:
        attempts = self._settings.max_retries + 1

        @retry(
            retry=retry_if_exception_type(_RetryableHTTPError),
            stop=stop_after_attempt(attempts),
            wait=wait_exponential(multiplier=0.5, min=0.5, max=8),
            reraise=True,
        )
        def _do() -> dict[str, Any]:
            try:
                resp = self._client.post("/text/chatcompletion_v2", json=payload)
            except httpx.TransportError as exc:  # red caída, DNS, timeout…
                _log.warning("minimax.transport_error", error=str(exc))
                raise _RetryableHTTPError(str(exc)) from exc

            if resp.status_code >= 500:
                _log.warning("minimax.server_error", status=resp.status_code)
                raise _RetryableHTTPError(f"HTTP {resp.status_code}")
            if resp.status_code >= 400:
                raise LLMError(f"MiniMax HTTP {resp.status_code}: {resp.text}")

            try:
                return resp.json()
            except json.JSONDecodeError as exc:
                raise LLMError(f"Respuesta no-JSON de MiniMax: {resp.text[:200]}") from exc

        return _do()

    # ------------------------------------------------------------------ #
    # Traducción dominio <-> API
    # ------------------------------------------------------------------ #

    @staticmethod
    def _encode_message(message: Message) -> dict[str, Any]:
        out: dict[str, Any] = {"role": message.role.value}
        # `content` puede ser null en assistant cuando solo hay tool_calls.
        out["content"] = message.content if message.content is not None else ""

        if message.tool_calls:
            out["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(call.arguments, ensure_ascii=False),
                    },
                }
                for call in message.tool_calls
            ]
        if message.role == Role.TOOL:
            out["tool_call_id"] = message.tool_call_id
            if message.name:
                out["name"] = message.name
        return out

    @staticmethod
    def _encode_tool(spec: ToolSpec) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.parameters,
            },
        }

    @staticmethod
    def _decode_response(data: dict[str, Any]) -> LLMResponse:
        # MiniMax incluye siempre base_resp; status_code != 0 indica error de API
        # aunque la respuesta HTTP sea 200.
        base = data.get("base_resp") or {}
        status = base.get("status_code", 0)
        if status not in (0, None):
            raise LLMError(_format_base_resp(status, base.get("status_msg", "")))

        choices = data.get("choices")
        if not choices:
            raise LLMError(f"Respuesta inesperada de MiniMax (sin 'choices'): {data}")

        choice = choices[0]
        msg = choice.get("message", {})

        tool_calls: list[ToolCall] = []
        for raw_call in msg.get("tool_calls") or []:
            fn = raw_call.get("function", {})
            tool_calls.append(
                ToolCall(
                    id=raw_call.get("id", fn.get("name", "")),
                    name=fn.get("name", ""),
                    arguments=_parse_arguments(fn.get("arguments")),
                )
            )

        usage_raw = data.get("usage") or {}
        usage = Usage(
            prompt_tokens=usage_raw.get("prompt_tokens", 0),
            completion_tokens=usage_raw.get("completion_tokens", 0),
            total_tokens=usage_raw.get("total_tokens", 0),
        )

        return LLMResponse(
            content=msg.get("content") or None,
            tool_calls=tool_calls,
            finish_reason=choice.get("finish_reason"),
            usage=usage,
            raw=data,
        )


# Códigos de error de MiniMax (campo base_resp.status_code) → mensaje claro.
_BASE_RESP_MESSAGES = {
    1000: "Error desconocido en MiniMax.",
    1001: "Timeout en MiniMax: reintenta más tarde.",
    1002: "Límite de frecuencia (rate limit) alcanzado en MiniMax.",
    1004: "Autenticación fallida: revisa AGENTE_MINIMAX_API_KEY.",
    1008: "Saldo insuficiente en tu cuenta MiniMax: recarga crédito para continuar.",
    1013: "Error interno del servicio de MiniMax: reintenta más tarde.",
    1027: "Contenido bloqueado por las políticas de MiniMax.",
    1039: "Límite de tokens por minuto (TPM) alcanzado en MiniMax.",
    2013: "Parámetros de la petición inválidos para MiniMax.",
}


def _format_base_resp(status: int, msg: str) -> str:
    friendly = _BASE_RESP_MESSAGES.get(status)
    detail = f" ({msg})" if msg else ""
    if friendly:
        return f"{friendly}{detail} [base_resp.status_code={status}]"
    return f"Error de MiniMax{detail} [base_resp.status_code={status}]"


def _parse_arguments(raw: Any) -> dict[str, Any]:
    """Los argumentos llegan como string JSON; se decodifican a dict."""
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {"_raw": parsed}
    except (json.JSONDecodeError, TypeError):
        return {"_raw": raw}
