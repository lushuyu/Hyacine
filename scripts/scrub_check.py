"""CI / pre-commit guard against personal-string regressions.

Usage:
    python scripts/scrub_check.py [--fix-allowlist]

Exit codes:
    0  — no violations found
    1  — one or more violations found (file:line printed to stdout)
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Regex pattern — case-insensitive alternation of personal strings
# ---------------------------------------------------------------------------

_PATTERN = re.compile(
    r"lushuyu"
    r"|e1376036"
    r"|shuyulu"
    r"|(?<!\w)NUS(?!\w)"
    r"|(?<!\w)Tung(?!\w)"
    r"|tungkh"
    r"|(?<!\w)H200(?!\w)"
    r"|u\.nus\.edu"
    r"|comp\.nus\.edu"
    r"|/home/lushuyu"
    r"|atung@nus\.edu\.sg"
    r"|5ba5ef5e-3109-4e77-85bd-cfeb0d347e82",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Allowlist — entries are either path prefixes or "path:keyword" pairs
# Path prefixes: the entire file is allowed
# "path::keyword": only lines containing *keyword* are allowed in that file
# ---------------------------------------------------------------------------

_ALLOWLIST_PATHS: list[str] = [
    # Historical generalization interview records — allowed to reference original author identity
    ".omc/specs/",
    # The scanner itself and its tests must name the patterns they detect.
    "scripts/scrub_check.py",
    "tests/test_scrub_check.py",
]

_ALLOWLIST_PATH_PATTERNS: list[re.Pattern[str]] = [
    # Kept example H200 deploy docs
    re.compile(r"^docs/examples/h200"),
]

# Per-file allowed keywords (the match is fine if the line contains ONLY these
# keywords from our pattern and the file is in this dict)
_ALLOWLIST_FILE_KEYWORDS: dict[str, list[str]] = {
    # The IANA→Windows tz map is allowed to keep Asia/Singapore; NUS/lushuyu are NOT allowed here
    "src/hyacine/graph/fetch.py": [],
}


def _is_allowlisted(rel_path: str, line: str, match: re.Match[str]) -> bool:
    """Return True if this match is covered by the allowlist."""
    # Full-path prefix allowlist
    for prefix in _ALLOWLIST_PATHS:
        if rel_path.startswith(prefix):
            return True

    # Pattern-based path allowlist
    for pat in _ALLOWLIST_PATH_PATTERNS:
        if pat.match(rel_path):
            return True

    # Per-file keyword allowlist
    if rel_path in _ALLOWLIST_FILE_KEYWORDS:
        allowed_kws = _ALLOWLIST_FILE_KEYWORDS[rel_path]
        # If the list is empty — the file is fully in scope, no exemptions
        if not allowed_kws:
            return False
        matched_text = match.group(0).lower()
        return any(kw.lower() in matched_text for kw in allowed_kws)

    return False


def _git_tracked_files() -> list[str]:
    """Return a list of tracked file paths (relative to repo root)."""
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        # Fall back to ls-files without extras
        result = subprocess.run(
            ["git", "ls-files"],
            capture_output=True,
            text=True,
            check=True,
        )
    return [line for line in result.stdout.splitlines() if line]


def _is_binary(path: Path) -> bool:
    """Heuristic: read first 8 KB and check for null bytes."""
    try:
        chunk = path.read_bytes()[:8192]
        return b"\x00" in chunk
    except OSError:
        return True


def scan() -> list[tuple[str, int, str]]:
    """Return list of (rel_path, line_number, line_text) for each violation."""
    violations: list[tuple[str, int, str]] = []
    tracked = _git_tracked_files()

    for rel in tracked:
        path = Path(rel)
        if not path.exists() or _is_binary(path):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        for lineno, line in enumerate(text.splitlines(), start=1):
            for match in _PATTERN.finditer(line):
                if not _is_allowlisted(rel, line, match):
                    violations.append((rel, lineno, line.rstrip()))

    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="scrub_check",
        description="Scan tracked files for personal-string regressions.",
    )
    parser.add_argument(
        "--fix-allowlist",
        action="store_true",
        help="(placeholder) Print suggested allowlist entries for found violations.",
    )
    _args = parser.parse_args(argv)

    violations = scan()

    if not violations:
        print("scrub_check: OK — no personal strings found in tracked files.")
        return 0

    print(f"scrub_check: FAILED — found {len(violations)} violation(s):\n")
    for rel, lineno, line in violations:
        print(f"  {rel}:{lineno}: {line}")

    print(
        "\nFix: remove personal strings or add an entry to _ALLOWLIST_PATHS / "
        "_ALLOWLIST_FILE_KEYWORDS in scripts/scrub_check.py"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
