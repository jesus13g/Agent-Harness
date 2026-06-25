"""Widgets a medida de la TUI (capa de interfaz, sin lógica de núcleo).

Contiene las piezas visuales reutilizables:

- `ChatMessage`: burbuja de chat con estilo por rol; soporta spinner de
  "pensando", efecto typewriter y render final en Markdown.
- `StatusBar`: barra de estado inferior (estado · modelo · modo fs · pasos ·
  tokens).
- `SidePanel`: panel lateral en formato tabla (`DataTable`).

Todo el color procede de `tui_theme` (hex de la paleta) para que las celdas de
`DataTable`/`Static` sean deterministas y no dependan de tokens del tema en el
markup.
"""

from __future__ import annotations

from rich.text import Text
from textual.containers import Vertical
from textual.widgets import DataTable, Markdown, Static

from interfaces import tui_theme as T

# Etiqueta visible por rol de mensaje.
ROLE_LABELS = {
    "user": "tú",
    "assistant": "agente",
    "error": "error",
    "tool": "herramienta",
    "system": "·",
}


class ChatMessage(Vertical):
    """Una burbuja de mensaje con cabecera de rol y cuerpo.

    El cuerpo arranca como `Static` (texto plano / destino del typewriter) y, en
    las respuestas del agente, se sustituye por un `Markdown` al terminar el
    tecleo para obtener render estilizado y resaltado de sintaxis.
    """

    def __init__(self, role: str, text: str = "", *, label: str | None = None) -> None:
        super().__init__()
        self._role = role
        self._initial = text
        self._label = label or ROLE_LABELS.get(role, role)
        self.add_class(f"msg-{role}")
        self._spin_timer = None
        self._spin_i = 0
        self._spin_label = "pensando"
        self._tw_timer = None
        self._tw_text = ""
        self._tw_i = 0
        self._tw_chunk = 4
        self._tw_done = None

    def compose(self):
        yield Static(self._label, classes="bubble-role")
        yield Static(self._initial, classes="bubble-body")

    @property
    def body(self) -> Static:
        return self.query_one(".bubble-body", Static)

    # ------------------------------------------------------------------ #
    # Spinner ("pensando…")
    # ------------------------------------------------------------------ #

    def start_spinner(self, label: str = "pensando") -> None:
        self._spin_label = label
        self._spin_i = 0
        self._spin_timer = self.set_interval(0.08, self._tick_spinner)

    def _tick_spinner(self) -> None:
        frame = T.SPINNER_FRAMES[self._spin_i % len(T.SPINNER_FRAMES)]
        self._spin_i += 1
        self.body.update(f"[{T.ROSE}]{frame}[/] [dim]{self._spin_label}…[/]")
        self.scroll_visible(animate=False)

    def stop_spinner(self) -> None:
        if self._spin_timer is not None:
            self._spin_timer.stop()
            self._spin_timer = None

    # ------------------------------------------------------------------ #
    # Typewriter
    # ------------------------------------------------------------------ #

    def typewriter(
        self,
        text: str,
        *,
        cap: int = 600,
        chunk: int = 4,
        interval: float = 0.005,
        on_done=None,
    ) -> None:
        """Revela `text` con efecto de tecleo; de golpe si supera `cap`."""
        self.stop_spinner()
        if len(text) > cap:
            self.body.update(text)
            self.scroll_visible(animate=False)
            if on_done is not None:
                on_done()
            return
        self._tw_text = text
        self._tw_i = 0
        self._tw_chunk = chunk
        self._tw_done = on_done
        self._tw_timer = self.set_interval(interval, self._tick_tw)

    def _tick_tw(self) -> None:
        self._tw_i += self._tw_chunk
        self.body.update(self._tw_text[: self._tw_i])
        self.scroll_visible(animate=False)
        if self._tw_i >= len(self._tw_text):
            if self._tw_timer is not None:
                self._tw_timer.stop()
                self._tw_timer = None
            done, self._tw_done = self._tw_done, None
            if done is not None:
                done()

    # ------------------------------------------------------------------ #
    # Render Markdown final
    # ------------------------------------------------------------------ #

    def render_markdown(self, text: str) -> None:
        """Sustituye el cuerpo plano por un `Markdown` estilizado."""
        self.mount(Markdown(text))
        try:
            self.body.remove()
        except Exception:  # noqa: BLE001 — el cuerpo ya pudo desaparecer
            pass
        self.scroll_visible(animate=False)


