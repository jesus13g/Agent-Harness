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

import base64
import binascii
import fnmatch
import os
import re
import shutil
from datetime import datetime, timezone
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
                    "read", "write", "list", "search", "append", "mkdir",
                    "move", "copy", "delete", "edit", "grep", "stat", "tree",
                    "insert", "replace_lines",
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
            "find": {
                "type": "string",
                "description": (
                    "Para 'edit': texto exacto a localizar y reemplazar dentro "
                    "del fichero. Debe ser único salvo que 'all' sea true."
                ),
            },
            "replace": {
                "type": "string",
                "description": (
                    "Para 'edit': texto por el que se sustituye 'find'. Puede "
                    "ser cadena vacía para eliminar el fragmento."
                ),
            },
            "all": {
                "type": "boolean",
                "description": (
                    "Para 'edit': si es true reemplaza TODAS las ocurrencias de "
                    "'find'. Por defecto false (exige una única coincidencia)."
                ),
            },
            "regex": {
                "type": "string",
                "description": (
                    "Para 'grep': expresión regular a buscar dentro del "
                    "contenido de los ficheros (bajo el directorio 'path')."
                ),
            },
            "offset": {
                "type": "integer",
                "description": (
                    "Número de línea (1 = primera). Para 'read': primera línea a "
                    "devolver. Para 'insert': línea ANTES de la cual insertar "
                    "'content'. Para 'replace_lines': primera línea a sustituir."
                ),
            },
            "limit": {
                "type": "integer",
                "description": (
                    "Para 'read': número máximo de líneas desde 'offset'. Para "
                    "'replace_lines': número de líneas a sustituir desde 'offset'. "
                    "Para 'tree': profundidad máxima de descenso."
                ),
            },
            "encoding": {
                "type": "string",
                "enum": ["utf-8", "base64"],
                "description": (
                    "Codificación para 'read'/'write'. 'utf-8' (por defecto) para "
                    "texto; 'base64' para ficheros binarios (read devuelve base64; "
                    "write decodifica 'content' base64 a bytes)."
                ),
            },
            "overwrite": {
                "type": "boolean",
                "description": (
                    "Permite sobrescribir un destino existente. 'write': por "
                    "defecto true. 'move'/'copy': por defecto false (rechazan si "
                    "el destino existe)."
                ),
            },
            "before": {
                "type": "integer",
                "description": (
                    "Para 'grep': nº de líneas de contexto ANTES de cada "
                    "coincidencia (como -B). Por defecto 0."
                ),
            },
            "after": {
                "type": "integer",
                "description": (
                    "Para 'grep': nº de líneas de contexto DESPUÉS de cada "
                    "coincidencia (como -A). Por defecto 0."
                ),
            },
            "multiline": {
                "type": "boolean",
                "description": (
                    "Para 'grep': si es true, la regex puede cruzar saltos de "
                    "línea (modos MULTILINE y DOTALL). Por defecto false."
                ),
            },
            "long": {
                "type": "boolean",
                "description": (
                    "Para 'list': si es true, muestra tamaño y permisos de cada "
                    "entrada además del nombre. Por defecto false."
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
            "Operaciones: 'read' (lee; admite 'offset'/'limit' por líneas y "
            "'encoding': 'base64' para binarios), 'write' (escribe 'content'; "
            "'encoding': 'base64' para binarios; 'overwrite': false para no "
            "sobrescribir), 'edit' (reemplaza 'find' por 'replace' in-place; usa "
            "'all' para todas las ocurrencias), 'insert' (inserta 'content' antes "
            "de la línea 'offset'), 'replace_lines' (sustituye 'limit' líneas "
            "desde 'offset' por 'content'; 'content' vacío las borra), 'append' "
            "(añade 'content' al final), 'list' (lista un directorio; 'long': "
            "true añade tamaño y permisos), 'tree' (listado recursivo; 'limit' "
            "limita la profundidad), 'search' (busca por NOMBRE con 'pattern' "
            "glob de forma recursiva), 'grep' (busca por CONTENIDO con 'regex'; "
            "'before'/'after' dan contexto, 'multiline' cruza líneas, 'pattern' "
            "filtra ficheros), 'stat' (metadatos: tipo, tamaño, fecha, "
            "permisos), 'mkdir' (crea un directorio), 'move' (mueve/renombra de "
            "'path' a 'destination'; 'overwrite' para sobrescribir), 'copy' "
            "(copia de 'path' a 'destination'; 'overwrite' para sobrescribir) y "
            "'delete' (borra; para directorios no vacios usa 'recursive': true)."
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
        "read", "write", "list", "search", "append", "mkdir",
        "move", "copy", "delete", "edit", "grep", "stat", "tree",
        "insert", "replace_lines",
    )

    def run(self, **kwargs: Any) -> ToolResult:
        operation = kwargs.get("operation")
        path = kwargs.get("path")
        content = kwargs.get("content")
        pattern = kwargs.get("pattern")
        destination = kwargs.get("destination")
        recursive = bool(kwargs.get("recursive", False))
        find = kwargs.get("find")
        replace = kwargs.get("replace")
        replace_all = bool(kwargs.get("all", False))
        regex = kwargs.get("regex")
        offset = kwargs.get("offset")
        limit = kwargs.get("limit")
        encoding = kwargs.get("encoding", "utf-8")
        overwrite = kwargs.get("overwrite")  # None => default por operación
        before = kwargs.get("before")
        after = kwargs.get("after")
        multiline = bool(kwargs.get("multiline", False))
        long = bool(kwargs.get("long", False))

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
        if encoding not in ("utf-8", "base64"):
            return ToolResult.failure("'encoding' debe ser 'utf-8' o 'base64'.")

        try:
            target = self._resolve(path)
            dest = self._resolve(destination) if operation in ("move", "copy") else None
        except (_OutsideSandbox, _BlockedPath, _BlockedSecret) as exc:
            return ToolResult.failure(str(exc))

        if operation == "read":
            return self._read(target, offset, limit, encoding)
        if operation == "write":
            return self._write(
                target, content, True if overwrite is None else bool(overwrite), encoding
            )
        if operation == "edit":
            return self._edit(target, find, replace, replace_all)
        if operation == "insert":
            return self._insert(target, offset, content)
        if operation == "replace_lines":
            return self._replace_lines(target, offset, limit, content)
        if operation == "append":
            return self._append(target, content)
        if operation == "search":
            return self._search(target, pattern)
        if operation == "grep":
            return self._grep(target, regex, pattern, before, after, multiline)
        if operation == "stat":
            return self._stat(target)
        if operation == "tree":
            return self._tree(target, limit)
        if operation == "mkdir":
            return self._mkdir(target)
        if operation == "move":
            return self._move(target, dest, bool(overwrite))
        if operation == "copy":
            return self._copy(target, dest, bool(overwrite))
        if operation == "delete":
            return self._delete(target, recursive)
        return self._list(target, long)

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

    def _read(
        self, target: Path, offset: Any, limit: Any, encoding: str = "utf-8"
    ) -> ToolResult:
        if not target.is_file():
            return ToolResult.failure(f"No existe el fichero: {self._rel(target)}")
        try:
            raw = target.read_bytes()
        except OSError as exc:
            return ToolResult.failure(f"No se pudo leer {self._rel(target)}: {exc}")

        truncated = len(raw) > _MAX_READ_BYTES

        if encoding == "base64":
            if offset is not None or limit is not None:
                return ToolResult.failure(
                    "'offset'/'limit' no son compatibles con 'encoding': 'base64'."
                )
            encoded = base64.b64encode(raw[:_MAX_READ_BYTES]).decode("ascii")
            if truncated:
                encoded += (
                    f"\n[contenido truncado a {_MAX_READ_BYTES} bytes antes de "
                    "codificar]"
                )
            return ToolResult.success(encoded)

        text = raw[:_MAX_READ_BYTES].decode("utf-8", errors="replace")

        # Lectura paginada por líneas (offset/limit) para ficheros grandes.
        if offset is not None or limit is not None:
            if offset is not None and (not isinstance(offset, int) or offset < 1):
                return ToolResult.failure("'offset' debe ser un entero >= 1.")
            if limit is not None and (not isinstance(limit, int) or limit < 1):
                return ToolResult.failure("'limit' debe ser un entero >= 1.")
            lines = text.splitlines(keepends=True)
            start = (offset - 1) if offset else 0
            end = (start + limit) if limit else len(lines)
            selected = lines[start:end]
            shown_to = start + len(selected)
            note = (
                f"\n[líneas {start + 1}-{shown_to} de {len(lines)}"
                f"{'+' if truncated else ''}]"
            )
            return ToolResult.success("".join(selected) + note)

        if truncated:
            text += (
                f"\n[contenido truncado a {_MAX_READ_BYTES} bytes; usa "
                "'offset'/'limit' para leer el resto por tramos]"
            )
        return ToolResult.success(text)

    def _edit(self, target: Path, find: Any, replace: Any, replace_all: bool) -> ToolResult:
        if not isinstance(find, str) or find == "":
            return ToolResult.failure("Se requiere 'find' (string no vacío) para 'edit'.")
        if not isinstance(replace, str):
            return ToolResult.failure("Se requiere 'replace' (string) para 'edit'.")
        if find == replace:
            return ToolResult.failure("'find' y 'replace' son idénticos; nada que hacer.")
        text, err = self._read_text_strict(target)
        if err is not None:
            return err
        assert text is not None

        count = text.count(find)
        if count == 0:
            return ToolResult.failure(
                f"No se encontró el texto a reemplazar en {self._rel(target)}."
            )
        if count > 1 and not replace_all:
            return ToolResult.failure(
                f"'find' aparece {count} veces en {self._rel(target)}; añade más "
                "contexto para que sea único o usa 'all': true."
            )
        new_text = text.replace(find, replace) if replace_all else text.replace(find, replace, 1)
        try:
            target.write_bytes(new_text.encode("utf-8"))
        except OSError as exc:
            return ToolResult.failure(f"No se pudo escribir {self._rel(target)}: {exc}")
        n = count if replace_all else 1
        return ToolResult.success(
            f"Reemplazada(s) {n} ocurrencia(s) en {self._rel(target)}."
        )

    def _read_text_strict(self, target: Path) -> tuple[str | None, ToolResult | None]:
        """Lee un fichero como texto UTF-8 estricto.

        Devuelve `(texto, None)` en éxito o `(None, ToolResult.failure)` si no
        existe, no se puede leer o no es UTF-8 (editar un binario lo corrompería).
        Lo comparten 'edit', 'insert' y 'replace_lines'.
        """
        if not target.is_file():
            return None, ToolResult.failure(f"No existe el fichero: {self._rel(target)}")
        try:
            raw = target.read_bytes()
        except OSError as exc:
            return None, ToolResult.failure(f"No se pudo leer {self._rel(target)}: {exc}")
        try:
            return raw.decode("utf-8"), None
        except UnicodeDecodeError:
            return None, ToolResult.failure(
                f"{self._rel(target)} no es texto UTF-8; no se puede editar por líneas."
            )

    def _insert(self, target: Path, offset: Any, content: Any) -> ToolResult:
        if not isinstance(content, str):
            return ToolResult.failure("'content' es obligatorio (string) para 'insert'.")
        if not isinstance(offset, int) or offset < 1:
            return ToolResult.failure(
                "'offset' debe ser un entero >= 1 (línea ante la cual insertar)."
            )
        text, err = self._read_text_strict(target)
        if err is not None:
            return err
        assert text is not None

        lines = text.splitlines(keepends=True)
        if offset > len(lines) + 1:
            return ToolResult.failure(
                f"'offset' {offset} fuera de rango: el fichero tiene "
                f"{len(lines)} líneas (máximo offset {len(lines) + 1})."
            )
        # El contenido insertado se trata como línea(s) completas.
        block = content if content.endswith("\n") else content + "\n"
        idx = offset - 1
        # Si se inserta al final, garantizar que la última línea cierre con salto.
        if idx == len(lines) and lines and not lines[-1].endswith(("\n", "\r")):
            lines[-1] += "\n"
        lines.insert(idx, block)
        try:
            target.write_bytes("".join(lines).encode("utf-8"))
        except OSError as exc:
            return ToolResult.failure(f"No se pudo escribir {self._rel(target)}: {exc}")
        return ToolResult.success(
            f"Insertado contenido antes de la línea {offset} en {self._rel(target)}."
        )

    def _replace_lines(
        self, target: Path, offset: Any, limit: Any, content: Any
    ) -> ToolResult:
        if not isinstance(content, str):
            return ToolResult.failure(
                "'content' es obligatorio (string) para 'replace_lines'. "
                "Usa una cadena vacía para borrar las líneas."
            )
        if not isinstance(offset, int) or offset < 1:
            return ToolResult.failure("'offset' debe ser un entero >= 1.")
        if not isinstance(limit, int) or limit < 1:
            return ToolResult.failure("'limit' debe ser un entero >= 1.")
        text, err = self._read_text_strict(target)
        if err is not None:
            return err
        assert text is not None

        lines = text.splitlines(keepends=True)
        if offset > len(lines):
            return ToolResult.failure(
                f"'offset' {offset} fuera de rango: el fichero tiene "
                f"{len(lines)} líneas."
            )
        start = offset - 1
        end = min(start + limit, len(lines))
        removed = end - start
        if content == "":
            replacement: list[str] = []
        else:
            block = content if content.endswith("\n") else content + "\n"
            replacement = [block]
        new_lines = lines[:start] + replacement + lines[end:]
        try:
            target.write_bytes("".join(new_lines).encode("utf-8"))
        except OSError as exc:
            return ToolResult.failure(f"No se pudo escribir {self._rel(target)}: {exc}")
        return ToolResult.success(
            f"Sustituidas {removed} línea(s) desde la {offset} en {self._rel(target)}."
        )

    def _write(
        self, target: Path, content: Any, overwrite: bool, encoding: str = "utf-8"
    ) -> ToolResult:
        if not isinstance(content, str):
            return ToolResult.failure("'content' es obligatorio (string) para 'write'.")
        if target.exists() and not overwrite:
            return ToolResult.failure(
                f"El destino ya existe: {self._rel(target)}. "
                "Usa 'overwrite': true para sobrescribirlo."
            )
        if encoding == "base64":
            try:
                data = base64.b64decode(content, validate=True)
            except (binascii.Error, ValueError) as exc:
                return ToolResult.failure(f"'content' no es base64 válido: {exc}")
        else:
            # write_bytes evita la traducción de saltos de línea, así lo escrito
            # se lee de vuelta byte a byte idéntico (coherente con _read).
            data = content.encode("utf-8")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        except OSError as exc:
            return ToolResult.failure(f"No se pudo escribir {self._rel(target)}: {exc}")
        return ToolResult.success(f"Escritos {len(data)} bytes en {self._rel(target)}.")

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

    def _clear_destination(self, dst: Path, overwrite: bool) -> ToolResult | None:
        """Prepara un destino existente para 'move'/'copy'.

        Devuelve None si el destino está libre o se ha borrado con `overwrite`;
        devuelve un `ToolResult.failure` si existe sin permiso o no se pudo borrar.
        """
        if not dst.exists():
            return None
        if not overwrite:
            return ToolResult.failure(
                f"El destino ya existe: {self._rel(dst)}. "
                "Usa 'overwrite': true para sobrescribirlo."
            )
        try:
            if dst.is_dir() and not dst.is_symlink():
                shutil.rmtree(dst)
            else:
                dst.unlink()
        except OSError as exc:
            return ToolResult.failure(f"No se pudo sobrescribir {self._rel(dst)}: {exc}")
        return None

    def _move(self, src: Path, dst: Path | None, overwrite: bool) -> ToolResult:
        assert dst is not None
        if not src.exists():
            return ToolResult.failure(f"No existe el origen: {self._rel(src)}")
        blocked = self._clear_destination(dst, overwrite)
        if blocked is not None:
            return blocked
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
        except OSError as exc:
            return ToolResult.failure(f"No se pudo mover a {self._rel(dst)}: {exc}")
        return ToolResult.success(f"Movido {self._rel(src)} -> {self._rel(dst)}.")

    def _copy(self, src: Path, dst: Path | None, overwrite: bool) -> ToolResult:
        assert dst is not None
        if not src.exists():
            return ToolResult.failure(f"No existe el origen: {self._rel(src)}")
        blocked = self._clear_destination(dst, overwrite)
        if blocked is not None:
            return blocked
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

    def _list(self, target: Path, long: bool = False) -> ToolResult:
        if not target.exists():
            return ToolResult.failure(f"No existe la ruta: {self._rel(target)}")
        if target.is_file():
            return ToolResult.success(self._rel(target))
        try:
            children = sorted(target.iterdir(), key=lambda p: p.name)
        except OSError as exc:
            return ToolResult.failure(f"No se pudo listar {self._rel(target)}: {exc}")
        if not children:
            return ToolResult.success("(directorio vacío)")
        entries = [self._list_entry(p, long) for p in children]
        return ToolResult.success("\n".join(entries))

    def _list_entry(self, p: Path, long: bool) -> str:
        prefix = "[dir] " if p.is_dir() else "      "
        if not long:
            return f"{prefix}{p.name}"
        try:
            st = p.stat()
            size = "-" if p.is_dir() else str(st.st_size)
            perms = oct(st.st_mode & 0o777)[2:]
        except OSError:
            size, perms = "?", "???"
        return f"{prefix}{size:>10}  {perms:>4}  {p.name}"

    def _search(self, base: Path, pattern: Any) -> ToolResult:
        if not isinstance(pattern, str) or not pattern:
            return ToolResult.failure(
                "Se requiere 'pattern' (glob de nombre, p. ej. '*.txt') para 'search'."
            )
        if not base.is_dir():
            return ToolResult.failure(f"El directorio base no existe: {self._rel(base)}")

        matches: list[str] = []
        truncated = False
        # _walk_files ya poda carpetas denegadas/secretas y filtra por glob.
        for full in self._walk_files(base, pattern):
            if self._block_secrets and self._is_secret(full):
                continue
            matches.append(self._rel(full))
            if len(matches) >= _MAX_SEARCH_RESULTS:
                truncated = True
                break

        if not matches:
            return ToolResult.success(
                f"Sin coincidencias para {pattern!r} en {self._rel(base)}."
            )
        result = "\n".join(sorted(matches))
        if truncated:
            result += f"\n(resultados truncados a {_MAX_SEARCH_RESULTS})"
        return ToolResult.success(result)

    def _grep(
        self,
        base: Path,
        regex: Any,
        pattern: Any,
        before: Any,
        after: Any,
        multiline: bool,
    ) -> ToolResult:
        if not isinstance(regex, str) or not regex:
            return ToolResult.failure(
                "Se requiere 'regex' (expresión regular) para 'grep'."
            )
        flags = (re.MULTILINE | re.DOTALL) if multiline else 0
        try:
            matcher = re.compile(regex, flags)
        except re.error as exc:
            return ToolResult.failure(f"Expresión regular inválida: {exc}")
        before_n = before if isinstance(before, int) and before > 0 else 0
        after_n = after if isinstance(after, int) and after > 0 else 0
        name_glob = pattern if isinstance(pattern, str) and pattern else "*"

        if base.is_file():
            files = [base]
        elif base.is_dir():
            files = self._walk_files(base, name_glob)
        else:
            return ToolResult.failure(f"No existe la ruta base: {self._rel(base)}")

        blocks: list[str] = []
        match_count = 0
        truncated = False
        for full in files:
            if self._block_secrets and self._is_secret(full):
                continue
            try:
                data = full.read_bytes()[:_MAX_READ_BYTES]
            except OSError:
                continue
            text = data.decode("utf-8", errors="replace")
            lines = text.splitlines()
            rel = self._rel(full)

            hit_lines = self._grep_hits(matcher, text, lines, multiline)
            if not hit_lines:
                continue
            hit_set = set(hit_lines)
            show: set[int] = set()
            for ln in hit_lines:
                lo = max(1, ln - before_n)
                hi = min(len(lines), ln + after_n)
                show.update(range(lo, hi + 1))

            file_lines: list[str] = []
            prev: int | None = None
            for ln in sorted(show):
                if prev is not None and ln != prev + 1:
                    file_lines.append("--")
                body = lines[ln - 1].strip()
                if ln in hit_set:
                    file_lines.append(f"{rel}:{ln}: {body}")
                    match_count += 1
                    if match_count >= _MAX_SEARCH_RESULTS:
                        truncated = True
                else:
                    file_lines.append(f"{rel}-{ln}- {body}")
                prev = ln
                if truncated:
                    break
            blocks.append("\n".join(file_lines))
            if truncated:
                break

        if not blocks:
            return ToolResult.success(
                f"Sin coincidencias para {regex!r} en {self._rel(base)}."
            )
        joiner = "\n--\n" if (before_n or after_n) else "\n"
        result = joiner.join(blocks)
        if truncated:
            result += f"\n(resultados truncados a {_MAX_SEARCH_RESULTS})"
        return ToolResult.success(result)

    @staticmethod
    def _grep_hits(
        matcher: re.Pattern[str], text: str, lines: list[str], multiline: bool
    ) -> list[int]:
        """Números de línea (1-based, ordenados y únicos) que casan con la regex."""
        hits: list[int] = []
        if multiline:
            seen: set[int] = set()
            for m in matcher.finditer(text):
                start_line = text.count("\n", 0, m.start()) + 1
                end_line = text.count("\n", 0, max(m.start(), m.end() - 1)) + 1
                for ln in range(start_line, end_line + 1):
                    if ln not in seen:
                        seen.add(ln)
                        hits.append(ln)
        else:
            for i, line in enumerate(lines, start=1):
                if matcher.search(line):
                    hits.append(i)
        return hits

    def _walk_files(self, base: Path, name_glob: str) -> list[Path]:
        """Recorre `base` devolviendo ficheros que casan con `name_glob`,
        podando carpetas denegadas (modo system) y de secretos."""
        found: list[Path] = []
        for dirpath, dirnames, filenames in os.walk(base, onerror=lambda _e: None):
            current = Path(dirpath)
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
                if fnmatch.fnmatch(name, name_glob):
                    found.append(current / name)
        return found

    def _stat(self, target: Path) -> ToolResult:
        if not target.exists():
            return ToolResult.failure(f"No existe la ruta: {self._rel(target)}")
        try:
            st = target.stat()
        except OSError as exc:
            return ToolResult.failure(f"No se pudo consultar {self._rel(target)}: {exc}")
        if target.is_dir():
            kind = "directorio"
        elif target.is_file():
            kind = "fichero"
        else:
            kind = "otro"
        mtime = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat()
        access = "".join(
            flag if os.access(target, mode) else "-"
            for flag, mode in (("r", os.R_OK), ("w", os.W_OK), ("x", os.X_OK))
        )
        lines = [
            f"ruta: {self._rel(target)}",
            f"tipo: {kind}",
            f"tamaño: {st.st_size} bytes",
            f"modificado: {mtime}",
            f"permisos: {oct(st.st_mode & 0o777)[2:]}",
            f"acceso: {access}",
            f"symlink: {'sí' if target.is_symlink() else 'no'}",
        ]
        if target.is_dir():
            try:
                lines.append(f"entradas: {sum(1 for _ in target.iterdir())}")
            except OSError:
                pass
        return ToolResult.success("\n".join(lines))

    def _tree(self, base: Path, limit: Any) -> ToolResult:
        if not base.is_dir():
            return ToolResult.failure(f"No es un directorio: {self._rel(base)}")
        if limit is not None and (not isinstance(limit, int) or limit < 1):
            return ToolResult.failure("'limit' (profundidad) debe ser un entero >= 1.")
        max_depth = limit if isinstance(limit, int) else None
        base_depth = len(base.resolve().parts)

        lines: list[str] = []
        truncated = False
        for dirpath, dirnames, filenames in os.walk(base, onerror=lambda _e: None):
            current = Path(dirpath)
            depth = len(current.resolve().parts) - base_depth
            if max_depth is not None and depth >= max_depth:
                dirnames[:] = []
            kept = []
            for name in sorted(dirnames):
                child = (current / name).resolve()
                if self._system and self._is_denied(child):
                    continue
                if self._block_secrets and self._is_secret(child):
                    continue
                kept.append(name)
                lines.append(f"{'  ' * (depth + 1)}[dir] {name}")
            dirnames[:] = kept
            for name in sorted(filenames):
                full = current / name
                if self._block_secrets and self._is_secret(full):
                    continue
                lines.append(f"{'  ' * (depth + 1)}      {name}")
            if len(lines) >= _MAX_SEARCH_RESULTS:
                truncated = True
                break

        header = f"{self._rel(base)}"
        body = "\n".join(lines) if lines else "  (vacío)"
        result = f"{header}\n{body}"
        if truncated:
            result += f"\n(listado truncado a {_MAX_SEARCH_RESULTS} entradas)"
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
