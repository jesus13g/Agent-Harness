"""Pruebas de las herramientas y el registro."""

from __future__ import annotations

import base64
import os
from pathlib import Path

import pytest

from agente.core.types import ToolResult
from agente.infra.tools.calculator import CalculatorTool
from agente.infra.tools.claude_code import (
    ClaudeCodeTool,
    CodeAgentResult,
    CodeAgentUnavailable,
)
from agente.infra.tools.claude_code.sanitize import clean_output, clean_task
from agente.infra.tools.filesystem import FileSystemTool, default_denied_roots
from agente.infra.tools.registry import ToolRegistry


# --- Calculator -------------------------------------------------------------


@pytest.mark.parametrize(
    "expr,expected",
    [
        ("2 + 3 * 4", "14"),
        ("(12**2 + 8) / 4", "38.0"),
        ("sqrt(16)", "4.0"),
        ("factorial(5)", "120"),
        ("2 ** 10", "1024"),
    ],
)
def test_calculator_ok(expr, expected):
    result = CalculatorTool().run(expression=expr)
    assert result.ok
    assert result.content == expected


def test_calculator_rejects_division_by_zero():
    result = CalculatorTool().run(expression="1/0")
    assert not result.ok
    assert "cero" in result.error.lower()


def test_calculator_rejects_unsafe_code():
    result = CalculatorTool().run(expression="__import__('os').system('echo hi')")
    assert not result.ok


def test_calculator_requires_expression():
    assert not CalculatorTool().run().ok


# --- FileSystem -------------------------------------------------------------


def test_filesystem_write_read_list(workspace):
    tool = FileSystemTool(root=workspace)

    write = tool.run(operation="write", path="notas.txt", content="hola")
    assert write.ok

    read = tool.run(operation="read", path="notas.txt")
    assert read.ok and read.content == "hola"

    listing = tool.run(operation="list", path=".")
    assert listing.ok and "notas.txt" in listing.content


def test_filesystem_blocks_path_traversal(workspace):
    tool = FileSystemTool(root=workspace)
    result = tool.run(operation="read", path="../../secreto.txt")
    assert not result.ok
    assert "fuera del directorio" in result.error


def test_filesystem_read_missing_file(workspace):
    tool = FileSystemTool(root=workspace)
    assert not tool.run(operation="read", path="noexiste.txt").ok


# --- FileSystem: niveles de acceso y bloqueos -------------------------------


def test_scoped_blocks_secret_files(workspace):
    tool = FileSystemTool(root=workspace)  # block_secrets=True por defecto
    for secret in (".env", "id_rsa", "cert.pem"):
        result = tool.run(operation="read", path=secret)
        assert not result.ok
        assert "secretos" in result.error.lower()


def test_system_access_reads_outside_cwd(tmp_path):
    target = tmp_path / "fuera.txt"
    target.write_text("contenido externo", encoding="utf-8")

    tool = FileSystemTool(system_access=True)
    result = tool.run(operation="read", path=str(target))
    assert result.ok
    assert result.content == "contenido externo"


def test_system_access_blocks_denied_root(tmp_path):
    blocked = tmp_path / "sys"
    blocked.mkdir()
    (blocked / "f.txt").write_text("x", encoding="utf-8")

    tool = FileSystemTool(system_access=True, denied_roots=[blocked])

    read = tool.run(operation="read", path=str(blocked / "f.txt"))
    assert not read.ok and "sistema protegida" in read.error.lower()

    write = tool.run(operation="write", path=str(blocked / "nuevo.txt"), content="x")
    assert not write.ok and "sistema protegida" in write.error.lower()

    listing = tool.run(operation="list", path=str(blocked))
    assert not listing.ok and "sistema protegida" in listing.error.lower()


def test_system_access_blocks_secrets(tmp_path):
    tool = FileSystemTool(system_access=True, denied_roots=[])
    for secret in ("id_ed25519", "clave.pem", ".env"):
        result = tool.run(operation="read", path=str(tmp_path / secret))
        assert not result.ok
        assert "secretos" in result.error.lower()


