"""Puerto de herramienta.

Una herramienta declara su esquema (nombre, descripción, parámetros JSON
Schema) y su ejecución. El orquestador solo conoce este contrato; añadir una
herramienta nueva no requiere tocar el núcleo.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from agente.core.types import ToolResult, ToolSpec


class Tool(ABC):
    """Contrato de una herramienta ejecutable por el agente."""

    #: Nombre único de la herramienta (lo usa el modelo para invocarla).
    name: str
    #: Descripción para el modelo: cuándo y para qué usarla.
    description: str
    #: JSON Schema de los argumentos (formato OpenAI function parameters).
    parameters: dict[str, Any]

    @abstractmethod
    def run(self, **kwargs: Any) -> ToolResult:
        """Ejecuta la herramienta con los argumentos dados.

        Una herramienta NO debe lanzar excepciones por errores esperables:
        debe capturarlas y devolver ``ToolResult.failure(...)`` para que el
        modelo pueda recuperarse.
        """
        raise NotImplementedError

    def spec(self) -> ToolSpec:
        """Esquema que se pasa al modelo."""
        return ToolSpec(
            name=self.name,
            description=self.description,
            parameters=self.parameters,
        )
