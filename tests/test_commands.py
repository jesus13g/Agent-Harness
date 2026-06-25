"""Pruebas del parser de comandos de barra de las interfaces."""

from __future__ import annotations

from interfaces.commands import parse_command


def test_plain_text_has_no_force_tool():
    assert parse_command("crea hola.py") == ("crea hola.py", None)


def test_claude_command_forces_tool_and_keeps_task():
    assert parse_command("/claude crea hola.py") == ("crea hola.py", "claude_code")


def test_claude_command_is_case_insensitive():
    assert parse_command("/CLAUDE arregla el bug") == ("arregla el bug", "claude_code")


def test_claude_command_without_task():
    # Sin tarea tras el comando: la interfaz lo trata como entrada vacía.
    assert parse_command("/claude") == ("", "claude_code")
    assert parse_command("/claude   ") == ("", "claude_code")


def test_unknown_command_is_treated_as_task():
    assert parse_command("/otro haz algo") == ("/otro haz algo", None)


def test_strips_surrounding_whitespace():
    assert parse_command("   /claude  x  ") == ("x", "claude_code")
