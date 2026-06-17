"""Herramienta de sistema de ficheros con dos niveles de acceso.

Modos:
- **scoped** (por defecto): todas las operaciones se restringen a un directorio
  raíz (`root`, por defecto el directorio de trabajo actual). Se rechaza salir
  de él (path traversal).
- **system** (acceso total, se activa con `-dap`): permite rutas absolutas o
  relativas al CWD en todo el sistema, EXCEPTO carpetas delicadas
  (`default_denied_roots()`).

En ambos modos, si `block_secrets` está activo, se bloquean ficheros de secretos
(`.env`, claves SSH/AWS/GPG, `*.pem`, …) para que el agente no pueda leer su
propia API key ni credenciales del usuario.

`Path.resolve()` neutraliza `..` y enlaces simbólicos antes de comprobar las
listas de bloqueo, así que no se pueden evadir con rutas como
`C:\\Users\\..\\Windows`.
"""

from __future__ import annotations

import fnmatch
import os
from pathlib import Path
from typing import Any

from agente.core.types import ToolResult
from agente.ports.tool import Tool

_MAX_READ_BYTES = 200_000


def default_denied_roots() -> list[Path]:
    """Carpetas de sistema delicadas que se bloquean en modo total."""
    candidates: list[str] = []
    if os.name == "nt":
        env = os.environ
        candidates += [
            env.get("SystemRoot", r"C:\Windows"),
            env.get("windir", r"C:\Windows"),
            env.get("ProgramFiles", r"C:\Program Files"),
            env.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
            env.get("ProgramData", r"C:\ProgramData"),
            r"C:\$Recycle.Bin",
            r"C:\System Volume Information",
            r"C:\Recovery",
            r"C:\Boot",
        ]
    else:
        candidates += [
            "/etc", "/sys", "/proc", "/dev", "/boot", "/root",
            "/bin", "/sbin", "/usr/bin", "/usr/sbin", "/var",
        ]
    resolved: list[Path] = []
    seen: set[str] = set()
    for raw in candidates:
        try:
            p = Path(raw).resolve()
        except (OSError, ValueError):
            continue
        key = str(p).lower()
        if key not in seen:
            seen.add(key)
            resolved.append(p)
    return resolved


def default_secret_dirs() -> set[str]:
    """Nombres de directorio que contienen credenciales (cualquier nivel)."""
    return {".ssh", ".aws", ".gnupg", ".azure"}


def default_secret_patterns() -> list[str]:
    """Patrones de nombre de fichero considerados secretos."""
    return [
        ".env", ".env.*", "*.env",
        "id_rsa*", "id_dsa*", "id_ecdsa*", "id_ed25519*",
        "*.pem",
    ]


