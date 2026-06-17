"""Interfaces del agente (adaptadores de presentación).

Paquete hermano del núcleo: consume la fachada `AgentService` y la raíz de
composición `factory`. Nunca construye el agente por su cuenta ni importa
adaptadores concretos. Añadir una interfaz (REST, WebSocket, chat) = un módulo
nuevo aquí, sin tocar el núcleo.
"""
