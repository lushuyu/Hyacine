"""desktop/src-tauri/capabilities/default.json — the webview's opener scope.

The opener plugin only opens URLs matching one of the ``opener:allow-open-url``
globs, and it intercepts the provider page's ``target="_blank"`` Docs link
too. A preset whose ``docs_url`` is on a host the list doesn't cover gets a
link that silently does nothing, so every ``docs_url`` (the Python presets and
the desktop's offline fallback copy) must match a glob. The globs themselves
must stay ``https://`` with a literal host, so the scope can't widen to
arbitrary sites.

This mirrors desktop/src-tauri/tests/capabilities.rs in the suite CI runs.
"""
from __future__ import annotations

import json
import re
from fnmatch import fnmatchcase
from pathlib import Path

import pytest

from hyacine.llm.providers import as_dicts

_REPO = Path(__file__).resolve().parents[1]
_CAPABILITY = _REPO / "desktop" / "src-tauri" / "capabilities" / "default.json"
_TS_PRESETS = _REPO / "desktop" / "src" / "lib" / "provider-presets.ts"


def _opener_globs() -> list[str]:
    cap = json.loads(_CAPABILITY.read_text(encoding="utf-8"))
    opener = [
        p
        for p in cap["permissions"]
        if isinstance(p, dict) and p.get("identifier") == "opener:allow-open-url"
    ]
    assert len(opener) == 1, "expected one scoped opener:allow-open-url entry"
    globs = [entry["url"] for entry in opener[0]["allow"]]
    assert globs, "the opener allow list is empty"
    return globs


def _allowed(url: str) -> bool:
    # fnmatch's `*` also matches `/`, like glob::Pattern in the opener plugin.
    return any(fnmatchcase(url, glob) for glob in _opener_globs())


def _python_docs_urls() -> list[str]:
    return [str(p["docs_url"]) for p in as_dicts() if p["docs_url"]]


def _ts_docs_urls() -> list[str]:
    body = _TS_PRESETS.read_text(encoding="utf-8")
    return [u for u in re.findall(r"""docs_url:\s*['"]([^'"]*)['"]""", body) if u]


def test_opener_globs_pin_an_https_host() -> None:
    for glob in _opener_globs():
        # `?` and `[...]` mean different things to fnmatch and glob::Pattern.
        assert not set(glob) & set("?[]"), f"unsupported glob syntax in {glob}"
        assert glob.startswith("https://"), f"{glob}: https only"
        rest = glob.removeprefix("https://")
        host = rest.split("/", 1)[0]
        assert host and "*" not in host and "/" in rest, (
            f"{glob}: the host must be literal and followed by a path"
        )


@pytest.mark.parametrize(
    ("source", "urls"),
    [
        ("src/hyacine/llm/providers.py", _python_docs_urls()),
        ("desktop/src/lib/provider-presets.ts", _ts_docs_urls()),
    ],
)
def test_provider_docs_links_open(source: str, urls: list[str]) -> None:
    assert urls, f"no docs_url found in {source}"
    for url in urls:
        assert _allowed(url), (
            f"{url} (from {source}) needs an opener entry in "
            "desktop/src-tauri/capabilities/default.json"
        )


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example/",
        "https://docs.anthropic.com.evil.example/",
        "http://docs.anthropic.com/en/docs/claude-code",
        "file:///etc/passwd",
    ],
)
def test_other_urls_stay_blocked(url: str) -> None:
    assert not _allowed(url)
