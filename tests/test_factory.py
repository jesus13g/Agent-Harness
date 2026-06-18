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


def test_browser_force_enabled(settings):
    settings.enable_browser = True
    assert "browser_scraper" in build_registry(settings).names()


def test_browser_force_disabled(settings):
    settings.enable_browser = False
    assert "browser_scraper" not in build_registry(settings).names()


def test_browser_auto_follows_playwright_availability(settings, monkeypatch):
    import importlib.util as iu

    settings.enable_browser = None  # AUTO

    real_find_spec = iu.find_spec

    def fake_find_spec(name, *args, **kwargs):
        if name == "playwright":
            return object()  # simula que está instalado
        return real_find_spec(name, *args, **kwargs)

    monkeypatch.setattr(iu, "find_spec", fake_find_spec)
    assert "browser_scraper" in build_registry(settings).names()

    def no_playwright(name, *args, **kwargs):
        if name == "playwright":
            return None
        return real_find_spec(name, *args, **kwargs)

    monkeypatch.setattr(iu, "find_spec", no_playwright)
    assert "browser_scraper" not in build_registry(settings).names()


def test_agent_service_requires_injected_dependencies(settings):
    # DIP estricto: la fachada no autoconstruye; exige llm y tools.
    import pytest

    with pytest.raises(TypeError):
        AgentService(settings)  # type: ignore[call-arg]
