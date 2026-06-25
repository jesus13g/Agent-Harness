"""Adaptador CLI mínimo (ejemplo).

Interfaz delgada que demuestra el patrón de extensión: construye la `AgentService`
mediante la raíz de composición (`factory`) y solo llama a sus métodos. Cualquier
otra interfaz (REST, WebSocket, chat) se construye igual, sin tocar el núcleo.

Uso:
    agente "¿Cuánto es (12**2 + 8) / 4?"
    agente                       # modo interactivo (REPL)
    agente -dap ...              # acceso total al sistema de ficheros
    python -m interfaces.cli ... # equivalente sin instalar el script
"""

from __future__ import annotations

import argparse
import sys

from agente.service.agent_service import AgentService
from factory.builder import build_service, build_settings
from interfaces.commands import parse_command


def _dispatch(service: AgentService, session_id: str, raw: str):
    """Parsea posibles comandos ('/claude ...') y ejecuta la tarea."""
    task, force_tool = parse_command(raw)
    if force_tool and not task:
        return None  # comando sin tarea: el llamador lo trata como entrada vacía
    return service.run_task(session_id, task, force_tool=force_tool)


def _run_once(service: AgentService, raw: str) -> int:
    session_id = service.create_session()
    result = _dispatch(service, session_id, raw)
    if result is None:
        print("[error] indica una tarea tras el comando, p. ej. '/claude crea x'.",
              file=sys.stderr)
        return 1
    if result.completed:
        print(result.output)
        return 0
    print(f"[no completado] {result.error}", file=sys.stderr)
    return 1


def _repl(service: AgentService) -> int:
    session_id = service.create_session()
    print("Agente listo. Escribe una tarea (Ctrl-D o 'salir' para terminar).")
    print("Pista: empieza con '/claude <tarea>' para delegarla en Claude Code.")
    while True:
        try:
            raw = input("› ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if raw.lower() in {"salir", "exit", "quit"}:
            return 0
        if not raw:
            continue
        result = _dispatch(service, session_id, raw)
        if result is None:
            print("[error] indica una tarea tras el comando, p. ej. '/claude crea x'.")
            continue
        print(result.output if result.completed else f"[error] {result.error}")


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="agente",
        description="Agente orquestador (CLI de ejemplo).",
    )
    parser.add_argument(
        "-dap",
        action="store_true",
        help="Acceso total al sistema de ficheros (salvo carpetas delicadas y secretos).",
    )
    parser.add_argument(
        "task",
        nargs="*",
        help="Tarea a ejecutar. Si se omite, arranca el modo interactivo (REPL).",
    )
    args = parser.parse_args()

    service = build_service(build_settings(dap=args.dap))
    if args.task:
        return _run_once(service, " ".join(args.task))
    return _repl(service)


if __name__ == "__main__":
    raise SystemExit(main())
