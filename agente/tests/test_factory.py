"""Pruebas de la raíz de composición (`factory`)."""

from __future__ import annotations

from agente.infra.tools.registry import ToolRegistry
from agente.service.agent_service import AgentService
from factory.builder import build_registry, build_settings


def test_build_settings_default_scoped():
    settings = build_settings()
    assert settings.fs_access_mode == "scoped"


def test_build_settings_dap_enables_system_access():
    settings = build_settings(dap=True)
    assert settings.fs_access_mode == "system"


def test_build_settings_log_level_override():
    settings = build_settings(log_level="CRITICAL")
    assert settings.log_level == "CRITICAL"


def test_build_registry_includes_base_tools(settings):
    # `settings` (de conftest) desactiva la búsqueda web.
    registry = build_registry(settings)
    assert isinstance(registry, ToolRegistry)
    names = registry.names()
    assert "calculator" in names
    assert "filesystem" in names
    assert "web_search" not in names


def test_build_registry_with_web_search(settings):
    settings.enable_web_search = True
    registry = build_registry(settings)
    assert "web_search" in registry.names()


def test_agent_service_requires_injected_dependencies(settings):
    # DIP estricto: la fachada no autoconstruye; exige llm y tools.
    import pytest

    with pytest.raises(TypeError):
        AgentService(settings)  # type: ignore[call-arg]
