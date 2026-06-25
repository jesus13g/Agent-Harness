"""Construcción del agente: ensambla configuración, LLM, herramientas y memoria.

Este módulo es el único que importa adaptadores concretos. Centraliza todo el
cableado que antes estaba disperso entre `AgentService.__init__` y cada interfaz
(el flag `-dap`, la elección del cliente LLM y del catálogo de herramientas).
"""

from __future__ import annotations

from agente.config.settings import Settings
from agente.infra.tools.registry import ToolRegistry
from agente.observability.logging import configure_logging
from agente.ports.llm_client import LLMClient
from agente.ports.tool import Tool
from agente.service.agent_service import AgentService


def build_settings(*, dap: bool = False, log_level: str | None = None) -> Settings:
    """Construye la configuración aplicando los overrides de las interfaces.

    - `dap`: acceso total al sistema de ficheros (`fs_access_mode = "system"`).
    - `log_level`: fuerza un nivel de log (p. ej. "CRITICAL" en la TUI para no
      corromper la pantalla).
    """
    settings = Settings()
    if dap:
        settings.fs_access_mode = "system"
    if log_level is not None:
        settings.log_level = log_level
    return settings


def build_llm(settings: Settings) -> LLMClient:
    """Instancia el cliente LLM concreto a partir de la configuración."""
    # Import local: mantiene el adaptador concreto fuera del import-time del paquete.
    from agente.infra.minimax_client import MiniMaxClient

    return MiniMaxClient(settings)


def build_registry(settings: Settings) -> ToolRegistry:
    """Construye el registro con las herramientas base habilitadas por config."""
    from agente.infra.tools.browser import BrowserScraperTool
    from agente.infra.tools.calculator import CalculatorTool
    from agente.infra.tools.claude_code import ClaudeCodeTool
    from agente.infra.tools.claude_code.sdk_backend import ClaudeAgentSdkBackend
    from agente.infra.tools.filesystem import FileSystemTool
    from agente.infra.tools.scraper import WebScraperTool
    from agente.infra.tools.web_search import WebSearchTool

    if settings.fs_access_mode == "system":
        fs_tool = FileSystemTool(
            system_access=True, block_secrets=settings.fs_block_secrets
        )
    else:
        fs_tool = FileSystemTool(
            root=settings.fs_root, block_secrets=settings.fs_block_secrets
        )

    tools: list[Tool] = [
        CalculatorTool(),
        fs_tool,
    ]
    if settings.enable_web_search:
        tools.append(WebSearchTool())
    if settings.enable_scraper:
        tools.append(WebScraperTool())
    if _browser_enabled(settings):
        tools.append(BrowserScraperTool())
    if _claude_code_enabled(settings):
        backend = ClaudeAgentSdkBackend(
            model=settings.claude_code_model,
            permission_mode=settings.claude_code_permission_mode,
            max_turns=settings.claude_code_max_turns,
            max_budget_usd=settings.claude_code_max_budget_usd,
        )
        # En scoped, el agente trabaja dentro del sandbox de ficheros; en system
        # (-dap), sin restricción de directorio. Coherente con FileSystemTool.
        cwd = None if settings.fs_access_mode == "system" else settings.fs_root
        tools.append(ClaudeCodeTool(backend, cwd=cwd))
    return ToolRegistry(tools)


def _browser_enabled(settings: Settings) -> bool:
    """Decide si registrar el scraper de navegador.

    `enable_browser` None significa AUTO: se habilita solo si Playwright está
    instalado, evitando que el usuario tenga que tocar un flag a mano. Un valor
    explícito (True/False) manda sobre la detección.
    """
    if settings.enable_browser is not None:
        return settings.enable_browser
    from importlib.util import find_spec

    return find_spec("playwright") is not None


def _claude_code_enabled(settings: Settings) -> bool:
    """Decide si registrar la herramienta de delegación a Claude Code.

    `enable_claude_code` None significa AUTO: se habilita solo si el Claude
    Agent SDK está instalado. Un valor explícito (True/False) manda sobre la
    detección. Igual que `_browser_enabled` con Playwright.
    """
    if settings.enable_claude_code is not None:
        return settings.enable_claude_code
    from importlib.util import find_spec

    return find_spec("claude_agent_sdk") is not None


def build_service(settings: Settings) -> AgentService:
    """Ensambla una `AgentService` lista para ejecutar tareas."""
    configure_logging(settings.log_level, settings.log_format)
    return AgentService(
        settings,
        llm=build_llm(settings),
        tools=build_registry(settings),
    )
