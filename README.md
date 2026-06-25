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

Como librería (la vía prevista para cualquier interfaz). La fachada
`AgentService` no se autoconstruye: la raíz de composición `factory` la cablea:

```python
from factory import build_service, build_settings

service = build_service(build_settings())
session_id = service.create_session()
result = service.run_task(session_id, "¿Cuánto es (12**2 + 8) / 4 y guárdalo en r.txt?")
print(result.output)
```

CLI de ejemplo (adaptador delgado sobre la fachada, no es parte del núcleo):

```bash
agente "¿Cuánto es 2**10?"
agente                      # modo interactivo
# o sin instalar el script: python -m interfaces.cli "¿Cuánto es 2**10?"
```

Interfaz TUI en terminal con Textual (otra interfaz, también adaptador delgado):

```bash
pip install -e ".[ui]"
agente-tui
# o: python -m interfaces.tui_app
```

Pantalla completa en ASCII: panel de chat con scroll, panel lateral con modelo,
herramientas, tokens y la traza de cada respuesta (pasos y herramientas usadas).
Atajos: `Ctrl+N` nueva conversación, `Ctrl+Q` salir. Crece añadiendo widgets en
`src/interfaces/tui_app.py`, sin tocar el núcleo.

## Estructura

Un paquete por funcionalidad (lógica · construcción · interfaz):

```
src/
├── agente/            # LÓGICA DEL AGENTE (núcleo + fachada)
│   ├── core/          #   orquestador, planner, sesión, tipos de dominio
│   ├── ports/         #   PUERTOS: LLMClient, Tool, Memory (interfaces abstractas)
│   ├── infra/         #   ADAPTADORES: MiniMaxClient, memoria RAM, herramientas
│   ├── service/       #   FACHADA: AgentService (API pura, recibe sus colaboradores)
│   ├── config/        #   Settings (entorno / .env)
│   └── observability/ #   logging estructurado
├── factory/           # CONSTRUCCIÓN: raíz de composición (cablea LLM + tools + memoria)
└── interfaces/        # INTERFACES: adaptadores que consumen la fachada (CLI, TUI Textual, …)
```

La dependencia apunta hacia el centro: `interfaces → factory → agente`, y dentro
del núcleo `service → core → ports`, con los adaptadores de `infra` implementando
los puertos. Solo `factory` conoce adaptadores concretos (DIP estricto): ni el
núcleo ni la fachada los construyen.

## Herramientas incluidas

| Herramienta   | Qué hace                                                        |
|---------------|-----------------------------------------------------------------|
| `calculator`  | Evalúa expresiones matemáticas de forma segura (AST, sin `eval`).|
| `filesystem`  | Lee/escribe/lista ficheros (dos niveles de acceso, ver abajo).  |
| `web_search`  | Búsqueda web vía DuckDuckGo Instant Answer (sin clave).         |
| `claude_code` | Delega tareas de programación a un agente Claude Code (ver abajo).|

Añadir una herramienta = implementar `Tool` y registrarla; el núcleo no cambia.

### Delegación a Claude Code (`claude_code`)

Para tareas de programación complejas (implementar features, refactors, tests,
depurar), el agente puede **delegar en un agente Claude Code** vía el Claude
Agent SDK. Claude Code no sustituye al orquestador: entra como una herramienta
más; MiniMax decide cuándo invocarla, Claude Code ejecuta su propio bucle
(bash/read/write/edit) y devuelve un resumen que el orquestador reinyecta.

Requisitos (dependencia opcional y pesada, igual que el navegador):

```bash
pip install -e ".[code]"
npm install -g @anthropic-ai/claude-code   # CLI de Claude Code (necesita Node.js)
```

Autenticación **independiente de MiniMax**: el SDK usa el CLI de Claude Code, que
se autentica con `ANTHROPIC_API_KEY` o con tu suscripción Claude.ai
(`claude login`). Se habilita en AUTO si el SDK está instalado
(`AGENTE_ENABLE_CLAUDE_CODE` lo fuerza). Configurable: `AGENTE_CLAUDE_CODE_MODEL`
(por defecto `claude-opus-4-8`), `AGENTE_CLAUDE_CODE_PERMISSION_MODE`,
`AGENTE_CLAUDE_CODE_MAX_TURNS`, `AGENTE_CLAUDE_CODE_MAX_BUDGET_USD`.

> ⚠️ Cada llamada lanza un agente completo: es la herramienta más cara. Está
> acotada por `max_turns`/`max_budget_usd` y por la detección de bucles del
> orquestador. En modo `scoped` el agente trabaja dentro del directorio actual;
> con `-dap` (system) sin restricción de directorio.

El modelo puede usar `claude_code` cuando lo crea conveniente. Además, en la CLI
y la TUI puedes **forzar** una tarea a Claude Code con el prefijo `/claude`:

```bash
agente "/claude crea utils.py con una función slugify y su test"
agente            # en el REPL: › /claude refactoriza foo.py
```

El prefijo se procesa en la interfaz (`interfaces/commands.py`) y fuerza
`tool_choice=claude_code` en el primer paso del orquestador; MiniMax sigue
coordinando y resume el resultado (mantiene memoria y traza de la sesión). Si la
herramienta no está disponible, el forzado se ignora y la tarea sigue en modo
automático.

## Modelo de seguridad — niveles de acceso a ficheros

La herramienta `filesystem` tiene **dos niveles de acceso**:

| Nivel | Cómo se activa | Alcance |
|-------|----------------|---------|
| **scoped** (por defecto) | nada que hacer | Solo el **directorio de trabajo** (CWD) y sus subcarpetas. |
| **system** (total) | lanzar con **`-dap`** | **Todo el sistema** salvo carpetas delicadas. |

```bash
agente-tui            # scoped: solo el directorio actual
agente-tui -dap       # system: acceso total (menos lo bloqueado)
agente -dap "lista C:\Users\...\Documents"
```

**Bloqueado en modo `system`** (carpetas de sistema): en Windows `C:\Windows`
(incluye System32), `Program Files`, `Program Files (x86)`, `ProgramData`,
`$Recycle.Bin`, `System Volume Information`, `Recovery`, `Boot`; en Linux/mac
`/etc`, `/sys`, `/proc`, `/dev`, `/boot`, `/root`, `/bin`, `/sbin`, `/usr/bin`,
`/usr/sbin`, `/var`.

**Bloqueado en AMBOS modos** (secretos, `AGENTE_FS_BLOCK_SECRETS=true`):
ficheros `.env`/`*.env`, claves `id_rsa*`/`id_ed25519*`/…, `*.pem`, y todo lo que
esté bajo `.ssh`, `.aws`, `.gnupg`, `.azure`. Así el agente no puede leer su
propia API key ni tus credenciales.

> ⚠️ `-dap` da mucho poder al agente sobre tu disco (leer y **escribir** casi
> cualquier fichero). Úsalo solo si entiendes las implicaciones. Las rutas se
> resuelven con `Path.resolve()`, por lo que no se pueden evadir los bloqueos con
> `..` ni con enlaces simbólicos.

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
