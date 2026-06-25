"""Saneo de la entrada y la salida del agente de programación (funciones puras).

Separadas del adaptador del SDK para poder probarlas de forma aislada (SRP) y
para mantener un único sitio donde se decide qué entra y qué sale del agente.
"""

from __future__ import annotations

import re

# Límite de la tarea que se envía al agente (evita prompts desbocados).
_MAX_TASK_CHARS = 20_000
# Límite de la salida que se reinyecta al orquestador (protege su contexto/tokens).
_MAX_OUTPUT_CHARS = 20_000

_BLANK_LINES = re.compile(r"\n{3,}")


def clean_task(raw: object) -> str:
    """Valida y normaliza la tarea de entrada.

    Devuelve "" si no es un string no vacío (el llamador lo trata como error).
    """
    if not isinstance(raw, str) or not raw.strip():
        return ""
    task = raw.strip()
    if len(task) > _MAX_TASK_CHARS:
        task = task[:_MAX_TASK_CHARS]
    return task


def clean_output(assistant_texts: list[str], result_text: str | None) -> str:
    """Construye la salida limpia que se reinyecta al orquestador.

    Prioriza `result_text` (el resumen final del agente). Si falta, recurre a la
    concatenación de los bloques de texto intermedios. Colapsa líneas en blanco
    repetidas y trunca a un máximo para no inundar el contexto del modelo.
    """
    text = (result_text or "").strip()
    if not text:
        text = "\n".join(t for t in assistant_texts if t and t.strip()).strip()
    if not text:
        return "(el agente no devolvió salida)"
    return _truncate(_collapse_blank_lines(text), _MAX_OUTPUT_CHARS)


def _collapse_blank_lines(text: str) -> str:
    return _BLANK_LINES.sub("\n\n", text).strip()


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... (truncado a {limit} caracteres)"
