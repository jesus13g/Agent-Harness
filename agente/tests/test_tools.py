"""Pruebas de las herramientas y el registro."""

from __future__ import annotations

import os

import pytest

from agente.core.types import ToolResult
from agente.infra.tools.calculator import CalculatorTool
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


def test_default_denied_roots_nonempty():
    roots = default_denied_roots()
    assert roots
    if os.name == "nt":
        joined = " ".join(str(p).lower() for p in roots)
        assert "windows" in joined


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
