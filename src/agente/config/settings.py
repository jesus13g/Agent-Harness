"""Configuración tipada del agente, cargada desde entorno / `.env`.

Todos los parámetros usan el prefijo `AGENTE_`. La API key se gestiona SOLO por
entorno; nunca debe aparecer en el código ni en el repositorio.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Parámetros de ejecución del agente."""

    model_config = SettingsConfigDict(
        env_prefix="AGENTE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- MiniMax ---
    minimax_api_key: str = Field(default="")
    minimax_base_url: str = Field(default="https://api.minimax.io/v1")
    model: str = Field(default="MiniMax-M2.5")

    # --- Parámetros del modelo ---
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=2048, gt=0)

    # --- Control del orquestador ---
    max_steps: int = Field(default=12, gt=0)
    request_timeout: float = Field(default=60.0, gt=0)
    max_retries: int = Field(default=3, ge=0)

    # --- Herramientas ---
    # Modo scoped: raíz del sandbox de ficheros (por defecto el directorio actual).
    fs_root: str = Field(default=".")
    # Nivel de acceso de la herramienta filesystem: "scoped" | "system".
    # "system" (acceso total salvo carpetas delicadas) se activa con -dap.
    fs_access_mode: str = Field(default="scoped")
    # Bloquear ficheros de secretos (.env, claves) en ambos modos.
    fs_block_secrets: bool = Field(default=True)
    enable_web_search: bool = Field(default=True)
    enable_scraper: bool = Field(default=True)
    # Scraper con navegador headless (Playwright).
    #   None (por defecto) -> AUTO: se habilita si Playwright está instalado.
    #   True  -> forzar habilitado (requiere 'pip install "agente[browser]"' +
    #            'playwright install chromium').
    #   False -> forzar deshabilitado.
    enable_browser: bool | None = Field(default=None)

    # --- Claude Code (delegación de tareas de programación) ---
    # Igual que enable_browser: None -> AUTO (se habilita si claude-agent-sdk
    # está instalado). Requiere además Node.js + el CLI de Claude Code
    # autenticado. La autenticación es independiente de MiniMax.
    enable_claude_code: bool | None = Field(default=None)
    claude_code_model: str = Field(default="claude-opus-4-8")
    claude_code_permission_mode: str = Field(default="acceptEdits")
    claude_code_max_turns: int = Field(default=40, gt=0)
    claude_code_max_budget_usd: float | None = Field(default=5.0)

    # --- Observabilidad ---
    log_level: str = Field(default="INFO")
    log_format: str = Field(default="console")  # "json" | "console"

    @property
    def has_api_key(self) -> bool:
        return bool(self.minimax_api_key.strip())
