"""Jerarquía de excepciones del agente."""

from __future__ import annotations


class AgenteError(Exception):
    """Base de todos los errores del dominio."""


class ConfigError(AgenteError):
    """Configuración inválida o incompleta (p. ej. falta la API key)."""


class LLMError(AgenteError):
    """Fallo al comunicarse con el proveedor del modelo o respuesta inválida."""


class ToolError(AgenteError):
    """Fallo controlado dentro de una herramienta.

    Las herramientas no deben propagar excepciones arbitrarias: las capturan y
    devuelven un `ToolResult` fallido. Esta excepción se usa para errores de
    registro/resolución (p. ej. herramienta inexistente).
    """


class SessionNotFoundError(AgenteError):
    """Se solicitó una sesión que no existe."""
