"""Puertos: contratos abstractos que el núcleo usa para hablar con el exterior.

Los adaptadores concretos viven en `agente.infra` e implementan estos puertos.
"""

from agente.ports.llm_client import LLMClient
from agente.ports.memory import Memory
from agente.ports.tool import Tool

__all__ = ["LLMClient", "Memory", "Tool"]
