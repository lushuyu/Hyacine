"""Tests for scripts/scrub_check.py."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_scrub(repo_dir: Path) -> subprocess.CompletedProcess[str]:
    """Run scrub_check.py in *repo_dir* and return the CompletedProcess."""
    scrub_script = Path(__file__).parent.parent / "scripts" / "scrub_check.py"
    return subprocess.run(
        [sys.executable, str(scrub_script)],
        capture_output=True,
        text=True,
        cwd=str(repo_dir),
    )


def _git_init(repo_dir: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=str(repo_dir), check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=str(repo_dir),
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=str(repo_dir),
        check=True,
    )


def _git_add_commit(repo_dir: Path, files: dict[str, str]) -> None:
    """Write files and commit them."""
    for name, content in files.items():
        path = repo_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        subprocess.run(["git", "add", name], cwd=str(repo_dir), check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "test"],
        cwd=str(repo_dir),
        check=True,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_clean_tree_exits_0(tmp_path: Path) -> None:
    """A repo with no personal strings should exit 0."""
    _git_init(tmp_path)
    _git_add_commit(tmp_path, {
        "README.md": "# Generic briefing template\n\nNo personal info here.\n",
        "src/example.py": 'print("hello world")\n',
    })
    result = _run_scrub(tmp_path)
    assert result.returncode == 0, f"Expected 0, got {result.returncode}.\nstdout: {result.stdout}"


def test_personal_string_detected(tmp_path: Path) -> None:
    """A file containing a personal string should cause exit 1."""
    _git_init(tmp_path)
    _git_add_commit(tmp_path, {
        "README.md": "Created by lushuyu for personal use.\n",
    })
    result = _run_scrub(tmp_path)
    assert result.returncode == 1, f"Expected 1, got {result.returncode}.\nstdout: {result.stdout}"
    assert "README.md" in result.stdout
    assert "lushuyu" in result.stdout.lower() or "violation" in result.stdout.lower()


def test_nus_detected(tmp_path: Path) -> None:
    """NUS references should be flagged."""
    _git_init(tmp_path)
    _git_add_commit(tmp_path, {
        "config/config.yaml": "recipient_email: user@u.nus.edu\n",
    })
    result = _run_scrub(tmp_path)
    assert result.returncode == 1
    assert "config/config.yaml" in result.stdout


def test_home_path_detected(tmp_path: Path) -> None:
    """/home/lushuyu hardcodes should be flagged."""
    _git_init(tmp_path)
    _git_add_commit(tmp_path, {
        "scripts/setup.sh": "export PATH=/home/lushuyu/.local/bin:$PATH\n",
    })
    result = _run_scrub(tmp_path)
    assert result.returncode == 1
    assert "scripts/setup.sh" in result.stdout


def test_allowlisted_omc_specs_ignored(tmp_path: Path) -> None:
    """Files under .omc/specs/ are allowlisted and should not trigger violations."""
    _git_init(tmp_path)
    _git_add_commit(tmp_path, {
        ".omc/specs/deep-interview-briefing-generalize.md": (
            "Original author: lushuyu. NUS grad student.\n"
        ),
        "README.md": "# Generic template\n",
    })
    result = _run_scrub(tmp_path)
    assert result.returncode == 0, (
        f"Expected 0 (allowlisted), got {result.returncode}.\nstdout: {result.stdout}"
    )


def test_multiple_violations_reported(tmp_path: Path) -> None:
    """Multiple personal strings across multiple files should all be reported."""
    _git_init(tmp_path)
    _git_add_commit(tmp_path, {
        "file_a.py": "# author: lushuyu\n",
        "file_b.py": "# university: NUS\n",
    })
    result = _run_scrub(tmp_path)
    assert result.returncode == 1
    assert "file_a.py" in result.stdout
    assert "file_b.py" in result.stdout


def test_violation_count_shown(tmp_path: Path) -> None:
    """The output should include a violation count."""
    _git_init(tmp_path)
    _git_add_commit(tmp_path, {
        "bad.py": "# lushuyu wrote this\n",
    })
    result = _run_scrub(tmp_path)
    assert result.returncode == 1
    # Should say "found N violation(s)"
    assert "violation" in result.stdout.lower()


def test_binary_file_skipped(tmp_path: Path) -> None:
    """Binary files should not cause errors."""
    _git_init(tmp_path)
    # Write a file with null bytes (binary heuristic)
    binary_file = tmp_path / "data.bin"
    binary_file.write_bytes(b"\x00\x01\x02lushuyu\x00")
    subprocess.run(["git", "add", "data.bin"], cwd=str(tmp_path), check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "add binary"],
        cwd=str(tmp_path),
        check=True,
    )
    # Should not crash; binary file is skipped
    result = _run_scrub(tmp_path)
    # Binary file shouldn't be scanned → exit 0
    assert result.returncode == 0


def test_email_domain_detected(tmp_path: Path) -> None:
    """comp.nus.edu.sg domain references should be flagged."""
    _git_init(tmp_path)
    _git_add_commit(tmp_path, {
        "config/rules.yaml": "sender_email: advisor@comp.nus.edu.sg\n",
    })
    result = _run_scrub(tmp_path)
    assert result.returncode == 1
    assert "config/rules.yaml" in result.stdout


def test_public_project_url_line_allowlisted(tmp_path: Path) -> None:
    """Lines containing the canonical public project URL are exempt."""
    _git_init(tmp_path)
    _git_add_commit(tmp_path, {
        "README.md": (
            "[![CI](https://github.com/lushuyu/Hyacine/actions/workflows/"
            "ci.yml/badge.svg)](https://github.com/lushuyu/Hyacine/actions)\n"
            "git clone https://github.com/lushuyu/Hyacine ~/hyacine\n"
        ),
    })
    result = _run_scrub(tmp_path)
    assert result.returncode == 0, (
        f"Expected 0 (project URL allowlisted), got {result.returncode}.\n"
        f"stdout: {result.stdout}"
    )


def test_bare_lushuyu_still_flagged_in_readme(tmp_path: Path) -> None:
    """The URL allowlist must not leak into unrelated lines in the same file."""
    _git_init(tmp_path)
    _git_add_commit(tmp_path, {
        "README.md": (
            "Link: https://github.com/lushuyu/Hyacine\n"
            "Authored by lushuyu for personal stuff.\n"
        ),
    })
    result = _run_scrub(tmp_path)
    assert result.returncode == 1
    assert "Authored by lushuyu" in result.stdout