class FileSystemTool(Tool):
    name = "filesystem"
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
                "description": "Ruta del fichero o directorio.",
            },
            "content": {
                "type": "string",
                "description": "Contenido a escribir (solo para 'write').",
            },
        },
        "required": ["operation", "path"],
    }

    def __init__(
        self,
        root: str | Path | None = None,
        *,
        system_access: bool = False,
        denied_roots: list[str | Path] | None = None,
        block_secrets: bool = True,
    ) -> None:
        self._system = system_access
        self._block_secrets = block_secrets
        self._secret_dirs = default_secret_dirs()
        self._secret_patterns = default_secret_patterns()

        if system_access:
            roots = denied_roots if denied_roots is not None else default_denied_roots()
            self._denied = [Path(p).resolve() for p in roots]
            self._root = None
        else:
            self._root = Path(root or Path.cwd()).resolve()
            self._root.mkdir(parents=True, exist_ok=True)
            self._denied = []

        self.description = self._build_description()

    # ------------------------------------------------------------------ #

    def _build_description(self) -> str:
        secrets = (
            " Por seguridad, los ficheros de secretos (.env, claves SSH/AWS, "
            "*.pem) están bloqueados."
            if self._block_secrets
            else ""
        )
        if self._system:
            return (
                "Lee, escribe o lista ficheros en CUALQUIER lugar del sistema. "
                "Puedes usar rutas absolutas (p. ej. 'C:\\\\Users\\\\...\\\\doc.txt') "
                "o relativas al directorio actual. Operaciones: 'read', 'write', "
                "'list'. Las carpetas de sistema (Windows, Program Files, etc.) "
                f"están bloqueadas.{secrets}"
            )
        return (
            "Lee, escribe o lista ficheros dentro del directorio de trabajo "
            f"('{self._root}'). Operaciones: 'read', 'write', 'list'. Las rutas "
            f"son relativas a ese directorio y no se puede salir de él.{secrets}"
        )

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
        except _BlockedPath as exc:
            return ToolResult.failure(str(exc))
        except _BlockedSecret as exc:
            return ToolResult.failure(str(exc))

        if operation == "read":
            return self._read(target)
        if operation == "write":
            return self._write(target, content)
        return self._list(target)

    # ------------------------------------------------------------------ #
    # Resolución de rutas y políticas de acceso
    # ------------------------------------------------------------------ #

    def _resolve(self, path: str) -> Path:
        if self._system:
            candidate = Path(path)
            if not candidate.is_absolute():
                candidate = Path.cwd() / candidate
            candidate = candidate.resolve()
            self._check_denied(candidate)
        else:
            assert self._root is not None
            candidate = (self._root / path).resolve()
            if candidate != self._root and self._root not in candidate.parents:
                raise _OutsideSandbox(f"Ruta fuera del directorio de trabajo: {path!r}")

        if self._block_secrets and self._is_secret(candidate):
            raise _BlockedSecret(f"Fichero de secretos protegido: {path!r}")
        return candidate

    def _check_denied(self, candidate: Path) -> None:
        for denied in self._denied:
            if candidate == denied or denied in candidate.parents:
                raise _BlockedPath(f"Ruta de sistema protegida: {candidate}")

    def _is_secret(self, candidate: Path) -> bool:
        parts = {part.lower() for part in candidate.parts}
        if parts & {d.lower() for d in self._secret_dirs}:
            return True
        name = candidate.name.lower()
        return any(fnmatch.fnmatch(name, pat) for pat in self._secret_patterns)

    # ------------------------------------------------------------------ #
    # Operaciones
    # ------------------------------------------------------------------ #

    def _read(self, target: Path) -> ToolResult:
        if not target.is_file():
            return ToolResult.failure(f"No existe el fichero: {self._rel(target)}")
        try:
            data = target.read_bytes()[:_MAX_READ_BYTES]
        except OSError as exc:
            return ToolResult.failure(f"No se pudo leer {self._rel(target)}: {exc}")
        text = data.decode("utf-8", errors="replace")
        return ToolResult.success(text)

    def _write(self, target: Path, content: Any) -> ToolResult:
        if not isinstance(content, str):
            return ToolResult.failure("'content' es obligatorio (string) para 'write'.")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        except OSError as exc:
            return ToolResult.failure(f"No se pudo escribir {self._rel(target)}: {exc}")
        return ToolResult.success(
            f"Escritos {len(content)} caracteres en {self._rel(target)}."
        )

    def _list(self, target: Path) -> ToolResult:
        if not target.exists():
            return ToolResult.failure(f"No existe la ruta: {self._rel(target)}")
        if target.is_file():
            return ToolResult.success(self._rel(target))
        try:
            entries = sorted(
                f"{'[dir] ' if p.is_dir() else '      '}{p.name}"
                for p in target.iterdir()
            )
        except OSError as exc:
            return ToolResult.failure(f"No se pudo listar {self._rel(target)}: {exc}")
        listing = "\n".join(entries) if entries else "(directorio vacío)"
        return ToolResult.success(listing)

    def _rel(self, target: Path) -> str:
        if self._system or self._root is None:
            return str(target)
        try:
            return str(target.relative_to(self._root)) or "."
        except ValueError:
            return str(target)


class _OutsideSandbox(Exception):
    """Intento de acceder fuera del directorio de trabajo (modo scoped)."""


class _BlockedPath(Exception):
    """Intento de acceder a una carpeta de sistema protegida (modo total)."""


class _BlockedSecret(Exception):
    """Intento de acceder a un fichero de secretos protegido."""
