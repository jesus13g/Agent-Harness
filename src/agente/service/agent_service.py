"""Fachada del agente: punto de entrada único y estable.

Cualquier interfaz futura (CLI, REST, WebSocket, chat web) consume SOLO esta
clase. El núcleo nunca importa código de interfaz; la dependencia va siempre
hacia el centro.

Fachada pura: NO construye adaptadores concretos. Recibe el LLM y las
herramientas ya inyectados (DIP estricto); del cableado se encarga la raíz de
composición (`factory`). `planner` y `memory_factory` son del núcleo y admiten
un valor por defecto inocuo.
"""

from __future__ import annotations

from collections.abc import Callable

from agente.config.settings import Settings
from agente.core.orchestrator import Orchestrator
from agente.core.planner import Planner
from agente.core.session import Session, new_session_id
from agente.core.types import AgentResult, Message
from agente.infra.memory.in_memory import InMemoryMemory
from agente.infra.tools.registry import ToolRegistry
from agente.observability.logging import get_logger
from agente.ports.llm_client import LLMClient
from agente.ports.memory import Memory

_log = get_logger("agente.service")

MemoryFactory = Callable[[], Memory]


class AgentService:
    """API limpia para ejecutar tareas en sesiones."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        llm: LLMClient,
        tools: ToolRegistry,
        planner: Planner | None = None,
        memory_factory: MemoryFactory | None = None,
    ) -> None:
        self._settings = settings or Settings()

        self._llm = llm
        self._tools = tools
        self._planner = planner or Planner()
        self._memory_factory = memory_factory or InMemoryMemory

        self._orchestrator = Orchestrator(self._llm, self._tools, self._settings)
        self._sessions: dict[str, Session] = {}

    # ------------------------------------------------------------------ #
    # API pública (estable para interfaces)
    # ------------------------------------------------------------------ #

    def create_session(self) -> str:
        """Crea una sesión nueva con su memoria y el mensaje de sistema."""
        memory = self._memory_factory()
        memory.add(self._planner.system_message())
        session = Session(id=new_session_id(), memory=memory)
        self._sessions[session.id] = session
        _log.info("session.created", session_id=session.id)
        return session.id

    def run_task(
        self, session_id: str, task: str, *, force_tool: str | None = None
    ) -> AgentResult:
        """Ejecuta una tarea dentro de una sesión existente.

        `force_tool` (opcional) fuerza el uso de una herramienta concreta en el
        primer paso (p. ej. el comando `/claude` de las interfaces). Si la
        herramienta no está registrada, se ignora.
        """
        session = self._get_session(session_id)
        return self._orchestrator.run(
            session.memory, task, session_id=session_id, force_tool=force_tool
        )

    def get_history(self, session_id: str) -> list[Message]:
        """Historial completo de la sesión."""
        return self._get_session(session_id).history()

    def list_tools(self) -> list[str]:
        return self._tools.names()

    def close_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    @property
    def settings(self) -> Settings:
        return self._settings

    # ------------------------------------------------------------------ #
    # Futuro: streaming de eventos por paso.
    #   def run_task_stream(self, session_id, task) -> Iterator[Event]: ...
    # ------------------------------------------------------------------ #

    def _get_session(self, session_id: str) -> Session:
        from agente.errors import SessionNotFoundError

        session = self._sessions.get(session_id)
        if session is None:
            raise SessionNotFoundError(f"Sesión inexistente: {session_id!r}")
        return session
