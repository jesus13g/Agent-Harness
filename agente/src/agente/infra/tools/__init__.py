"""Herramientas concretas y su registro."""

from agente.infra.tools.calculator import CalculatorTool
from agente.infra.tools.filesystem import FileSystemTool
from agente.infra.tools.registry import ToolRegistry
from agente.infra.tools.web_search import WebSearchTool

__all__ = [
    "ToolRegistry",
    "CalculatorTool",
    "FileSystemTool",
    "WebSearchTool",
]
