# HyacineAI

> **Your personal Outlook daily report — powered by Claude.**
>
> Microsoft Outlook mail + calendar → Claude Code LLM → summary email delivered to your own inbox.

[![CI](https://github.com/lushuyu/Hyacine/actions/workflows/ci.yml/badge.svg)](https://github.com/lushuyu/Hyacine/actions/workflows/ci.yml)
[![license](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![python](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue)](pyproject.toml)

## What it does

`hyacine` fetches your Outlook inbox and today's calendar via Microsoft Graph,
classifies each message against a set of lightweight YAML rules, and passes the
structured data to Claude Code (`claude -p`). The LLM produces a prioritised
summary email that is sent back to your own inbox via `/me/sendMail`. A small
FastAPI web UI lets you inspect past runs and tweak the prompt or classification
rules without restarting anything.

All per-user state — secrets, config, identity prompt, database, auth tokens —
lives inside the repo checkout under `.env`, `config/`, `prompts/`, and
`data/`. The user-specific files are gitignored, so `git pull` never conflicts
with your customisations.

## Quickstart

```bash
git clone https://github.com/lushuyu/Hyacine ~/hyacine
cd ~/hyacine
uv sync
python -m hyacine init           # interactive wizard — writes .env, config/, prompts/hyacine.md
python scripts/bootstrap_auth.py # one-time Microsoft Graph OAuth (device-code flow)
python scripts/doctor.py         # sanity check — paths, perms, credentials
python -m hyacine run            # first manual run
```

The wizard prompts for your name, role, priorities, delivery address, timezone,
language, and credentials. Everything it writes lives inside the repo tree.

## What you configure via the wizard

- **Identity** — name, role description, free-form identity blurb
- **Priorities** — signals that promote mail to the "must do today" section
- **Delivery** — recipient email address, timezone (IANA), output language (`en` / `zh-CN`)
- **Credentials** — Claude Code OAuth token, Microsoft tenant id (defaults to `common`)
- **Monitoring** — optional ntfy topic and healthchecks.io UUID

After first run you can edit the config at any time via the Web UI or by hand
in `./config/` and `./prompts/hyacine.md`.

## Architecture

The pipeline runs as `hyacine.pipeline.run`. It reads a watermark from
`./data/hyacine.db` to bound the fetch window, pulls mail and calendar events
from `graph.microsoft.com`, classifies each message with the rules in
`./config/rules.yaml`, then invokes:

```
claude -p --model sonnet --output-format json --tools "" --permission-mode default \
       --append-system-prompt-file ./prompts/hyacine.md
```

The response is converted to HTML and sent via Graph `/me/sendMail`. On success
the watermark advances. A FastAPI web UI (default `127.0.0.1:8765`) exposes the
run history, snapshot viewer, and editors for the prompt and rules.

```
Outlook inbox + calendar
        │ Microsoft Graph
        ▼
  rules classifier (rules.yaml)
        │
        ▼
  Claude Code (claude -p)
        │ hyacine.md system prompt
        ▼
  /me/sendMail → your inbox
```

## Links

- [First-run guide](docs/ONBOARDING.md)
- [Server deploy](docs/server-deploy.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Example: Alice the PM](examples/alice/)
- [Contributing](CONTRIBUTING.md)

## License

MIT — see [LICENSE](LICENSE).
