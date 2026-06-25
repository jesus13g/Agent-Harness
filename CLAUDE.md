# CLAUDE.md

Guía para agentes de Claude que trabajan en este repositorio. Resume la
arquitectura, las convenciones y los comandos clave para poder contribuir sin
romper el diseño.

## Qué es

`agente` es el núcleo de un **agente orquestador de IA** en Python. Planifica,
decide qué herramientas usar, las ejecuta en un bucle *razonar → actuar →
observar* y combina los resultados. El modelo por defecto es **MiniMax**
(`MiniMax-M2.5`) detrás de una abstracción intercambiable.

El idioma del proyecto (código, docstrings, commits) es **español**. Mantén ese
idioma al escribir o modificar código.

## Arquitectura (hexagonal — ports & adapters)

La dependencia apunta siempre hacia el centro:

```
interfaces → factory → agente   (y dentro del núcleo: service → core → ports)
```

```
src/
├── agente/            # LÓGICA (núcleo + fachada) — no conoce proveedor ni interfaz
│   ├── core/          #   orquestador (orchestrator.py), planner, session, types, prompts
│   ├── ports/         #   PUERTOS (interfaces abstractas): LLMClient, Tool, Memory
│   ├── infra/         #   ADAPTADORES: minimax_client.py, memory/, tools/
│   ├── service/       #   FACHADA: AgentService (API pública estable)
│   ├── config/        #   Settings (pydantic-settings, prefijo AGENTE_)
│   └── observability/ #   logging estructurado (structlog)
├── factory/           # CONSTRUCCIÓN: única raíz de composición (builder.py)
└── interfaces/        # INTERFACES: adaptadores delgados (cli.py, tui_app.py, commands.py)
```

### Reglas de dependencia (importantes)

- **Solo `factory/builder.py` importa adaptadores concretos.** Ni el núcleo ni la
  fachada construyen `MiniMaxClient`, herramientas, etc. — los reciben inyectados
  (DIP estricto). Los imports de adaptadores en `builder.py` son **locales** a la
  función para no arrastrarlos al import-time.
- El **núcleo (`core`) nunca importa de `interfaces` ni de `infra`**. Depende solo
  de `ports` y `config`.
- `AgentService` (la fachada) es el **único punto de entrada** para cualquier
  interfaz. Si añades una interfaz nueva, consúmela solo a través de ella.

## Conceptos clave

- **`Tool` (puerto, `ports/tool.py`)**: contrato de herramienta. Expone `name`,
  `description`, `parameters` (JSON Schema estilo OpenAI) y `run(**kwargs) ->
  ToolResult`. Una herramienta **no debe lanzar excepciones por errores
  esperables**: captúralas y devuelve `ToolResult.failure(...)` para que el
  modelo pueda recuperarse.
- **Añadir una herramienta** = implementar `Tool`, ponerla en
  `agente/infra/tools/`, y registrarla en `build_registry()` de
  `factory/builder.py`. El núcleo no cambia.
- **Habilitación AUTO**: herramientas con dependencias pesadas (navegador,
  Claude Code) se habilitan automáticamente si su paquete está instalado, salvo
  que un flag explícito en `Settings` mande lo contrario (ver `_browser_enabled`
  / `_claude_code_enabled`).
- **Orquestador (`core/orchestrator.py`)**: bucle stateless sobre la `Memory` de
  la sesión. Controla `AGENTE_MAX_STEPS` y detecta bucles (`_LOOP_THRESHOLD`)
  para acotar coste. Soporta `force_tool` (usado por el comando `/claude`).
- **Memoria**: en RAM (`infra/memory/in_memory.py`); el puerto `Memory` está
  listo para sustituir por persistencia.

## Herramientas incluidas

| Herramienta   | Notas |
|---------------|-------|
| `calculator`  | Evalúa expresiones con AST seguro (sin `eval`). |
| `filesystem`  | Dos niveles: `scoped` (CWD, por defecto) y `system` (`-dap`). |
| `web_search`  | DuckDuckGo Instant Answer (sin clave). |
| `scraper` / `browser` | Scraping HTTP y por navegador (Playwright, opcional). |
| `claude_code` | Delega tareas de programación a un agente Claude Code (SDK). |

## Modelo de seguridad de ficheros

- `scoped` (defecto): solo el directorio de trabajo y subcarpetas.
- `system`: se activa lanzando con `-dap`; acceso total salvo carpetas de sistema.
- En **ambos** modos se bloquean secretos (`.env`, claves SSH/PEM, `.aws`,
  `.gnupg`, …) si `AGENTE_FS_BLOCK_SECRETS=true`.
- Las rutas se resuelven con `Path.resolve()`: no se evaden bloqueos con `..` ni
  symlinks. Respeta este modelo al tocar `infra/tools/filesystem.py`.

## Comandos

```bash
pip install -e ".[dev]"          # entorno de desarrollo
pip install -e ".[ui]"           # TUI (Textual)
pip install -e ".[browser,code]" # extras opcionales (Playwright, Claude Code SDK)

pytest                           # toda la batería (no requiere red)
pytest tests/test_orchestrator.py

agente "¿Cuánto es 2**10?"      # CLI; sin argumentos → modo interactivo
agente-tui                       # TUI; añade -dap para acceso total a ficheros
```

## Configuración

`Settings` (pydantic-settings) lee de entorno / `.env` con prefijo `AGENTE_`.
Mínimo: `AGENTE_MINIMAX_API_KEY`. Otros: `AGENTE_MODEL`, `AGENTE_MAX_STEPS`,
`AGENTE_FS_*`, `AGENTE_ENABLE_*`, `AGENTE_CLAUDE_CODE_*`. Ver
`agente/config/settings.py` como fuente de verdad.

## Pruebas y convenciones

- Tests en `tests/`, sin red: el orquestador se prueba con un LLM programado y
  MiniMax con `httpx.MockTransport`. Si añades una herramienta o un adaptador,
  añade su test siguiendo ese patrón (mock, no llamadas reales).
- `from __future__ import annotations` en todos los módulos.
- Type hints completos; estilo Python 3.11+. `ruff`, `line-length = 100`.
- Docstrings en español explicando el **porqué** del diseño, no solo el qué.
- Commits en español con prefijo de tipo: `feat(...)`, `refactor(...)`, etc.

## Al contribuir, no hagas

- No importes adaptadores concretos fuera de `factory/builder.py`.
- No hagas que el núcleo dependa de una interfaz o de `infra`.
- No saltes la fachada `AgentService` desde una interfaz.
- No dejes que una `Tool` propague excepciones por errores esperables.
