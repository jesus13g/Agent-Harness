"""Núcleo de un agente orquestador de IA sobre MiniMax.

Arquitectura hexagonal (ports & adapters): el núcleo no conoce ni al proveedor
de LLM ni a ninguna interfaz. Todo el acceso externo pasa por la fachada
`AgentService`.
"""

from agente.service.agent_service import AgentService
from agente.config.settings import Settings

__all__ = ["AgentService", "Settings"]
__version__ = "0.1.0"
