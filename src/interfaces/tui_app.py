"""Interfaz TUI con Textual (adaptador delgado sobre AgentService).

Pantalla completa en terminal con identidad visual propia (tema *Ruby Charcoal
Twilight*): panel de chat con burbujas por rol y Markdown renderizado, panel
lateral en formato tabla, barra de estado inferior, spinner + efecto typewriter
y notificaciones toast.

Ejecutar:
    agente-tui
    # o
    python -m interfaces.tui_app

No forma parte del núcleo: solo recibe la fachada (vía `factory`) y llama a sus
métodos. La identidad visual vive en `tui_theme` y `tui_app.tcss`; los widgets a
medida en `tui_widgets`. Crece añadiendo widgets aquí, sin tocar el núcleo.
"""

from __future__ import annotations

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.suggester import SuggestFromList
from textual.widgets import Footer, Header, Input, Rule, Static

from agente.core.types import AgentResult, StepType
from agente.errors import AgenteError
from agente.service.agent_service import AgentService
from interfaces import tui_theme as T
from interfaces.commands import SLASH_TOOLS, parse_command
from interfaces.tui_widgets import ChatMessage, SidePanel, StatusBar


class AgenteTUI(App):
    """App TUI de chat con el agente orquestador."""

    TITLE = "Agente"
    SUB_TITLE = "orquestador de IA"
    CSS_PATH = "tui_app.tcss"

    BINDINGS = [
        Binding("ctrl+n", "new_session", "Nueva conversación"),
        Binding("ctrl+b", "toggle_side", "Panel lateral"),
        Binding("ctrl+q", "quit", "Salir"),
    ]

    def __init__(self, service: AgentService) -> None:
        super().__init__()
        self._service = service
        self._session_id = ""
        self._total_tokens = 0
        self._last_steps: int | str = "-"
        self._pending: ChatMessage | None = None

    # ------------------------------------------------------------------ #
    # Composición y arranque
    # ------------------------------------------------------------------ #

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Rule(id="top-rule", line_style="heavy")
        with Horizontal(id="body"):
            yield VerticalScroll(id="chat")
            yield Rule(orientation="vertical", id="body-rule", line_style="heavy")
            yield SidePanel(id="side")
        yield StatusBar(id="status-bar")
        suggester = SuggestFromList(
            [f"{cmd} " for cmd in SLASH_TOOLS], case_sensitive=False
        )
        yield Input(
            placeholder="Escribe una tarea y pulsa Enter  (prueba /claude …)",
            id="prompt",
            suggester=suggester,
        )
        yield Static(
            "Enter enviar  ·  Ctrl+N nueva  ·  Ctrl+B panel  ·  Ctrl+Q salir",
            id="hint",
        )
        yield Footer()

    def on_mount(self) -> None:
        self.register_theme(T.RUBY_CHARCOAL_TWILIGHT)
        self.theme = T.THEME_NAME

        self._chat().border_title = "conversación"
        self.query_one("#side", SidePanel).border_title = "panel"

        self._session_id = self._service.create_session()
        self._refresh_side()
        self._set_state(T.STATE_READY)

        self._add_message(
            "system",
            "Bienvenido. Escribe una tarea abajo y pulsa Enter.",
            label="·",
        )
        if not self._service.settings.has_api_key:
            self.notify(
                "Falta AGENTE_MINIMAX_API_KEY en .env; las tareas fallarán.",
                title="Configuración",
                severity="warning",
                timeout=8,
            )
        else:
            self.notify("Sesión lista.", title="Agente", severity="information")
        self._prompt().focus()

    # ------------------------------------------------------------------ #
    # Eventos
    # ------------------------------------------------------------------ #

    @on(Input.Submitted, "#prompt")
    async def _on_submit(self, event: Input.Submitted) -> None:
        raw = event.value.strip()
        if not raw:
            return

        task, force_tool = parse_command(raw)
        if force_tool and not task:
            self.notify(
                "Indica una tarea tras el comando, p. ej. '/claude crea x'.",
                title="Comando incompleto",
                severity="warning",
            )
            return

        prompt = self._prompt()
        prompt.value = ""
        prompt.disabled = True

        await self._mount(ChatMessage("user", raw))
        self._pending = ChatMessage("assistant")
        await self._mount(self._pending)
        self._pending.start_spinner()
        self._set_state(T.STATE_THINKING)

        self._run_task(task, force_tool)

    # ------------------------------------------------------------------ #
    # Trabajo en hilo (run_task es síncrono y hace I/O de red)
    # ------------------------------------------------------------------ #

    @work(thread=True, exclusive=True)
    def _run_task(self, task: str, force_tool: str | None = None) -> None:
        try:
            result = self._service.run_task(
                self._session_id, task, force_tool=force_tool
            )
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
        pending = self._pending
        self._pending = None

        if not result.completed:
            if pending is not None:
                pending.stop_spinner()
                pending.remove()
            self._show_error(result.error or "tarea no completada")
            return

        output = result.output or ""
        if pending is not None:
            pending.typewriter(output, on_done=lambda: pending.render_markdown(output))
        else:
            self._add_message("assistant", output)

        self._render_trace(result)

        self._total_tokens += result.usage.total_tokens
        self._last_steps = len(result.steps)
        self._refresh_side()
        self._set_state(T.STATE_OK)
        self.notify(
            f"{len(result.steps)} pasos · {result.usage.total_tokens} tokens",
            title="Tarea completada",
            severity="information",
        )
        self._enable_input()

    def _render_trace(self, result: AgentResult) -> None:
        for step in result.steps:
            if step.type is StepType.TOOL:
                ok = step.detail.get("ok")
                glyph = T.TOOL_OK if ok else T.TOOL_ERR
                color = "#5FB37A" if ok else T.RUBY
                res = (step.detail.get("result", "") or "").replace("\n", " ")[:80]
                tool = step.detail.get("tool")
                self._add_message(
                    "tool",
                    f"[{color}]{glyph}[/] [b]{tool}[/] → {res}",
                    label="traza",
                )
            else:
                calls = step.detail.get("tool_calls") or []
                if calls:
                    names = ", ".join(c["name"] for c in calls)
                    self._add_message("tool", f"razona → pide: {names}", label="traza")

    def _show_error(self, message: str) -> None:
        self._pending = None
        self._add_message("error", message)
        self._set_state(T.STATE_ERROR)
        self.notify(message, title="Error", severity="error", timeout=8)
        self._enable_input()

    # ------------------------------------------------------------------ #
    # Acciones
    # ------------------------------------------------------------------ #

    def action_new_session(self) -> None:
        self._service.close_session(self._session_id)
        self._session_id = self._service.create_session()
        self._total_tokens = 0
        self._last_steps = "-"
        self._pending = None
        chat = self._chat()
        chat.remove_children()
        self._add_message("system", "Nueva conversación.", label="·")
        self._refresh_side()
        self._set_state(T.STATE_READY)
        self.notify("Nueva conversación iniciada.", title="Agente")
        self._enable_input()

    def action_toggle_side(self) -> None:
        self.query_one("#side", SidePanel).toggle_class("hidden")

    # ------------------------------------------------------------------ #
    # Utilidades de UI
    # ------------------------------------------------------------------ #

    def _chat(self) -> VerticalScroll:
        return self.query_one("#chat", VerticalScroll)

    def _prompt(self) -> Input:
        return self.query_one("#prompt", Input)

    async def _mount(self, message: ChatMessage) -> None:
        await self._chat().mount(message)
        self._chat().scroll_end(animate=False)

    def _add_message(self, role: str, text: str, *, label: str | None = None) -> None:
        """Monta un mensaje estático (sin spinner/typewriter) y baja el scroll."""
        self._chat().mount(ChatMessage(role, text, label=label))
        self._chat().scroll_end(animate=False)

    def _enable_input(self) -> None:
        prompt = self._prompt()
        prompt.disabled = False
        prompt.focus()

    def _set_state(self, state: tuple[str, str]) -> None:
        s = self._service.settings
        fs_mode = "system" if s.fs_access_mode == "system" else "scoped"
        self.query_one("#status-bar", StatusBar).set_status(
            state=state,
            model=s.model,
            fs_mode=fs_mode,
            steps=self._last_steps,
            tokens=self._total_tokens,
        )

    def _refresh_side(self) -> None:
        s = self._service.settings
        fs_mode = "system (-dap)" if s.fs_access_mode == "system" else "scoped"
        self.query_one("#side", SidePanel).refresh_data(
            model=s.model,
            max_steps=s.max_steps,
            fs_mode=fs_mode,
            tokens=self._total_tokens,
            tools=self._service.list_tools(),
            commands=[(prefix, tool) for prefix, tool in SLASH_TOOLS.items()],
            has_api_key=s.has_api_key,
        )


def main() -> None:
    # Silencia los logs para no corromper la pantalla del TUI (el orquestador
    # registra en stderr a nivel INFO durante run_task).
    import argparse

    from factory.builder import build_service, build_settings

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

    settings = build_settings(dap=args.dap, log_level="CRITICAL")
    service = build_service(settings)
    AgenteTUI(service=service).run()


if __name__ == "__main__":
    main()
