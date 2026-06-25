"""Comandos de barra ('/...') para las interfaces.

Permite que el usuario fuerce una herramienta escribiendo un prefijo antes de su
tarea, p. ej. `/claude crea hola.py`. Es lógica de interfaz (no del núcleo): solo
traduce un prefijo a (tarea, nombre_de_herramienta_forzada).

Crece añadiendo entradas a `SLASH_TOOLS`.
"""

from __future__ import annotations

# Prefijo de comando -> nombre de herramienta a forzar.
SLASH_TOOLS = {"/claude": "claude_code"}


def parse_command(text: str) -> tuple[str, str | None]:
    """Separa un posible comando de barra del resto del texto.

    Devuelve `(tarea, force_tool)`:
    - `/claude crea x`  -> ("crea x", "claude_code")
    - `hola`            -> ("hola", None)
    - comando desconocido (`/otro ...`) -> se trata como tarea normal.
    """
    stripped = text.strip()
    if not stripped.startswith("/"):
        return stripped, None

    head, _, rest = stripped.partition(" ")
    tool = SLASH_TOOLS.get(head.lower())
    if tool is None:
        return stripped, None
    return rest.strip(), tool