def test_system_access_can_disable_secret_block(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("AGENTE_MINIMAX_API_KEY=zzz", encoding="utf-8")

    tool = FileSystemTool(system_access=True, denied_roots=[], block_secrets=False)
    result = tool.run(operation="read", path=str(env_file))
    assert result.ok and "zzz" in result.content


def test_filesystem_search_recursive(workspace):
    tool = FileSystemTool(root=workspace)
    tool.run(operation="write", path="a/b/objetivo.txt", content="x")
    tool.run(operation="write", path="otro.md", content="y")

    res = tool.run(operation="search", path=".", pattern="*.txt")
    assert res.ok
    assert "objetivo.txt" in res.content
    assert "otro.md" not in res.content


def test_filesystem_search_skips_secrets(workspace):
    tool = FileSystemTool(root=workspace)
    tool.run(operation="write", path="normal.txt", content="x")
    # El .env se crea en disco directamente (write lo bloquea por ser secreto).
    (Path(workspace) / ".env").write_text("secreto", encoding="utf-8")

    res = tool.run(operation="search", path=".", pattern="*")
    assert res.ok
    assert "normal.txt" in res.content
    assert ".env" not in res.content


def test_filesystem_search_system_prunes_denied(tmp_path):
    base = tmp_path / "base"
    (base / "ok").mkdir(parents=True)
    (base / "ok" / "found.log").write_text("x", encoding="utf-8")
    denied = base / "secreta"
    denied.mkdir()
    (denied / "found.log").write_text("y", encoding="utf-8")

    tool = FileSystemTool(system_access=True, denied_roots=[denied])
    res = tool.run(operation="search", path=str(base), pattern="*.log")
    assert res.ok
    assert "found.log" in res.content
    # Nada bajo la carpeta denegada debe aparecer.
    assert all("secreta" not in line for line in res.content.splitlines())


def test_filesystem_search_requires_pattern(workspace):
    tool = FileSystemTool(root=workspace)
    res = tool.run(operation="search", path=".")
    assert not res.ok
    assert "pattern" in res.error.lower()


def test_filesystem_search_no_matches(workspace):
    tool = FileSystemTool(root=workspace)
    res = tool.run(operation="search", path=".", pattern="*.zzz")
    assert res.ok
    assert "sin coincidencias" in res.content.lower()


def test_filesystem_append(workspace):
    tool = FileSystemTool(root=workspace)
    tool.run(operation="write", path="log.txt", content="linea1\n")
    res = tool.run(operation="append", path="log.txt", content="linea2\n")
    assert res.ok
    assert tool.run(operation="read", path="log.txt").content == "linea1\nlinea2\n"


def test_filesystem_mkdir(workspace):
    tool = FileSystemTool(root=workspace)
    res = tool.run(operation="mkdir", path="nueva/carpeta")
    assert res.ok
    assert (Path(workspace) / "nueva" / "carpeta").is_dir()


def test_filesystem_move_renames(workspace):
    tool = FileSystemTool(root=workspace)
    tool.run(operation="write", path="viejo.txt", content="x")
    res = tool.run(operation="move", path="viejo.txt", destination="sub/nuevo.txt")
    assert res.ok
    assert not (Path(workspace) / "viejo.txt").exists()
    assert (Path(workspace) / "sub" / "nuevo.txt").read_text(encoding="utf-8") == "x"


def test_filesystem_copy(workspace):
    tool = FileSystemTool(root=workspace)
    tool.run(operation="write", path="orig.txt", content="dato")
    res = tool.run(operation="copy", path="orig.txt", destination="copia.txt")
    assert res.ok
    assert (Path(workspace) / "orig.txt").exists()
    assert (Path(workspace) / "copia.txt").read_text(encoding="utf-8") == "dato"


def test_filesystem_move_requires_destination(workspace):
    tool = FileSystemTool(root=workspace)
    tool.run(operation="write", path="a.txt", content="x")
    res = tool.run(operation="move", path="a.txt")
    assert not res.ok
    assert "destination" in res.error.lower()


def test_filesystem_copy_refuses_overwrite(workspace):
    tool = FileSystemTool(root=workspace)
    tool.run(operation="write", path="a.txt", content="x")
    tool.run(operation="write", path="b.txt", content="y")
    res = tool.run(operation="copy", path="a.txt", destination="b.txt")
    assert not res.ok
    assert "ya existe" in res.error.lower()


def test_filesystem_delete_file(workspace):
    tool = FileSystemTool(root=workspace)
    tool.run(operation="write", path="borrame.txt", content="x")
    res = tool.run(operation="delete", path="borrame.txt")
    assert res.ok
    assert not (Path(workspace) / "borrame.txt").exists()


def test_filesystem_delete_nonempty_dir_requires_recursive(workspace):
    tool = FileSystemTool(root=workspace)
    tool.run(operation="write", path="dir/f.txt", content="x")

    res = tool.run(operation="delete", path="dir")
    assert not res.ok
    assert "no está vacío" in res.error.lower()

    res2 = tool.run(operation="delete", path="dir", recursive=True)
    assert res2.ok
    assert not (Path(workspace) / "dir").exists()


def test_filesystem_management_respects_secrets(workspace):
    tool = FileSystemTool(root=workspace)
    # No se puede borrar ni mover un fichero de secretos (bloqueado al resolver).
    (Path(workspace) / ".env").write_text("k", encoding="utf-8")
    assert not tool.run(operation="delete", path=".env").ok
    assert not tool.run(operation="copy", path="normal.txt", destination=".env").ok


def test_default_denied_roots_nonempty():
    roots = default_denied_roots()
    assert roots
    if os.name == "nt":
        joined = " ".join(str(p).lower() for p in roots)
        assert "windows" in joined


# --- FileSystem: edit, grep, stat, tree, read paginado ----------------------


def test_filesystem_edit_replaces_unique(workspace):
    tool = FileSystemTool(root=workspace)
    tool.run(operation="write", path="c.txt", content="hola mundo")
    res = tool.run(operation="edit", path="c.txt", find="mundo", replace="agente")
    assert res.ok
    assert tool.run(operation="read", path="c.txt").content == "hola agente"


def test_filesystem_edit_requires_unique_without_all(workspace):
    tool = FileSystemTool(root=workspace)
    tool.run(operation="write", path="c.txt", content="a a a")
    res = tool.run(operation="edit", path="c.txt", find="a", replace="b")
    assert not res.ok
    assert "3 veces" in res.error


def test_filesystem_edit_all(workspace):
    tool = FileSystemTool(root=workspace)
    tool.run(operation="write", path="c.txt", content="a a a")
    res = tool.run(operation="edit", path="c.txt", find="a", replace="b", all=True)
    assert res.ok
    assert tool.run(operation="read", path="c.txt").content == "b b b"


def test_filesystem_edit_missing_text(workspace):
    tool = FileSystemTool(root=workspace)
    tool.run(operation="write", path="c.txt", content="hola")
    res = tool.run(operation="edit", path="c.txt", find="adios", replace="x")
    assert not res.ok
    assert "no se encontró" in res.error.lower()


def test_filesystem_grep_finds_in_content(workspace):
    tool = FileSystemTool(root=workspace)
    tool.run(operation="write", path="a/uno.txt", content="rojo\nverde\nazul")
    tool.run(operation="write", path="dos.txt", content="amarillo")
    res = tool.run(operation="grep", path=".", regex="ver.e")
    assert res.ok
    assert "uno.txt:2" in res.content
    assert "amarillo" not in res.content


def test_filesystem_grep_filters_by_pattern(workspace):
    tool = FileSystemTool(root=workspace)
    tool.run(operation="write", path="a.txt", content="diana")
    tool.run(operation="write", path="a.md", content="diana")
    res = tool.run(operation="grep", path=".", regex="diana", pattern="*.md")
    assert res.ok
    assert "a.md" in res.content
    assert "a.txt" not in res.content


def test_filesystem_grep_skips_secrets(workspace):
    tool = FileSystemTool(root=workspace)
    (Path(workspace) / ".env").write_text("clave_secreta", encoding="utf-8")
    tool.run(operation="write", path="normal.txt", content="clave_secreta")
    res = tool.run(operation="grep", path=".", regex="clave_secreta")
    assert res.ok
    assert "normal.txt" in res.content
    assert ".env" not in res.content


def test_filesystem_grep_invalid_regex(workspace):
    tool = FileSystemTool(root=workspace)
    res = tool.run(operation="grep", path=".", regex="[")
    assert not res.ok
    assert "regular" in res.error.lower()


def test_filesystem_stat(workspace):
    tool = FileSystemTool(root=workspace)
    tool.run(operation="write", path="f.txt", content="12345")
    res = tool.run(operation="stat", path="f.txt")
    assert res.ok
    assert "fichero" in res.content
    assert "5 bytes" in res.content


def test_filesystem_tree(workspace):
    tool = FileSystemTool(root=workspace)
    tool.run(operation="write", path="a/b/hoja.txt", content="x")
    res = tool.run(operation="tree", path=".")
    assert res.ok
    assert "[dir] a" in res.content
    assert "hoja.txt" in res.content


def test_filesystem_tree_depth_limit(workspace):
    tool = FileSystemTool(root=workspace)
    tool.run(operation="write", path="a/b/hoja.txt", content="x")
    res = tool.run(operation="tree", path=".", limit=1)
    assert res.ok
    assert "[dir] a" in res.content
    assert "hoja.txt" not in res.content


def test_filesystem_read_offset_limit(workspace):
    tool = FileSystemTool(root=workspace)
    tool.run(operation="write", path="f.txt", content="l1\nl2\nl3\nl4\n")
    res = tool.run(operation="read", path="f.txt", offset=2, limit=2)
    assert res.ok
    assert "l2" in res.content and "l3" in res.content
    assert "l1" not in res.content and "l4" not in res.content
    assert "líneas 2-3 de 4" in res.content


# --- FileSystem: insert / replace_lines -------------------------------------


def test_filesystem_insert_middle(workspace):
    tool = FileSystemTool(root=workspace)
    tool.run(operation="write", path="f.txt", content="l1\nl3\n")
    res = tool.run(operation="insert", path="f.txt", offset=2, content="l2")
    assert res.ok
    assert tool.run(operation="read", path="f.txt").content == "l1\nl2\nl3\n"


def test_filesystem_insert_at_end(workspace):
    tool = FileSystemTool(root=workspace)
    tool.run(operation="write", path="f.txt", content="l1\n")
    res = tool.run(operation="insert", path="f.txt", offset=2, content="l2")
    assert res.ok
    assert tool.run(operation="read", path="f.txt").content == "l1\nl2\n"


def test_filesystem_insert_offset_out_of_range(workspace):
    tool = FileSystemTool(root=workspace)
    tool.run(operation="write", path="f.txt", content="l1\n")
    res = tool.run(operation="insert", path="f.txt", offset=5, content="x")
    assert not res.ok
    assert "fuera de rango" in res.error.lower()


def test_filesystem_replace_lines(workspace):
    tool = FileSystemTool(root=workspace)
    tool.run(operation="write", path="f.txt", content="a\nb\nc\nd\n")
    res = tool.run(operation="replace_lines", path="f.txt", offset=2, limit=2, content="X")
    assert res.ok
    assert tool.run(operation="read", path="f.txt").content == "a\nX\nd\n"


def test_filesystem_replace_lines_delete(workspace):
    tool = FileSystemTool(root=workspace)
    tool.run(operation="write", path="f.txt", content="a\nb\nc\n")
    res = tool.run(operation="replace_lines", path="f.txt", offset=2, limit=1, content="")
    assert res.ok
    assert tool.run(operation="read", path="f.txt").content == "a\nc\n"


def test_filesystem_replace_lines_offset_out_of_range(workspace):
    tool = FileSystemTool(root=workspace)
    tool.run(operation="write", path="f.txt", content="a\n")
    res = tool.run(operation="replace_lines", path="f.txt", offset=5, limit=1, content="x")
    assert not res.ok
    assert "fuera de rango" in res.error.lower()


# --- FileSystem: binarios base64 --------------------------------------------


def test_filesystem_base64_roundtrip(workspace):
    tool = FileSystemTool(root=workspace)
    data = b"\x00\x01\xff\xfe binario"
    b64 = base64.b64encode(data).decode("ascii")
    write = tool.run(operation="write", path="bin.dat", content=b64, encoding="base64")
    assert write.ok
    read = tool.run(operation="read", path="bin.dat", encoding="base64")
    assert read.ok
    assert base64.b64decode(read.content) == data


def test_filesystem_base64_read_rejects_offset(workspace):
    tool = FileSystemTool(root=workspace)
    tool.run(operation="write", path="f.txt", content="hola")
    res = tool.run(operation="read", path="f.txt", encoding="base64", offset=1)
    assert not res.ok


def test_filesystem_base64_write_invalid(workspace):
    tool = FileSystemTool(root=workspace)
    res = tool.run(
        operation="write", path="x.dat", content="esto no es base64 !!!", encoding="base64"
    )
    assert not res.ok
    assert "base64" in res.error.lower()


# --- FileSystem: overwrite uniforme -----------------------------------------


def test_filesystem_write_overwrites_by_default(workspace):
    tool = FileSystemTool(root=workspace)
    tool.run(operation="write", path="f.txt", content="a")
    res = tool.run(operation="write", path="f.txt", content="b")
    assert res.ok
    assert tool.run(operation="read", path="f.txt").content == "b"


def test_filesystem_write_refuses_overwrite_when_disabled(workspace):
    tool = FileSystemTool(root=workspace)
    tool.run(operation="write", path="f.txt", content="a")
    res = tool.run(operation="write", path="f.txt", content="b", overwrite=False)
    assert not res.ok
    assert "ya existe" in res.error.lower()


def test_filesystem_copy_overwrite_flag(workspace):
    tool = FileSystemTool(root=workspace)
    tool.run(operation="write", path="a.txt", content="x")
    tool.run(operation="write", path="b.txt", content="y")
    assert not tool.run(operation="copy", path="a.txt", destination="b.txt").ok
    res = tool.run(operation="copy", path="a.txt", destination="b.txt", overwrite=True)
    assert res.ok
    assert tool.run(operation="read", path="b.txt").content == "x"


def test_filesystem_move_overwrite_flag(workspace):
    tool = FileSystemTool(root=workspace)
    tool.run(operation="write", path="a.txt", content="x")
    tool.run(operation="write", path="b.txt", content="y")
    assert not tool.run(operation="move", path="a.txt", destination="b.txt").ok
    res = tool.run(operation="move", path="a.txt", destination="b.txt", overwrite=True)
    assert res.ok
    assert tool.run(operation="read", path="b.txt").content == "x"
    assert not (Path(workspace) / "a.txt").exists()


# --- FileSystem: grep contexto / multilínea ---------------------------------


def test_filesystem_grep_context(workspace):
    tool = FileSystemTool(root=workspace)
    tool.run(operation="write", path="f.txt", content="a\nMATCH\nc\n")
    res = tool.run(operation="grep", path=".", regex="MATCH", before=1, after=1)
    assert res.ok
    assert "f.txt:2: MATCH" in res.content
    assert "f.txt-1- a" in res.content
    assert "f.txt-3- c" in res.content


def test_filesystem_grep_multiline(workspace):
    tool = FileSystemTool(root=workspace)
    tool.run(operation="write", path="f.txt", content="foo\nbar\n")
    sin_ml = tool.run(operation="grep", path=".", regex="foo.bar")
    assert "sin coincidencias" in sin_ml.content.lower()
    con_ml = tool.run(operation="grep", path=".", regex="foo.bar", multiline=True)
    assert con_ml.ok and "f.txt" in con_ml.content


# --- FileSystem: stat / list enriquecidos -----------------------------------


def test_filesystem_stat_includes_permissions(workspace):
    tool = FileSystemTool(root=workspace)
    tool.run(operation="write", path="f.txt", content="x")
    res = tool.run(operation="stat", path="f.txt")
    assert res.ok
    assert "permisos:" in res.content
    assert "acceso:" in res.content


def test_filesystem_list_long_shows_size(workspace):
    tool = FileSystemTool(root=workspace)
    tool.run(operation="write", path="f.txt", content="12345")
    res = tool.run(operation="list", path=".", long=True)
    assert res.ok
    assert "f.txt" in res.content
    assert "5" in res.content
    # Sin 'long' se mantiene el formato simple.
    simple = tool.run(operation="list", path=".")
    assert "f.txt" in simple.content


# --- Claude Code ------------------------------------------------------------


class _FakeBackend:
    """Doble del CodeAgentBackend: devuelve un resultado o lanza una excepción."""

    def __init__(self, *, result=None, raises=None):
        self._result = result
        self._raises = raises
        self.calls = []

    def run_task(self, task, *, cwd):
        self.calls.append((task, cwd))
        if self._raises is not None:
            raise self._raises
        return self._result


def test_claude_code_success_returns_output():
    backend = _FakeBackend(result=CodeAgentResult(output="hecho", ok=True, cost_usd=0.1))
    tool = ClaudeCodeTool(backend, cwd="/proj")
    res = tool.run(task="crea hola.py")
    assert res.ok and res.content == "hecho"
    assert backend.calls == [("crea hola.py", "/proj")]


def test_claude_code_failure_surfaces_error():
    backend = _FakeBackend(
        result=CodeAgentResult(output="", ok=False, error="el test falló")
    )
    res = ClaudeCodeTool(backend).run(task="arregla el bug")
    assert not res.ok
    assert "el test falló" in res.error


def test_claude_code_unavailable_returns_failure():
    backend = _FakeBackend(raises=CodeAgentUnavailable("falta el SDK"))
    res = ClaudeCodeTool(backend).run(task="haz algo")
    assert not res.ok
    assert "falta el SDK" in res.error


def test_claude_code_unexpected_error_is_captured():
    backend = _FakeBackend(raises=RuntimeError("boom"))
    res = ClaudeCodeTool(backend).run(task="haz algo")
    assert not res.ok
    assert "boom" in res.error


def test_claude_code_requires_task():
    backend = _FakeBackend(result=CodeAgentResult(output="x"))
    assert not ClaudeCodeTool(backend).run().ok
    assert not ClaudeCodeTool(backend).run(task="   ").ok
    assert backend.calls == []  # ni se invoca el backend


# --- Claude Code: saneo de entrada/salida -----------------------------------


def test_clean_task_strips_and_rejects_empty():
    assert clean_task("  hola  ") == "hola"
    assert clean_task("") == ""
    assert clean_task(None) == ""
    assert clean_task(123) == ""


def test_clean_task_truncates_long_input():
    assert len(clean_task("a" * 50_000)) == 20_000


def test_clean_output_prefers_result_text():
    out = clean_output(["paso intermedio"], "resumen final")
    assert out == "resumen final"


def test_clean_output_falls_back_to_assistant_texts():
    out = clean_output(["linea1", "", "linea2"], None)
    assert "linea1" in out and "linea2" in out


def test_clean_output_collapses_blank_lines():
    out = clean_output([], "a\n\n\n\nb")
    assert out == "a\n\nb"


def test_clean_output_empty_returns_placeholder():
    assert clean_output([], None) == "(el agente no devolvió salida)"


def test_clean_output_truncates():
    out = clean_output([], "x" * 50_000)
    assert "truncado" in out
    assert len(out) <= 20_000 + 60


# --- Registry ---------------------------------------------------------------


def test_registry_executes_and_lists():
    registry = ToolRegistry([CalculatorTool()])
    assert registry.names() == ["calculator"]
    assert len(registry.specs()) == 1

    result = registry.execute("calculator", {"expression": "1+1"})
    assert result.ok and result.content == "2"


def test_registry_unknown_tool_returns_failure():
    registry = ToolRegistry([])
    result = registry.execute("nope", {})
    assert not result.ok
    assert "desconocida" in result.error.lower()


def test_registry_invalid_arguments_returns_failure():
    registry = ToolRegistry([CalculatorTool()])
    result = registry.execute("calculator", {"unexpected": 1})
    assert isinstance(result, ToolResult)
    assert not result.ok


def test_registry_rejects_duplicate():
    with pytest.raises(ValueError):
        ToolRegistry([CalculatorTool(), CalculatorTool()])
