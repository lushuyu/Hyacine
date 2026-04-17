"""Settings loader — env-first, all paths anchored to the repo root.

Env variables carry secrets and optional path overrides. YAML carries the
non-secret operational config (recipient, timezone, run_time, etc) so it can
be edited via the Web UI and snapshotted.

Repo root resolution (in order):
    1. HYACINE_REPO_ROOT env var, if set (absolute path).
    2. Module location: ``Path(__file__).parents[2]`` — works for editable
       installs where the repo is cloned and ``uv sync`` was run.

All derived paths default to locations under the repo root:
    config_path = <repo_root>/config/config.yaml
    rules_path  = <repo_root>/config/rules.yaml
    prompt_path = <repo_root>/prompts/hyacine.md
    db_path     = <repo_root>/data/hyacine.db
    auth_dir    = <repo_root>/data/auth
    log_dir     = <repo_root>/data/logs

Any individual path can still be overridden by setting ``HYACINE_<NAME>_PATH``.
"""
from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Sentinel: a Path value that is never a real user path; used as the default
# so the model_validator can detect "this field was not set by the caller or
# an env var" and fill in the in-repo default.
_UNSET = Path("/.__hyacine_path_unset__")


def _default_repo_root() -> Path:
    """Resolve the default repo root at Settings-instantiation time.

    Runs on every ``Settings()`` call so tests (and unusual deploys) can
    flip ``HYACINE_REPO_ROOT`` between instantiations.
    """
    env_override = os.environ.get("HYACINE_REPO_ROOT", "").strip()
    if env_override:
        return Path(env_override).expanduser().resolve()
    # src/hyacine/config.py → parents[2] = repo root (editable install).
    return Path(__file__).resolve().parents[2]


# Evaluated once at import time to anchor the .env path, which pydantic
# reads before the model validator runs. A different .env can still be
# selected per-instantiation via ``Settings(_env_file=...)``.
_STATIC_REPO_ROOT = _default_repo_root()


class Settings(BaseSettings):
    """Environment-driven settings — prefix HYACINE_ unless noted."""

    model_config = SettingsConfigDict(
        env_prefix="HYACINE_",
        env_file=str(_STATIC_REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Graph / auth
    graph_client_id: str = "14d82eec-204b-4c2f-b7e8-296a70dab67e"
    graph_tenant_id: str = "common"
    graph_scopes: str = "User.Read Mail.Read Mail.Send Calendars.Read"

    # Monitoring
    ntfy_topic: str = ""
    healthchecks_uuid: str = ""

    # Derived paths — _UNSET means "use in-repo default"
    config_path: Path = _UNSET
    rules_path: Path = _UNSET
    prompt_path: Path = _UNSET
    db_path: Path = _UNSET
    auth_dir: Path = _UNSET
    log_dir: Path = _UNSET
    auth_record_path: Path = _UNSET

    @model_validator(mode="after")
    def _resolve_paths(self) -> Settings:
        repo_root = _default_repo_root()
        if self.config_path == _UNSET:
            self.config_path = repo_root / "config" / "config.yaml"
        if self.rules_path == _UNSET:
            self.rules_path = repo_root / "config" / "rules.yaml"
        if self.prompt_path == _UNSET:
            self.prompt_path = repo_root / "prompts" / "hyacine.md"
        if self.db_path == _UNSET:
            self.db_path = repo_root / "data" / "hyacine.db"
        if self.auth_dir == _UNSET:
            self.auth_dir = repo_root / "data" / "auth"
        if self.log_dir == _UNSET:
            self.log_dir = repo_root / "data" / "logs"
        if self.auth_record_path == _UNSET:
            self.auth_record_path = self.auth_dir / "auth_record.json"
        return self

    @property
    def scope_list(self) -> list[str]:
        return [s for s in self.graph_scopes.split() if s]


class YamlConfig(BaseSettings):
    """Non-secret operational config, loaded from config.yaml."""

    recipient_email: str = ""               # must be set by wizard
    timezone: str = "UTC"                   # IANA tz, e.g. "America/New_York"
    llm_model: str = "sonnet"
    run_time: str = "07:30"
    llm_timeout_seconds: int = 300
    fetch_max_emails: int = 500
    initial_watermark_lookback_hours: int = 24
    language: str = "en"                    # "en" or "zh-CN"


def load_yaml_config(path: Path) -> YamlConfig:
    if not path.exists():
        return YamlConfig()
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return YamlConfig(**data)


def get_settings(env_file: Path | None = None) -> Settings:
    if env_file is not None:
        return Settings(_env_file=str(env_file))  # type: ignore[call-arg]
    return Settings()