class StatusBar(Static):
    """Barra de estado inferior con indicadores visuales."""

    def set_status(
        self,
        *,
        state: tuple[str, str],
        model: str,
        fs_mode: str,
        steps: int | str,
        tokens: int,
    ) -> None:
        glyph, color = self._state_color(state)
        parts = [
            f"[{color}]{glyph}[/] {self._state_label(state)}",
            f"[dim]modelo[/] {model}",
            f"[dim]fs[/] {fs_mode}",
            f"[dim]pasos[/] {steps}",
            f"[dim]tokens[/] {tokens}",
        ]
        self.update("   [dim]│[/]   ".join(parts))

    @staticmethod
    def _state_color(state: tuple[str, str]) -> tuple[str, str]:
        glyph, token = state
        mapping = {
            "$secondary": T.TWILIGHT,
            "$accent": T.ROSE,
            "$success": "#5FB37A",
            "$error": T.RUBY,
        }
        return glyph, mapping.get(token, T.ROSE)

    @staticmethod
    def _state_label(state: tuple[str, str]) -> str:
        labels = {
            T.STATE_READY: "listo",
            T.STATE_THINKING: "pensando",
            T.STATE_OK: "completado",
            T.STATE_ERROR: "error",
        }
        return labels.get(state, "listo")


class SidePanel(Vertical):
    """Panel lateral con la configuración y herramientas en formato tabla."""

    def compose(self):
        table = DataTable(
            id="side-table",
            show_header=False,
            cursor_type="none",
            zebra_stripes=False,
        )
        table.add_columns("k", "v")
        yield table

    def refresh_data(
        self,
        *,
        model: str,
        max_steps: int,
        fs_mode: str,
        tokens: int,
        tools: list[str],
        commands: list[tuple[str, str]],
        has_api_key: bool,
    ) -> None:
        table = self.query_one(DataTable)
        table.clear()
        self._section(table, "CONFIGURACIÓN")
        table.add_row(self._key("modelo"), Text(model, style=T.ROSE))
        table.add_row(self._key("máx pasos"), Text(str(max_steps)))
        table.add_row(self._key("modo fs"), Text(fs_mode))
        table.add_row(self._key("tokens"), Text(str(tokens), style="bold"))

        self._section(table, "HERRAMIENTAS")
        if tools:
            for name in tools:
                table.add_row(Text(f"{T.TOOL_OK} ", style=T.TWILIGHT) + Text(name), "")
        else:
            table.add_row(Text("(ninguna)", style="dim"), "")

        self._section(table, "COMANDOS")
        if commands:
            for prefix, label in commands:
                table.add_row(
                    Text(f"{prefix} <tarea>", style=f"bold {T.ROSE}"),
                    Text(label, style="dim"),
                )
        else:
            table.add_row(Text("(ninguno)", style="dim"), "")

        if not has_api_key:
            self._section(table, "AVISO")
            table.add_row(Text("falta API key", style=f"bold {T.RUBY}"), "")
            table.add_row(Text("AGENTE_MINIMAX_API_KEY", style=T.RUBY), "")

    @staticmethod
    def _section(table: DataTable, title: str) -> None:
        table.add_row(Text(title, style=f"bold {T.ROSE}"), "")

    @staticmethod
    def _key(label: str) -> Text:
        return Text(label, style="dim")
