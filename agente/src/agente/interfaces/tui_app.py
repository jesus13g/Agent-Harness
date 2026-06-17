"""Interfaz TUI con Textual (adaptador delgado sobre AgentService).

Pantalla completa en terminal: panel de chat con scroll, panel lateral con
modelo/herramientas/tokens/traza, y caja de entrada abajo.

Ejecutar:
    agente-tui
    # o
    python -m agente.interfaces.tui_app

No forma parte del núcleo: solo instancia la fachada y llama a sus métodos.
Estilo deliberadamente en ASCII (sin emojis): marcadores [OK]/[ERR], bordes
en estilo 'ascii'. Crece añadiendo widgets aquí, sin tocar el núcleo.
"""

from __future__ import annotations

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Footer, Header, Input, RichLog, Static

from agente.core.types import AgentResult, StepType
from agente.errors import AgenteError
from agente.service.agent_service import AgentService


class AgenteTUI(App):
    """App TUI de chat con el agente orquestador."""

    TITLE = "Agente - orquestador"

    CSS = """
    #body { height: 1fr; }
    #chat { width: 3fr; border: ascii $accent; padding: 0 1; }
    #side { width: 1fr; border: ascii $accent; padding: 0 1; }
    #prompt { border: ascii $accent; }
    """

    BINDINGS = [
        Binding("ctrl+n", "new_session", "Nueva conversacion"),
        Binding("ctrl+q", "quit", "Salir"),
    ]

    def __init__(self, service: AgentService | None = None) -> None:
        super().__init__()
        self._service = service or AgentService()
        self._session_id = ""
        self._total_tokens = 0

    # ------------------------------------------------------------------ #
    # Composición y arranque
    # ------------------------------------------------------------------ #

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Horizontal(id="body"):
            yield RichLog(id="chat", wrap=True, markup=False, highlight=False)
            yield Static(id="side")
        yield Input(placeholder="Escribe una tarea y pulsa Enter", id="prompt")
        yield Footer()

    def on_mount(self) -> None:
        self._session_id = self._service.create_session()
        self._update_side()
        log = self._chat()
        log.write("Escribe una tarea abajo y pulsa Enter.")
        log.write("Atajos: Ctrl+N nueva conversacion, Ctrl+Q salir.")
        if not self._service.settings.has_api_key:
            log.write(
                "[ERR] Falta AGENTE_MINIMAX_API_KEY en .env; las tareas fallaran "
                "hasta configurarla."
            )
        log.write("")
        self._prompt().focus()

    # ------------------------------------------------------------------ #
    # Eventos
    # ------------------------------------------------------------------ #

    @on(Input.Submitted, "#prompt")
    def _on_submit(self, event: Input.Submitted) -> None:
        task = event.value.strip()
        if not task:
            return
        prompt = self._prompt()
        prompt.value = ""
        prompt.disabled = True

        log = self._chat()
        log.write(f"tu> {task}")
        log.write("    (pensando...)")
        self._run_task(task)

    # ------------------------------------------------------------------ #
    # Trabajo en hilo (run_task es sincrono y hace I/O de red)
    # ------------------------------------------------------------------ #

    @work(thread=True, exclusive=True)
    def _run_task(self, task: str) -> None:
        try:
            result = self._service.run_task(self._session_id, task)
        except AgenteError as exc:
            self.call_from_thread(self._show_error, f"Error del agente: {exc}")
            return
        except Exception as exc:  # noqa: BLE001 — mostrar cualquier fallo en la UI
            self.call_from_thread(self._show_error, f"Error inesperado: {exc}")
            return
        self.call_from_thread(self._show_result, result)

    # ------------------------------------------------------------------ #
    # Render (en el hilo de la UI)
    # ------------------------------------------------------------------ #

    def _show_result(self, result: AgentResult) -> None:
        log = self._chat()
        if result.completed:
            log.write(f"ia> {result.output}")
        else:
            log.write(f"[ERR] {result.error}")

        log.write(
            f"    traza: {len(result.steps)} pasos, {result.usage.total_tokens} tokens"
        )
        for step in result.steps:
            if step.type is StepType.TOOL:
                mark = "[OK]" if step.detail.get("ok") else "[ERR]"
                res = (step.detail.get("result", "") or "").replace("\n", " ")[:80]
                log.write(
                    f"      {mark} {step.detail.get('tool')}"
                    f"({step.detail.get('arguments')}) -> {res}"
                )
            else:
                calls = step.detail.get("tool_calls") or []
                if calls:
                    names = [c["name"] for c in calls]
                    log.write(f"      * razona -> pide: {names}")
        log.write("")

        self._total_tokens += result.usage.total_tokens
        self._update_side()
        self._enable_input()

    def _show_error(self, message: str) -> None:
        self._chat().write(f"[ERR] {message}")
        self._chat().write("")
        self._enable_input()

    # ------------------------------------------------------------------ #
    # Acciones
    # ------------------------------------------------------------------ #

    def action_new_session(self) -> None:
        self._service.close_session(self._session_id)
        self._session_id = self._service.create_session()
        self._total_tokens = 0
        log = self._chat()
        log.clear()
        log.write("(nueva conversacion)")
        log.write("")
        self._update_side()
        self._enable_input()

    # ------------------------------------------------------------------ #
    # Utilidades de UI
    # ------------------------------------------------------------------ #

    def _chat(self) -> RichLog:
        return self.query_one("#chat", RichLog)

    def _prompt(self) -> Input:
        return self.query_one("#prompt", Input)

    def _enable_input(self) -> None:
        prompt = self._prompt()
        prompt.disabled = False
        prompt.focus()

    def _update_side(self) -> None:
        s = self._service.settings
        lines = [
            "AGENTE",
            f"modelo: {s.model}",
            f"max pasos: {s.max_steps}",
            "",
            "herramientas:",
        ]
        lines += [f"  - {name}" for name in self._service.list_tools()]
        mode = "system (-dap)" if s.fs_access_mode == "system" else "scoped"
        lines += ["", f"modo fs: {mode}"]
        lines += ["", f"tokens (sesion): {self._total_tokens}"]
        if not s.has_api_key:
            lines += ["", "AVISO: falta", "AGENTE_MINIMAX_API_KEY", "en .env"]
        self.query_one("#side", Static).update("\n".join(lines))


def main() -> None:
    # Silencia los logs para no corromper la pantalla del TUI (el orquestador
    # registra en stderr a nivel INFO durante run_task).
    import argparse

    from agente.config.settings import Settings

    parser = argparse.ArgumentParser(
        prog="agente-tui",
        description="Agente orquestador (interfaz TUI).",
    )
    parser.add_argument(
        "-dap",
        action="store_true",
        help="Acceso total al sistema de ficheros (salvo carpetas delicadas y secretos).",
    )
    args = parser.parse_args()

    settings = Settings(log_level="CRITICAL")
    if args.dap:
        settings.fs_access_mode = "system"

    service = AgentService(settings)
    AgenteTUI(service=service).run()


if __name__ == "__main__":
    main()
