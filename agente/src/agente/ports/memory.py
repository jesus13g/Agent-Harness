"""Puerto de memoria de sesión.

Abstrae cómo se almacena y recupera el historial de una conversación. La
implementación inicial vive en RAM; en el futuro puede sustituirse por fichero,
base de datos o memoria vectorial sin cambiar el núcleo.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from agente.core.types import Message


class Memory(ABC):
    """Contrato de la memoria de una sesión."""

    @abstractmethod
    def add(self, message: Message) -> None:
        """Añade un mensaje al historial."""
        raise NotImplementedError

    @abstractmethod
    def messages(self) -> list[Message]:
        """Devuelve el historial listo para enviar al modelo.

        La implementación es responsable de respetar el límite de contexto
        (truncado / resumen de mensajes antiguos).
        """
        raise NotImplementedError

    @abstractmethod
    def clear(self) -> None:
        """Vacía el historial."""
        raise NotImplementedError
