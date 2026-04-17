"""Settings loader — env-first, XDG paths, then legacy in-repo fallback.

Env variables are authoritative for secrets and paths. YAML carries the
non-secret operational config (recipient, timezone, run_time, etc) so it can
be edited via the Web UI and snapshotted.

Path resolution algorithm for each derived path:
1. If env var ``HYACINE_<NAME>_PATH`` is set → use that (pydantic-settings handles this).
2. Else check XDG path; if it exists → use it.
3. Else check legacy in-repo path; if it exists → use it (back-compat).
4. Else return XDG path (new install; wizard will create it).

XDG directories:
- config_dir = $XDG_CONFIG_HOME/hyacine/  (default ~/.config/hyacine/)
- state_dir  = $XDG_STATE_HOME/hyacine/   (default ~/.local/state/hyacine/)
- cache_dir  = $XDG_CACHE_HOME/hyacine/   (reserved; not yet used)
"""
from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Sentinel: a Path value that is never a real user path; used as the default
# so the model_validator can detect "this field was not set by the caller or
# an env var" and apply the XDG/legacy resolution algorithm.
_UNSET = Path("/.__hyacine_path_unset__")


def _xdg_config_home() -> Path:
    raw = os.environ.get("XDG_CONFIG_HOME", "")
    return Path(raw) if raw else Path.home() / ".config"


def _xdg_state_home() -> Path:
    raw = os.environ.get("XDG_STATE_HOME", "")
    return Path(raw) if raw else Path.home() / ".local" / "state"


def _resolve_path(xdg_path: Path, legacy_path: Path) -> Path:
    """Return xdg_path or legacy_path — whichever exists — else xdg_path."""
    if xdg_path.exists():
        return xdg_path
    if legacy_path.exists():
        return legacy_path
    return xdg_path


class Settings(BaseSettings):
    """Environment-driven settings — prefix HYACINE_ unless noted."""

    model_config = SettingsConfigDict(
        env_prefix="HYACINE_",
        env_file=(
            str(Path.home() / ".config" / "hyacine" / "hyacine.env"),
            ".env",
        ),
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

    # XDG base directories — _UNSET means "let the validator fill it in"
    config_dir: Path = _UNSET
    state_dir: Path = _UNSET

    # Derived paths — _UNSET means "resolve via XDG/legacy heuristic"
    config_path: Path = _UNSET
    rules_path: Path = _UNSET
    prompt_path: Path = _UNSET
    db_path: Path = _UNSET
    auth_dir: Path = _UNSET
    log_dir: Path = _UNSET
    auth_record_path: Path = _UNSET

    @model_validator(mode="after")
    def _resolve_paths(self) -> Settings:
        xdg_cfg = _xdg_config_home() / "hyacine"
        xdg_state = _xdg_state_home() / "hyacine"

        if self.config_dir == _UNSET:
            self.config_dir = xdg_cfg
        if self.state_dir == _UNSET:
            self.state_dir = xdg_state

        if self.config_path == _UNSET:
            self.config_path = _resolve_path(
                xdg_cfg / "config.yaml",
                Path("./config/config.yaml"),
            )

        if self.rules_path == _UNSET:
            self.rules_path = _resolve_path(
                xdg_cfg / "rules.yaml",
                Path("./config/rules.yaml"),
            )

        # Rendered briefing prompt filename stays `briefing.md` — the word
        # describes what the file is (a briefing prompt) independent of the
        # project name. Operators reading ~/.config/hyacine/prompts/ see a
        # self-documenting filename.
        if self.prompt_path == _UNSET:
            self.prompt_path = _resolve_path(
                xdg_cfg / "prompts" / "briefing.md",
                Path("./prompts/briefing.md"),
            )

        if self.db_path == _UNSET:
            self.db_path = _resolve_path(
                xdg_state / "hyacine.db",
                Path("./data/briefing.db"),
            )

        if self.auth_dir == _UNSET:
            self.auth_dir = _resolve_path(
                xdg_state / "auth",
                Path.home() / ".local" / "share" / "hyacine",
            )

        if self.log_dir == _UNSET:
            self.log_dir = _resolve_path(
                xdg_state / "logs",
                Path("./data/logs"),
            )

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
