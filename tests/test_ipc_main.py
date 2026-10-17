"""The sidecar entry point reads and writes UTF-8 whatever the OS locale is.

On Windows, Python decodes piped stdio with the ANSI code page (cp1252,
cp936/GBK, ...) unless UTF-8 mode is on, while the Rust parent always writes
raw UTF-8 JSON. These tests wrap the byte streams in legacy code pages the
way a Windows interpreter would and check that ``main()`` still sees the
right characters.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from hyacine.ipc import __main__ as ipc_main

# "要" is E8 A6 81 in UTF-8: 0x81 is undefined in cp1252, so the old loop
# died with UnicodeDecodeError; under GBK the bytes are an illegal sequence.
_PROMPT = "# 每日摘要\n优先处理老板的邮件，其余从简。\n"


def _frames(*frames: dict[str, Any]) -> bytes:
    return "".join(json.dumps(f, ensure_ascii=False) + "\n" for f in frames).encode("utf-8")


@pytest.mark.parametrize("codepage", ["cp1252", "gbk"])
def test_main_reads_utf8_requests_under_a_legacy_code_page(
    codepage: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prompt_path = tmp_path / "prompts" / "hyacine.md"
    monkeypatch.setenv("HYACINE_PROMPT_PATH", str(prompt_path))

    raw_in = _frames(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "config.write_prompt",
            "params": {"content": _PROMPT},
        },
        {"jsonrpc": "2.0", "id": 2, "method": "system.ping"},
    )
    raw_out = io.BytesIO()
    raw_err = io.BytesIO()
    stdout = io.TextIOWrapper(raw_out, encoding=codepage)
    stderr = io.TextIOWrapper(raw_err, encoding=codepage, errors="backslashreplace")
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(raw_in), encoding=codepage))
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", stderr)

    assert ipc_main.main() == 0
    stdout.flush()

    replies = {
        f["id"]: f
        for f in (json.loads(ln) for ln in raw_out.getvalue().decode("utf-8").splitlines())
        if "id" in f
    }
    assert replies[1]["result"]["ok"] is True
    # The loop survived the first request and answered the next one.
    assert replies[2]["result"] == {"pong": True}
    assert prompt_path.read_text(encoding="utf-8") == _PROMPT
    assert (stdout.encoding, stderr.encoding) == ("utf-8", "utf-8")
