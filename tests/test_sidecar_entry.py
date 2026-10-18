"""desktop/sidecar/entry.py — the frozen sidecar's data root.

A one-file PyInstaller build would otherwise anchor config.yaml, the DB and
the Graph auth record next to its extraction dir in the OS temp dir.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from types import ModuleType

import pytest

_REPO = Path(__file__).resolve().parents[1]
_ENTRY = _REPO / "desktop" / "sidecar" / "entry.py"
_TAURI_CONF = _REPO / "desktop" / "src-tauri" / "tauri.conf.json"


@pytest.fixture
def entry(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    # setenv (not delenv) so monkeypatch removes whatever pin_data_root
    # writes; blank counts as unset, as in config.py.
    monkeypatch.setenv("HYACINE_REPO_ROOT", "")
    spec = importlib.util.spec_from_file_location("hyacine_sidecar_entry", _ENTRY)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_identifier_matches_tauri_conf(entry: ModuleType) -> None:
    # Rust resolves app_local_data_dir() from this identifier; both sides
    # must land in the same directory.
    conf = json.loads(_TAURI_CONF.read_text(encoding="utf-8"))
    assert entry.APP_IDENTIFIER == conf["identifier"]


def test_default_data_root_per_platform(entry: ModuleType, tmp_path: Path) -> None:
    home = tmp_path / "home"
    ident = entry.APP_IDENTIFIER

    win = entry.default_data_root("win32", {"LOCALAPPDATA": str(tmp_path / "Local")}, home)
    assert win == tmp_path / "Local" / ident
    assert entry.default_data_root("win32", {}, home) == home / "AppData" / "Local" / ident

    mac = entry.default_data_root("darwin", {}, home)
    assert mac == home / "Library" / "Application Support" / ident

    xdg = entry.default_data_root("linux", {"XDG_DATA_HOME": str(tmp_path / "xdg")}, home)
    assert xdg == tmp_path / "xdg" / ident
    assert entry.default_data_root("linux", {}, home) == home / ".local" / "share" / ident
    # A relative XDG_DATA_HOME is ignored, per the XDG spec (and dirs-sys).
    relative = entry.default_data_root("linux", {"XDG_DATA_HOME": "rel"}, home)
    assert relative == home / ".local" / "share" / ident


def test_pin_data_root_when_frozen(
    entry: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "data" / entry.APP_IDENTIFIER
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(entry, "default_data_root", lambda: root)

    entry.pin_data_root()

    assert root.is_dir()
    assert os.environ["HYACINE_REPO_ROOT"] == str(root)


def test_pin_data_root_keeps_explicit_root(
    entry: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("HYACINE_REPO_ROOT", str(tmp_path / "explicit"))
    monkeypatch.setattr(entry, "default_data_root", lambda: pytest.fail("not consulted"))

    entry.pin_data_root()

    assert os.environ["HYACINE_REPO_ROOT"] == str(tmp_path / "explicit")


def test_pin_data_root_is_a_no_op_when_not_frozen(
    entry: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(entry, "default_data_root", lambda: pytest.fail("not consulted"))

    entry.pin_data_root()

    assert os.environ["HYACINE_REPO_ROOT"] == ""


def test_run_pins_the_root_then_calls_main(
    entry: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hyacine.ipc.__main__ as ipc_main

    root = tmp_path / "pinned"
    seen: dict[str, str | None] = {}

    def fake_main() -> int:
        seen["root"] = os.environ.get("HYACINE_REPO_ROOT")
        return 7

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(entry, "default_data_root", lambda: root)
    monkeypatch.setattr(ipc_main, "main", fake_main)

    assert entry.run() == 7
    assert seen["root"] == str(root)
