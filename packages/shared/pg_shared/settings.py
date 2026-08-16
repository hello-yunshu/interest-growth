from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Settings:
    app_env: str
    app_data_root: str
    database_url: str
    deepseek_api_key: str
    deepseek_base_url: str
    deepseek_model: str
    deepseek_timeout_seconds: float
    source_storage_root: str
    artifact_storage_root: str
    desktop_token: str
    remote_auth_enabled: bool
    owner_bootstrap_token: str
    server_display_name: str
    access_token_ttl_seconds: int
    refresh_token_ttl_seconds: int
    auth_rate_limit_attempts: int
    auth_rate_limit_window_seconds: int


def _bool(name: str, default: str) -> bool:
    return os.getenv(name, default).lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        return default


def _data_path(root: str, child: str, fallback: str) -> str:
    return str(Path(root) / child) if root else fallback


class ConfigError(RuntimeError):
    """Raised when the resolved configuration violates a fail-closed invariant."""


def validate_settings(settings: Settings) -> None:
    """Enforce startup configuration invariants (Gate C/D §4.2).

    A `remote` environment MUST authenticate its remote API. Shipping a remote
    compose with `PG_REMOTE_AUTH_ENABLED=false` would expose every protected
    route unauthenticated; that is a fail-open configuration and is rejected at
    startup. `development` / `desktop` are not subject to this remote-only
    invariant.

    The owner bootstrap token is intentionally NOT a startup block: the
    bootstrap endpoint already fail-closes when it is empty (no owner can be
    created, therefore no device can authenticate, therefore protected routes
    stay closed). Blocking startup here would prevent the empty-default remote
    compose from even booting into its safe state.
    """
    if settings.app_env == "remote" and not settings.remote_auth_enabled:
        raise ConfigError(
            "APP_ENV=remote requires PG_REMOTE_AUTH_ENABLED=true; refusing to start "
            "an unauthenticated remote API"
        )


def get_settings() -> Settings:
    data_root = os.getenv("APP_DATA_ROOT", "").strip()
    database_default = (
        f"sqlite:///{(Path(data_root) / 'psychology_growth.db').as_posix()}"
        if data_root else "sqlite:///./data/psychology_growth.db"
    )
    return Settings(
        app_env=os.getenv("APP_ENV", "development"),
        app_data_root=data_root,
        database_url=os.getenv("APP_DATABASE_URL", database_default),
        deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", ""),
        deepseek_base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        deepseek_timeout_seconds=float(os.getenv("DEEPSEEK_TIMEOUT_SECONDS", "60")),
        source_storage_root=os.getenv(
            "SOURCE_STORAGE_ROOT", _data_path(data_root, "sources", "./data/source_files")
        ),
        artifact_storage_root=os.getenv(
            "ARTIFACT_STORAGE_ROOT", _data_path(data_root, "artifacts", "./data/artifacts")
        ),
        desktop_token=os.getenv("PG_DESKTOP_TOKEN", ""),
        remote_auth_enabled=_bool("PG_REMOTE_AUTH_ENABLED", "false"),
        owner_bootstrap_token=os.getenv("PG_OWNER_BOOTSTRAP_TOKEN", ""),
        server_display_name=os.getenv("PG_SERVER_DISPLAY_NAME", "Interest Growth Server").strip()
        or "Interest Growth Server",
        access_token_ttl_seconds=_int("PG_ACCESS_TOKEN_TTL_SECONDS", 15 * 60),
        refresh_token_ttl_seconds=_int("PG_REFRESH_TOKEN_TTL_SECONDS", 30 * 24 * 60 * 60),
        auth_rate_limit_attempts=_int("PG_AUTH_RATE_LIMIT_ATTEMPTS", 10),
        auth_rate_limit_window_seconds=_int("PG_AUTH_RATE_LIMIT_WINDOW_SECONDS", 15 * 60),
    )
