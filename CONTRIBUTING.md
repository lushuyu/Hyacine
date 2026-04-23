# Contributing to Hyacine

Thank you for taking the time to contribute.

## Development environment

Requires Python 3.11 or 3.12 and [`uv`](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/<user>/hyacine ~/hyacine
cd ~/hyacine
uv sync          # installs all dependencies including dev extras
```

## Running tests

```bash
uv run pytest            # full suite
uv run pytest -q -x      # stop on first failure
```

## Linting and type checking

```bash
uv run ruff check .      # linter
uv run mypy src/         # type checker
```

CI enforces both with zero warnings allowed. Fix all issues before opening a PR.

## Personal-string scrub check

Before committing, verify that no personal strings leaked into tracked files:

```bash
uv run python scripts/scrub_check.py
```

The check greps tracked files for a regex covering known personal identifiers
and fails with a non-zero exit code on any match. CI runs the same check.

## Commit style

- Imperative mood, present tense: `Add wizard idempotency check`, not `Added …`
- No trailing period on the summary line
- Wrap body at 72 characters
- If AI-assisted, add a `Co-Authored-By:` trailer:
  ```
  Co-Authored-By: Claude Sonnet <noreply@anthropic.com>
  ```

## Pull request flow

1. Branch from `main`: `git checkout -b feat/my-feature`
2. Make changes, ensure `ruff`, `mypy`, `pytest`, and `scrub_check` all pass locally
3. Open a PR against `main`
4. CI must be green before review is requested
5. At least one review approval required
6. Merge via **squash-merge** — keep the history linear

## What belongs in a PR

Keep PRs focused. One logical change per PR. If you find an unrelated issue,
open a separate PR or issue rather than bundling it.

## Reporting bugs

Use the issue tracker. Include:
- OS and Python version (`python3 --version`)
- Output of `python scripts/doctor.py`
- Sanitised log excerpt (remove personal email addresses and tokens)

## Feature requests

Open a discussion issue first. The mail side is intentionally Microsoft
Graph only — alternative mail providers (Gmail, IMAP, etc.) aren't on the
roadmap. The LLM side is multi-provider: new presets slot into
[`src/hyacine/llm/providers.py`](src/hyacine/llm/providers.py), and three
wire formats are supported (`anthropic_cli`, `anthropic_http`,
`openai_chat`). Feature ideas that expand the provider registry or the
wizard UX are welcome; additions that fork the mail backend are not.
