"""Herramienta de sistema de ficheros con sandbox.

Todas las operaciones se restringen a un directorio raíz (`root`). Se resuelven
las rutas y se rechaza cualquier intento de salir del sandbox (path traversal).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agente.core.types import ToolResult
from agente.ports.tool import Tool

_MAX_READ_BYTES = 200_000


class FileSystemTool(Tool):
    name = "filesystem"
    description = (
        "Lee, escribe o lista ficheros dentro de un directorio de trabajo "
        "controlado. Operaciones: 'read' (lee un fichero), 'write' (crea o "
        "sobrescribe un fichero) y 'list' (lista el contenido de un directorio). "
        "Las rutas son relativas al directorio de trabajo; no se puede salir de él."
    )
    parameters = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["read", "write", "list"],
                "description": "Operación a realizar.",
            },
            "path": {
                "type": "string",
                "description": "Ruta relativa al directorio de trabajo (p. ej. 'notas.txt').",
            },
            "content": {
                "type": "string",
                "description": "Contenido a escribir (solo para 'write').",
            },
        },
        "required": ["operation", "path"],
    }

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def run(self, **kwargs: Any) -> ToolResult:
        operation = kwargs.get("operation")
        path = kwargs.get("path")
        content = kwargs.get("content")

        if operation not in ("read", "write", "list"):
            return ToolResult.failure("'operation' debe ser 'read', 'write' o 'list'.")
        if not isinstance(path, str) or not path:
            return ToolResult.failure("Se requiere 'path' (string no vacío).")

        try:
            target = self._resolve(path)
        except _OutsideSandbox as exc:
            return ToolResult.failure(str(exc))

        if operation == "read":
            return self._read(target)
        if operation == "write":
            return self._write(target, content)
        return self._list(target)

    # ------------------------------------------------------------------ #

    def _resolve(self, path: str) -> Path:
        candidate = (self._root / path).resolve()
        if candidate != self._root and self._root not in candidate.parents:
            raise _OutsideSandbox(
                f"Ruta fuera del directorio de trabajo: {path!r}"
            )
        return candidate

    def _read(self, target: Path) -> ToolResult:
        if not target.is_file():
            return ToolResult.failure(f"No existe el fichero: {self._rel(target)}")
        data = target.read_bytes()[:_MAX_READ_BYTES]
        text = data.decode("utf-8", errors="replace")
        return ToolResult.success(text)

    def _write(self, target: Path, content: Any) -> ToolResult:
        if not isinstance(content, str):
            return ToolResult.failure("'content' es obligatorio (string) para 'write'.")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return ToolResult.success(
            f"Escritos {len(content)} caracteres en {self._rel(target)}."
        )

    def _list(self, target: Path) -> ToolResult:
        if not target.exists():
            return ToolResult.failure(f"No existe la ruta: {self._rel(target)}")
        if target.is_file():
            return ToolResult.success(self._rel(target))
        entries = sorted(
            f"{'[dir] ' if p.is_dir() else '      '}{p.name}" for p in target.iterdir()
        )
        listing = "\n".join(entries) if entries else "(directorio vacío)"
        return ToolResult.success(listing)

    def _rel(self, target: Path) -> str:
        try:
            return str(target.relative_to(self._root)) or "."
        except ValueError:
            return str(target)


class _OutsideSandbox(Exception):
    """Intento de acceder fuera del directorio de trabajo."""
