"""Tema y constantes visuales de la TUI.

Aísla la identidad visual (paleta *Ruby Charcoal Twilight*, glifos de estado y
fotogramas del spinner) del resto de la interfaz. No depende del núcleo; solo lo
consumen `tui_app` y `tui_widgets`.

Estilo en Unicode (sin emojis): bullets `●`, spinner braille y separadores de
línea fina. La paleta procede de la guía de Figma "Ruby Charcoal Twilight".
"""

from __future__ import annotations

from textual.theme import Theme

THEME_NAME = "ruby-charcoal-twilight"

# --- Paleta cruda (hex de la guía) -------------------------------------- #
CHARCOAL = "#0E0E0E"  # fondo
WARM_GRAY = "#504141"  # gris cálido (tenue)
RUBY = "#D41414"  # acento principal / error
ROSE = "#E19B8B"  # acento secundario (mauve)
TWILIGHT = "#403963"  # bordes / secundario
DEEP_PURPLE = "#310A69"  # realces profundos

# Tonos derivados (la paleta no trae verde/ámbar legibles para estados).
_SUCCESS = "#5FB37A"
_WARNING = "#E1B45E"
_FOREGROUND = "#ECE3E1"


RUBY_CHARCOAL_TWILIGHT = Theme(
    name=THEME_NAME,
    dark=True,
    background=CHARCOAL,
    surface="#1A1416",
    panel="#221B2E",
    primary=RUBY,
    secondary=TWILIGHT,
    accent=ROSE,
    foreground=_FOREGROUND,
    success=_SUCCESS,
    warning=_WARNING,
    error=RUBY,
    variables={
        "block-cursor-foreground": CHARCOAL,
        "block-cursor-background": ROSE,
        "border": TWILIGHT,
        "border-blurred": WARM_GRAY,
        "scrollbar": TWILIGHT,
        "scrollbar-hover": ROSE,
        "scrollbar-active": RUBY,
        "input-selection-background": f"{DEEP_PURPLE} 60%",
    },
)


# --- Estados visuales --------------------------------------------------- #
# Cada estado: (glifo, color del tema). El color usa tokens del tema ($...).
STATE_READY = ("●", "$secondary")
STATE_THINKING = ("◐", "$accent")
STATE_OK = ("●", "$success")
STATE_ERROR = ("●", "$error")

# Fotogramas del spinner braille (tecleo/proceso).
SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

# Marcadores de resultado de herramienta.
TOOL_OK = "●"
TOOL_ERR = "●"
