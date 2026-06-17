# Agente — núcleo orquestador de IA (MiniMax)

Núcleo de un agente de IA **orquestador** en Python: planifica, decide qué
herramientas usar, las ejecuta y combina los resultados para resolver tareas
generales, usando un modelo MiniMax detrás de una abstracción.

Arquitectura **hexagonal (ports & adapters)**: el núcleo no conoce ni al
proveedor del modelo ni a ninguna interfaz. Todo el acceso externo pasa por la
fachada estable `AgentService`, de modo que se pueden añadir interfaces (CLI,
REST, WebSocket, chat) sin tocar el núcleo.

## Instalación

```bash
cd agente
python -m venv .venv
.venv\Scripts\activate        # PowerShell: .venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

## Configuración

Copia `.env.example` a `.env` y rellena al menos la API key:

```
AGENTE_MINIMAX_API_KEY=tu_clave
AGENTE_MODEL=MiniMax-M2.5
```

> El modelo por defecto es `MiniMax-M2.5` (lineup actual: M2 / M2.5 / M2.7).
> El plan original mencionaba "MiniMax-M3", que no existe. Cambiar de modelo o
> proveedor es solo editar la config o sustituir el adaptador.

## Uso

Como librería (la vía prevista para cualquier interfaz):

```python
from agente import AgentService

service = AgentService()
session_id = service.create_session()
result = service.run_task(session_id, "¿Cuánto es (12**2 + 8) / 4 y guárdalo en r.txt?")
print(result.output)
```

CLI de ejemplo (adaptador delgado sobre la fachada, no es parte del núcleo):

```bash
python -m agente "¿Cuánto es 2**10?"
python -m agente            # modo interactivo
```

Chat web con Streamlit (otra interfaz, también adaptador delgado):

```bash
pip install -e ".[ui]"
streamlit run src/agente/interfaces/streamlit_app.py
```

Incluye un panel de "Traza" por respuesta (pasos, herramientas usadas y tokens)
y un botón para reiniciar la conversación. Crece añadiendo widgets en
`src/agente/interfaces/streamlit_app.py`, sin tocar el núcleo.

## Estructura

```
src/agente/
├── core/          # NÚCLEO: orquestador, planner, sesión, tipos de dominio
├── ports/         # PUERTOS: LLMClient, Tool, Memory (interfaces abstractas)
├── infra/         # ADAPTADORES: MiniMaxClient, memoria RAM, herramientas
├── service/       # FACHADA: AgentService (punto de entrada estable)
├── interfaces/    # INTERFACES: adaptadores que consumen la fachada (Streamlit, …)
├── config/        # Settings (entorno / .env)
└── observability/ # logging estructurado
```

La dependencia siempre apunta al centro: `interfaces → service → core → ports`,
y los adaptadores de `infra` implementan los puertos.

## Herramientas incluidas

| Herramienta   | Qué hace                                                        |
|---------------|-----------------------------------------------------------------|
| `calculator`  | Evalúa expresiones matemáticas de forma segura (AST, sin `eval`).|
| `filesystem`  | Lee/escribe/lista ficheros dentro de un sandbox (`AGENTE_FS_ROOT`).|
| `web_search`  | Búsqueda web vía DuckDuckGo Instant Answer (sin clave).         |

Añadir una herramienta = implementar `Tool` y registrarla; el núcleo no cambia.

## Pruebas

```bash
pytest
```

Las pruebas no requieren red: el orquestador se prueba con un LLM programado y
el adaptador MiniMax con un transporte HTTP simulado (`httpx.MockTransport`).

## Estado y límites

- Memoria de sesión **en RAM**; sin persistencia entre procesos (puerto listo
  para sustituir).
- `web_search` base usa DuckDuckGo Instant Answer (resultados limitados); para
  producción, sustituir por un proveedor completo escribiendo otra `Tool`.
- Verifica en tu cuenta MiniMax el formato exacto de la API, *streaming* y
  límites antes de cerrar la integración (`run_task_stream` queda como extensión).

## Coste

Un agente reenvía contexto y reintenta: el coste por tarea es muy superior al de
un chat de un solo turno. `AGENTE_MAX_STEPS` limita las iteraciones y cada
`AgentResult` reporta `usage` (tokens) para poder medirlo.
