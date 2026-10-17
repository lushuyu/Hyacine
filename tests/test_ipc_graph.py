"""Device-code sign-in from the desktop wizard: cancel, remount, restart.

``DeviceCodeCredential.authenticate`` can't be interrupted, so a cancelled
worker keeps polling until its code expires. The wizard cancels whenever the
user leaves the Graph step, so coming back must start a fresh flow rather
than report ``already_running`` with no code to show, and the abandoned
worker must not later flip the new flow's UI or save its record.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from hyacine.ipc.handlers import graph_h


@dataclass
class _FakeRecord:
    username: str


@dataclass
class _FakeCredential:
    """Shows its code through the prompt callback, then blocks in
    ``authenticate`` until the test approves it, like a user would."""

    code: str
    prompt_callback: Callable[[str, str, object], None]
    approve: threading.Event = field(default_factory=threading.Event)
    authenticate_kwargs: dict[str, Any] = field(default_factory=dict)

    def authenticate(self, **kwargs: Any) -> _FakeRecord:
        self.authenticate_kwargs = kwargs
        self.prompt_callback("https://microsoft.com/devicelogin", self.code, "later")
        if not self.approve.wait(5):
            raise TimeoutError("test never approved the code")
        return _FakeRecord(username=f"user-{self.code}")


@dataclass
class _Harness:
    creds: list[_FakeCredential] = field(default_factory=list)
    saved: list[str] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)

    def emit(self, method: str, params: Any) -> None:
        assert method == "graph.device_flow"
        self.events.append(params)

    def wait_for(self, payload: dict[str, Any]) -> None:
        deadline = time.monotonic() + 5
        while payload not in self.events:
            assert time.monotonic() < deadline, f"never saw {payload}; got {self.events}"
            time.sleep(0.01)


def _awaiting(code: str) -> dict[str, Any]:
    return {
        "state": "awaiting_user",
        "user_code": code,
        "verification_uri": "https://microsoft.com/devicelogin",
        "expires_on": "later",
    }


@pytest.fixture
def harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[_Harness]:
    monkeypatch.setenv("HYACINE_REPO_ROOT", str(tmp_path))
    for var in ("HYACINE_AUTH_DIR", "HYACINE_AUTH_RECORD_PATH"):
        monkeypatch.delenv(var, raising=False)
    h = _Harness()

    def _build(*_a: Any, prompt_callback: Any = None, **_kw: Any) -> _FakeCredential:
        cred = _FakeCredential(code=f"CODE{len(h.creds) + 1}", prompt_callback=prompt_callback)
        h.creds.append(cred)
        return cred

    monkeypatch.setattr(graph_h, "build_credential", _build)
    monkeypatch.setattr(
        graph_h, "save_authentication_record", lambda rec, _path: h.saved.append(rec.username)
    )
    monkeypatch.setattr(graph_h, "_state", {"thread": None, "cancel": None, "prompt": None})
    yield h
    for cred in h.creds:
        cred.approve.set()


def _thread() -> threading.Thread:
    t = graph_h._state["thread"]
    assert isinstance(t, threading.Thread)
    return t


def test_start_after_cancel_begins_a_fresh_flow(harness: _Harness) -> None:
    assert graph_h.start_device_flow(emit=harness.emit) == {"started": True}
    harness.wait_for(_awaiting("CODE1"))
    old = _thread()

    graph_h.cancel_device_flow()
    # The old worker is still blocked in authenticate(); this used to
    # return {"already_running": True} for up to 15 minutes.
    assert graph_h.start_device_flow(emit=harness.emit) == {"started": True}
    harness.wait_for(_awaiting("CODE2"))
    new = _thread()
    assert new is not old

    # The user approves the stale code anyway: nothing saved, nothing said.
    harness.creds[0].approve.set()
    old.join(5)
    assert not old.is_alive()
    assert harness.saved == []
    assert harness.events == [_awaiting("CODE1"), _awaiting("CODE2")]

    harness.creds[1].approve.set()
    new.join(5)
    assert harness.events[-1] == {"state": "approved", "username": "user-CODE2"}
    assert harness.saved == ["user-CODE2"]


def test_authenticate_gets_no_ignored_timeout(harness: _Harness) -> None:
    graph_h.start_device_flow(emit=harness.emit)
    harness.wait_for(_awaiting("CODE1"))
    assert harness.creds[0].authenticate_kwargs == {
        "scopes": graph_h.get_settings().scope_list
    }


def test_remounted_page_is_shown_the_live_code_again(harness: _Harness) -> None:
    graph_h.start_device_flow(emit=harness.emit)
    harness.wait_for(_awaiting("CODE1"))
    harness.events.clear()

    assert graph_h.start_device_flow(emit=harness.emit) == {"already_running": True}

    assert harness.events == [_awaiting("CODE1")]
    assert len(harness.creds) == 1


def test_cancelled_flow_without_a_successor_reports_cancelled(harness: _Harness) -> None:
    graph_h.start_device_flow(emit=harness.emit)
    harness.wait_for(_awaiting("CODE1"))

    graph_h.cancel_device_flow()
    harness.creds[0].approve.set()
    _thread().join(5)

    assert harness.events[-1] == {"state": "cancelled"}
    assert harness.saved == []
