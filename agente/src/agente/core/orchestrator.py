"""Orquestador: el corazón del agente.

Ejecuta el bucle razonar → actuar → observar sobre la memoria de una sesión,
coordinando el modelo (`LLMClient`), las herramientas (`ToolRegistry`) y la
memoria (`Memory`). Controla el límite de pasos y detecta bucles para evitar
ejecuciones infinitas y coste descontrolado.
"""

from __future__ import annotations

from agente.config.settings import Settings
from agente.core.types import (
    AgentResult,
    LLMResponse,
    Message,
    Role,
    Step,
    StepType,
    Usage,
)
from agente.infra.tools.registry import ToolRegistry
from agente.observability.logging import get_logger
from agente.ports.llm_client import LLMClient
from agente.ports.memory import Memory

_log = get_logger("agente.orchestrator")

# Nº de repeticiones idénticas de una llamada antes de declarar bucle.
_LOOP_THRESHOLD = 3


class Orchestrator:
    """Bucle del agente. Es stateless respecto a sesiones: opera sobre la
    `Memory` que se le pasa en cada ejecución."""

    def __init__(
        self,
        llm: LLMClient,
        tools: ToolRegistry,
        settings: Settings,
    ) -> None:
        self._llm = llm
        self._tools = tools
        self._settings = settings

    def run(self, memory: Memory, task: str, *, session_id: str) -> AgentResult:
        memory.add(Message(role=Role.USER, content=task))

        steps: list[Step] = []
        usage_total = Usage()
        call_counter: dict[tuple[str, str], int] = {}

        log = _log.bind(session_id=session_id)
        log.info("task.start", task=task)

        for index in range(1, self._settings.max_steps + 1):
            response = self._llm.complete(memory.messages(), self._tools.specs())
            usage_total = usage_total + response.usage

            memory.add(
                Message(
                    role=Role.ASSISTANT,
                    content=response.content,
                    tool_calls=response.tool_calls,
                )
            )
            steps.append(self._llm_step(index, response))
            log.info(
                "step.llm",
                step=index,
                wants_tools=response.wants_tools,
                tools=[c.name for c in response.tool_calls],
            )

            if not response.wants_tools:
                log.info("task.done", step=index, total_tokens=usage_total.total_tokens)
                return AgentResult(
                    session_id=session_id,
                    output=response.content or "",
                    steps=steps,
                    usage=usage_total,
                    completed=True,
                )

            # Ejecutar cada herramienta solicitada y reinyectar resultados.
            for call in response.tool_calls:
                signature = (call.name, _stable_args(call.arguments))
                call_counter[signature] = call_counter.get(signature, 0) + 1

                if call_counter[signature] >= _LOOP_THRESHOLD:
                    log.warning("loop.detected", step=index, tool=call.name)
                    return AgentResult(
                        session_id=session_id,
                        output=None,
                        steps=steps,
                        usage=usage_total,
                        completed=False,
                        error=(
                            f"Bucle detectado: la herramienta {call.name!r} se "
                            f"repitió con los mismos argumentos."
                        ),
                    )

                result = self._tools.execute(call.name, call.arguments)
                memory.add(
                    Message(
                        role=Role.TOOL,
                        content=result.to_message_content(),
                        tool_call_id=call.id,
                        name=call.name,
                    )
                )
                steps.append(
                    Step(
                        index=index,
                        type=StepType.TOOL,
                        detail={
                            "tool": call.name,
                            "arguments": call.arguments,
                            "ok": result.ok,
                            "result": result.to_message_content()[:500],
                        },
                    )
                )
                log.info("step.tool", step=index, tool=call.name, ok=result.ok)

        log.warning("task.max_steps", max_steps=self._settings.max_steps)
        return AgentResult(
            session_id=session_id,
            output=None,
            steps=steps,
            usage=usage_total,
            completed=False,
            error=f"Límite de pasos alcanzado ({self._settings.max_steps}).",
        )

    # ------------------------------------------------------------------ #

    @staticmethod
    def _llm_step(index: int, response: LLMResponse) -> Step:
        return Step(
            index=index,
            type=StepType.LLM,
            detail={
                "content": (response.content or "")[:500],
                "tool_calls": [
                    {"name": c.name, "arguments": c.arguments}
                    for c in response.tool_calls
                ],
                "finish_reason": response.finish_reason,
            },
        )


def _stable_args(arguments: dict) -> str:
    """Representación estable de los argumentos para detectar repeticiones."""
    return repr(sorted(arguments.items()))
