import os
from functools import lru_cache
from pathlib import Path

from dynaconf import Dynaconf
from pydantic import BaseModel, ConfigDict, Field, field_validator


class DatabaseConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    url: str = "postgresql+asyncpg://localhost/orchestrator"
    pool_size: int = 5
    max_overflow: int = 10
    pool_timeout: int = 30
    pool_recycle: int = 1800
    echo: bool = False


class CorsConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    allow_origins: list[str] = Field(default_factory=lambda: ["http://localhost", "http://localhost:3000"])
    allow_methods: list[str] = Field(default_factory=lambda: ["*"])
    allow_headers: list[str] = Field(default_factory=lambda: ["*"])
    allow_credentials: bool = True
    max_age: int = 600


class PublicRouteRule(BaseModel):
    """Exact path + methods that skip API-key checks (e.g. health, tenant signup)."""

    model_config = ConfigDict(extra="ignore")

    methods: list[str]
    path: str

    @field_validator("methods", mode="before")
    @classmethod
    def _upper_methods(cls, v: list[str]) -> list[str]:
        return [m.upper() for m in v]


class QuotaRouteRule(BaseModel):
    """Maps HTTP requests to a plan_quotas.operation value for quota enforcement.

    First matching rule wins (list order matters). ``path_pattern`` is a regex
    matched against the normalized URL path (no trailing slash except ``/``).
    """

    model_config = ConfigDict(extra="ignore")

    path_pattern: str
    methods: list[str] = Field(default_factory=lambda: ["POST"])
    operation: str
    tenant_in_body: bool = False
    body_slug_field: str = "slug"
    max_body_bytes: int = 1_048_576

    @field_validator("methods", mode="before")
    @classmethod
    def _upper_methods(cls, v: list[str]) -> list[str]:
        return [m.upper() for m in v]


class AuthConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    disabled: bool = True
    quota_disabled: bool = True
    api_key_pepper: str = "change-me"
    # Defaults live in repo ``config.yaml`` (public_routes / quota_routes).
    public_routes: list[PublicRouteRule] = Field(default_factory=list)
    quota_routes: list[QuotaRouteRule] = Field(default_factory=list)


class OrchestratorConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    app_name: str = "orchestrator"
    debug: bool = False
    log_level: str = "INFO"
    config_file: str = "config.yaml"
    openai_api_key: str | None = None
    cors: CorsConfig = Field(default_factory=CorsConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _load_config_source(path: str | Path | None = None) -> Dynaconf:
    """Private Dynaconf source for orchestrator config."""
    root = _project_root()
    settings_file = str(path) if path is not None else str(root / "config.yaml")
    return Dynaconf(
        envvar_prefix="ORCHESTRATOR",
        settings_files=[settings_file],
        environments=False,
        load_dotenv=True,
        dotenv_path=str(root / ".env"),
        merge_enabled=True,
    )


def _apply_runtime_env(config: OrchestratorConfig) -> None:
    """Hydrate runtime env from config where downstream SDKs expect env vars."""
    if config.openai_api_key and not os.getenv("OPENAI_API_KEY"):
        os.environ["OPENAI_API_KEY"] = config.openai_api_key


def load_config(path: str | Path | None = None) -> OrchestratorConfig:
    dynasettings = _load_config_source(path)
    payload = {
        "app_name": dynasettings.get("app_name", "orchestrator"),
        "debug": dynasettings.get("debug", False),
        "log_level": dynasettings.get("log_level", "INFO"),
        "config_file": dynasettings.get("config_file", "config.yaml"),
        "openai_api_key": dynasettings.get(
            "openai_api_key", dynasettings.get("OPENAI_API_KEY", os.getenv("OPENAI_API_KEY"))
        ),
        "cors": dynasettings.get("cors", {}),
        "database": dynasettings.get("database", {}),
        "auth": dynasettings.get("auth", {}),
    }
    config = OrchestratorConfig.model_validate(payload)
    _apply_runtime_env(config)
    return config


@lru_cache
def get_config() -> OrchestratorConfig:
    return load_config()
