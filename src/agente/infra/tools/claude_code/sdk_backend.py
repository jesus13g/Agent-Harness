"""Adaptador del Claude Agent SDK (`claude-agent-sdk`).

Única pieza que conoce el SDK. Traduce una tarea en una sesión `query(...)` de
Claude Code, agrega sus mensajes y devuelve un `CodeAgentResult` normalizado.

Asincronía: el SDK es asíncrono; aquí se envuelve con `asyncio.run()`, de modo
que la herramienta que lo usa permanece síncrona. Es seguro porque el
orquestador ejecuta las herramientas fuera de cualquier event loop (la CLI es
síncrona y la TUI lo hace en un hilo worker).

Dependencia pesada y opcional (requiere Node.js + el CLI de Claude Code): se
importa de forma perezosa, igual que Playwright en el scraper de navegador.
"""

from __future__ import annotations

import asyncio

from agente.infra.tools.claude_code.backend import (
    CodeAgentBackend,
    CodeAgentResult,
    CodeAgentUnavailable,
)
from agente.infra.tools.claude_code.sanitize import clean_output

_DEFAULT_ALLOWED_TOOLS = ("Read", "Write", "Edit", "Bash", "Glob", "Grep")
_SYSTEM_PROMPT = "Eres un ingeniero de software experto y autónomo."


class ClaudeAgentSdkBackend(CodeAgentBackend):
    """Backend que delega en un agente Claude Code vía el Claude Agent SDK."""

    def __init__(
        self,
        *,
        model: str = "claude-opus-4-8",
        permission_mode: str = "acceptEdits",
        max_turns: int = 40,
        max_budget_usd: float | None = 5.0,
        allowed_tools: tuple[str, ...] = _DEFAULT_ALLOWED_TOOLS,
    ) -> None:
        self._model = model
        self._permission_mode = permission_mode
        self._max_turns = max_turns
        self._max_budget_usd = max_budget_usd
        self._allowed_tools = list(allowed_tools)

    def run_task(self, task: str, *, cwd: str | None) -> CodeAgentResult:
        return asyncio.run(self._run_async(task, cwd))

    async def _run_async(self, task: str, cwd: str | None) -> CodeAgentResult:
        try:
            from claude_agent_sdk import (  # import perezoso
                AssistantMessage,
                ClaudeAgentOptions,
                ResultMessage,
                TextBlock,
                query,
            )
        except ImportError as exc:  # pragma: no cover - depende del entorno
            raise CodeAgentUnavailable(
                "claude-agent-sdk no está instalado. Instálalo con "
                "'pip install \"agente[code]\"' y asegúrate de tener Node.js y el "
                "CLI de Claude Code ('npm i -g @anthropic-ai/claude-code') "
                "autenticado (ANTHROPIC_API_KEY o suscripción Claude.ai)."
            ) from exc

        options = ClaudeAgentOptions(
            system_prompt=_SYSTEM_PROMPT,
            permission_mode=self._permission_mode,
            allowed_tools=self._allowed_tools,
            cwd=cwd,
            model=self._model,
            max_turns=self._max_turns,
            max_budget_usd=self._max_budget_usd,
        )

        assistant_texts: list[str] = []
        result_text: str | None = None
        ok = True
        cost_usd: float | None = None
        num_turns: int | None = None

        async for message in query(prompt=task, options=options):
            if isinstance(message, AssistantMessage):
                assistant_texts += [
                    block.text for block in message.content if isinstance(block, TextBlock)
                ]
            elif isinstance(message, ResultMessage):
                ok = not message.is_error
                cost_usd = message.total_cost_usd
                num_turns = message.num_turns
                result_text = message.result

        output = clean_output(assistant_texts, result_text)
        return CodeAgentResult(
            output=output,
            ok=ok,
            cost_usd=cost_usd,
            num_turns=num_turns,
            error=None if ok else (output or "Claude Code terminó con error."),
        )
