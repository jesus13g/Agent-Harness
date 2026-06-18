"""Raíz de composición (composition root) del agente.

Único paquete que conoce adaptadores concretos (MiniMax, herramientas, memoria)
y los cablea en una `AgentService` lista para usar. Tanto el núcleo (`agente`)
como las interfaces dependen de abstracciones; solo aquí se instancian concretos.
"""

from __future__ import annotations

from factory.builder import build_llm, build_registry, build_service, build_settings

__all__ = ["build_llm", "build_registry", "build_service", "build_settings"]
