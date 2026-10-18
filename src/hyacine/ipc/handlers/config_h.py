"""Config read/write handlers for the wizard & settings panes.

Secrets never pass through these endpoints — they live in the OS keychain,
managed by the Rust side. These methods are only for non-secret YAML + prompt
files.
"""
from __future__ import annotations

import os
import shutil
import zoneinfo
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from hyacine.config import YamlConfig, get_settings, load_yaml_config
from hyacine.ipc.protocol import INVALID_PARAMS, RpcError

_SAFE_KEYS: set[str] = {
    "recipient_email",
    "timezone",
    "llm_model",
    "run_time",
    "llm_timeout_seconds",
    "fetch_max_emails",
    "initial_watermark_lookback_hours",
    "language",
    "identity",
    "priorities",
    # Provider selection — the wizard's /wizard/provider/ step writes these
    # three to persist preset vs. custom-endpoint choice. Leaving them off
    # the allowlist made every provider pick fail with the misleading
    # "unknown config key: llm_api_format" error.
    "llm_provider",
    "llm_base_url",
    "llm_api_format",
}


def read_config() -> dict[str, Any]:
    s = get_settings()
    cfg = load_yaml_config(s.config_path)
    raw: dict[str, Any] = {}
    if s.config_path.exists():
        raw = yaml.safe_load(s.config_path.read_text(encoding="utf-8")) or {}
    return {
        "exists": s.config_path.exists(),
        "recipient_email": cfg.recipient_email,
        "timezone": cfg.timezone,
        "llm_model": cfg.llm_model,
        "run_time": cfg.run_time,
        "language": cfg.language,
        "llm_provider": cfg.llm_provider,
        "llm_base_url": cfg.llm_base_url,
        "llm_api_format": cfg.llm_api_format,
        "identity": raw.get("identity", {"name": "", "role": "", "blurb": ""}),
        "priorities": raw.get("priorities", []),
    }


def write_config(**fields: Any) -> dict[str, Any]:
    s = get_settings()
    s.config_path.parent.mkdir(parents=True, exist_ok=True)

    existing: dict[str, Any] = {}
    if s.config_path.exists():
        existing = yaml.safe_load(s.config_path.read_text(encoding="utf-8")) or {}

    for k, v in fields.items():
        if k not in _SAFE_KEYS:
            raise RpcError(INVALID_PARAMS, f"unknown config key: {k}")
        existing[k] = v

    _validate_config(existing, check_timezone="timezone" in fields)
    _atomic_write_text(
        s.config_path, yaml.safe_dump(existing, sort_keys=True, allow_unicode=True)
    )
    return {"ok": True, "path": str(s.config_path)}


def _validate_config(merged: dict[str, Any], *, check_timezone: bool) -> None:
    """Reject a merged config that the pipeline couldn't use.

    Without this, a wrongly typed value (``llm_timeout_seconds: "10 min"``)
    made ``load_yaml_config`` raise, which broke ``config.read`` (so the
    settings page that could fix it wouldn't load) and every run. An
    unknown timezone (``shanghai``) loaded fine but made every run fail in
    ``ZoneInfo`` before it recorded anything. The timezone is only checked
    when this write sets it, so other saves still work if it is already bad.
    """
    try:
        cfg = YamlConfig(**merged)
    except ValidationError as e:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in err['loc']) or 'config'}: {err['msg']}"
            for err in e.errors()
        )
        raise RpcError(INVALID_PARAMS, f"invalid config value: {problems}") from e
    if check_timezone:
        try:
            zoneinfo.ZoneInfo(cfg.timezone)
        except (zoneinfo.ZoneInfoNotFoundError, ValueError) as e:
            raise RpcError(
                INVALID_PARAMS,
                f"unknown timezone: {cfg.timezone!r} (use an IANA name like 'Asia/Singapore')",
            ) from e


def _atomic_write_text(path: Path, content: str) -> None:
    """Replace *path* with *content* through a sibling temp file.

    ``os.replace`` swaps the file in one step, so a crash or a full disk
    mid-write leaves the old file intact instead of a truncated one. The
    temp file takes the original's permission bits first, so a ``chmod
    600`` the user applied survives the save; a new file gets the usual
    umask-based mode, as ``write_text`` would give it. A symlinked file is
    written through the link, so the link itself stays in place.
    """
    if path.is_symlink():
        path = path.resolve()
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with tmp.open("w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        if path.exists():
            shutil.copymode(path, tmp)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def read_prompt() -> dict[str, Any]:
    s = get_settings()
    if not s.prompt_path.exists():
        return {"exists": False, "content": ""}
    return {"exists": True, "content": s.prompt_path.read_text(encoding="utf-8")}


def write_prompt(content: str) -> dict[str, Any]:
    s = get_settings()
    s.prompt_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(s.prompt_path, content)
    return {"ok": True, "bytes": len(content.encode("utf-8"))}


def read_rules() -> dict[str, Any]:
    s = get_settings()
    if not s.rules_path.exists():
        return {"exists": False, "content": ""}
    return {"exists": True, "content": s.rules_path.read_text(encoding="utf-8")}


def write_rules(content: str) -> dict[str, Any]:
    s = get_settings()
    # Validate YAML before overwriting so we never leave a broken config.
    try:
        yaml.safe_load(content)
    except yaml.YAMLError as e:
        raise RpcError(INVALID_PARAMS, f"invalid YAML: {e}") from e
    s.rules_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(s.rules_path, content)
    return {"ok": True}


def bootstrap() -> dict[str, Any]:
    """Create the minimum set of files & dirs required before first run."""
    s = get_settings()
    for d in (s.config_path.parent, s.prompt_path.parent, s.db_path.parent, s.auth_dir, s.log_dir):
        d.mkdir(parents=True, exist_ok=True)

    if not s.prompt_path.exists():
        s.prompt_path.write_text(_DEFAULT_PROMPT, encoding="utf-8")
    if not s.rules_path.exists():
        s.rules_path.write_text(_DEFAULT_RULES, encoding="utf-8")
    return {"ok": True, "paths": {
        "config": str(s.config_path),
        "prompt": str(s.prompt_path),
        "rules": str(s.rules_path),
    }}


def _read_if_exists(p: Path) -> str:
    return p.read_text(encoding="utf-8") if p.exists() else ""


_DEFAULT_PROMPT = """# Hyacine identity

You are an executive assistant drafting a prioritised daily briefing. Keep it
short, factual, action-oriented. Never invent facts.
"""

_DEFAULT_RULES = """# rules.yaml — lightweight promotion/demotion rules.
promote: []
demote: []
"""
