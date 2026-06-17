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
import shutil
from pathlib import Path
from typing import Any

from agente.core.types import ToolResult
from agente.ports.tool import Tool

_MAX_READ_BYTES = 200_000
_MAX_SEARCH_RESULTS = 500


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
                "enum": [
                    "read", "write", "list", "search",
                    "append", "mkdir", "move", "copy", "delete",
                ],
                "description": "Operación a realizar.",
            },
            "path": {
                "type": "string",
                "description": (
                    "Ruta del fichero o directorio. Para 'search', el directorio "
                    "base. Para 'move'/'copy', el origen."
                ),
            },
            "content": {
                "type": "string",
                "description": "Contenido a escribir (para 'write' y 'append').",
            },
            "pattern": {
                "type": "string",
                "description": (
                    "Patrón glob de nombre de fichero para 'search', "
                    "p. ej. '*.txt' o 'informe*.pdf'."
                ),
            },
            "destination": {
                "type": "string",
                "description": (
                    "Ruta destino para 'move' (mover/renombrar) y 'copy'."
                ),
            },
            "recursive": {
                "type": "boolean",
                "description": (
                    "Para 'delete' de un directorio no vacío: si es true, borra "
                    "el directorio y todo su contenido. Por defecto false."
                ),
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
        ops = (
            "Operaciones: 'read', 'write', 'list', 'search' (busqueda recursiva "
            "por nombre con 'pattern' glob desde un directorio base 'path'), "
            "'append' (añade 'content' al final), 'mkdir' (crea un directorio), "
            "'move' (mueve o renombra de 'path' a 'destination'), 'copy' (copia "
            "de 'path' a 'destination') y 'delete' (borra; para directorios no "
            "vacios usa 'recursive': true)."
        )
        if self._system:
            return (
                "Gestiona ficheros en CUALQUIER lugar del sistema. Puedes usar "
                "rutas absolutas (p. ej. 'C:\\\\Users\\\\...\\\\doc.txt') o "
                f"relativas al directorio actual. {ops} Las carpetas de sistema "
                f"(Windows, Program Files, etc.) están bloqueadas.{secrets}"
            )
        return (
            "Gestiona ficheros dentro del directorio de trabajo "
            f"('{self._root}'). {ops} Las rutas son relativas a ese directorio y "
            f"no se puede salir de él.{secrets}"
        )

    _OPERATIONS = (
        "read", "write", "list", "search",
        "append", "mkdir", "move", "copy", "delete",
    )

    def run(self, **kwargs: Any) -> ToolResult:
        operation = kwargs.get("operation")
        path = kwargs.get("path")
        content = kwargs.get("content")
        pattern = kwargs.get("pattern")
        destination = kwargs.get("destination")
        recursive = bool(kwargs.get("recursive", False))

        if operation not in self._OPERATIONS:
            return ToolResult.failure(
                f"'operation' debe ser uno de: {', '.join(self._OPERATIONS)}."
            )
        if not isinstance(path, str) or not path:
            return ToolResult.failure("Se requiere 'path' (string no vacío).")
        if operation in ("move", "copy") and (
            not isinstance(destination, str) or not destination
        ):
            return ToolResult.failure(
                f"Se requiere 'destination' (string no vacío) para '{operation}'."
            )

        try:
            target = self._resolve(path)
            dest = self._resolve(destination) if operation in ("move", "copy") else None
        except (_OutsideSandbox, _BlockedPath, _BlockedSecret) as exc:
            return ToolResult.failure(str(exc))

        if operation == "read":
            return self._read(target)
        if operation == "write":
            return self._write(target, content)
        if operation == "append":
            return self._append(target, content)
        if operation == "search":
            return self._search(target, pattern)
        if operation == "mkdir":
            return self._mkdir(target)
        if operation == "move":
            return self._move(target, dest)
        if operation == "copy":
            return self._copy(target, dest)
        if operation == "delete":
            return self._delete(target, recursive)
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
        if self._is_denied(candidate):
            raise _BlockedPath(f"Ruta de sistema protegida: {candidate}")

    def _is_denied(self, candidate: Path) -> bool:
        return any(
            candidate == denied or denied in candidate.parents
            for denied in self._denied
        )

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
            # write_bytes evita la traducción de saltos de línea, así lo escrito
            # se lee de vuelta byte a byte idéntico (coherente con _read).
            target.write_bytes(content.encode("utf-8"))
        except OSError as exc:
            return ToolResult.failure(f"No se pudo escribir {self._rel(target)}: {exc}")
        return ToolResult.success(
            f"Escritos {len(content)} caracteres en {self._rel(target)}."
        )

    def _append(self, target: Path, content: Any) -> ToolResult:
        if not isinstance(content, str):
            return ToolResult.failure("'content' es obligatorio (string) para 'append'.")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("ab") as fh:
                fh.write(content.encode("utf-8"))
        except OSError as exc:
            return ToolResult.failure(f"No se pudo añadir a {self._rel(target)}: {exc}")
        return ToolResult.success(
            f"Añadidos {len(content)} caracteres a {self._rel(target)}."
        )

    def _mkdir(self, target: Path) -> ToolResult:
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return ToolResult.failure(f"No se pudo crear {self._rel(target)}: {exc}")
        return ToolResult.success(f"Directorio creado: {self._rel(target)}.")

    def _move(self, src: Path, dst: Path | None) -> ToolResult:
        assert dst is not None
        if not src.exists():
            return ToolResult.failure(f"No existe el origen: {self._rel(src)}")
        if dst.exists():
            return ToolResult.failure(f"El destino ya existe: {self._rel(dst)}")
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
        except OSError as exc:
            return ToolResult.failure(f"No se pudo mover a {self._rel(dst)}: {exc}")
        return ToolResult.success(f"Movido {self._rel(src)} -> {self._rel(dst)}.")

    def _copy(self, src: Path, dst: Path | None) -> ToolResult:
        assert dst is not None
        if not src.exists():
            return ToolResult.failure(f"No existe el origen: {self._rel(src)}")
        if dst.exists():
            return ToolResult.failure(f"El destino ya existe: {self._rel(dst)}")
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.is_dir():
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)
        except OSError as exc:
            return ToolResult.failure(f"No se pudo copiar a {self._rel(dst)}: {exc}")
        return ToolResult.success(f"Copiado {self._rel(src)} -> {self._rel(dst)}.")

    def _delete(self, target: Path, recursive: bool) -> ToolResult:
        if not target.exists():
            return ToolResult.failure(f"No existe la ruta: {self._rel(target)}")
        try:
            if target.is_dir():
                if any(target.iterdir()) and not recursive:
                    return ToolResult.failure(
                        f"El directorio no está vacío: {self._rel(target)}. "
                        "Usa 'recursive': true para borrarlo con su contenido."
                    )
                shutil.rmtree(target) if recursive else target.rmdir()
            else:
                target.unlink()
        except OSError as exc:
            return ToolResult.failure(f"No se pudo borrar {self._rel(target)}: {exc}")
        return ToolResult.success(f"Borrado: {self._rel(target)}.")

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

    def _search(self, base: Path, pattern: Any) -> ToolResult:
        if not isinstance(pattern, str) or not pattern:
            return ToolResult.failure(
                "Se requiere 'pattern' (glob de nombre, p. ej. '*.txt') para 'search'."
            )
        if not base.is_dir():
            return ToolResult.failure(f"El directorio base no existe: {self._rel(base)}")

        matches: list[str] = []
        truncated = False
        # os.walk con onerror permite saltar carpetas sin permisos sin abortar.
        for dirpath, dirnames, filenames in os.walk(base, onerror=lambda _e: None):
            current = Path(dirpath)
            # Podar carpetas bloqueadas para no descender en ellas.
            kept = []
            for name in dirnames:
                child = (current / name).resolve()
                if self._system and self._is_denied(child):
                    continue
                if self._block_secrets and self._is_secret(child):
                    continue
                kept.append(name)
            dirnames[:] = kept

            for name in filenames:
                if not fnmatch.fnmatch(name, pattern):
                    continue
                full = current / name
                if self._block_secrets and self._is_secret(full):
                    continue
                matches.append(self._rel(full))
                if len(matches) >= _MAX_SEARCH_RESULTS:
                    truncated = True
                    break
            if truncated:
                break

        if not matches:
            return ToolResult.success(
                f"Sin coincidencias para {pattern!r} en {self._rel(base)}."
            )
        result = "\n".join(sorted(matches))
        if truncated:
            result += f"\n(resultados truncados a {_MAX_SEARCH_RESULTS})"
        return ToolResult.success(result)

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
