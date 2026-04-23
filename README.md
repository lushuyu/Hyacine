# HyacineAI

> **Your personal Outlook daily report — powered by the LLM of your choice.**
>
> Microsoft Outlook mail + calendar → your LLM → summary email delivered to your own inbox.

[![CI](https://github.com/lushuyu/Hyacine/actions/workflows/ci.yml/badge.svg)](https://github.com/lushuyu/Hyacine/actions/workflows/ci.yml)
[![license](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![python](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue)](pyproject.toml)
[![release](https://img.shields.io/github/v/release/lushuyu/Hyacine?include_prereleases&sort=semver)](https://github.com/lushuyu/Hyacine/releases)

## What it does

`hyacine` fetches your Outlook inbox and today's calendar via Microsoft Graph,
classifies each message against a set of lightweight YAML rules, and hands the
structured data to the LLM you've picked. The model produces a prioritised
summary email that's sent back to your own inbox via `/me/sendMail`. A small
FastAPI web UI lets you inspect past runs and tweak the prompt or classification
rules without restarting anything.

**Supported providers out of the box**: Claude (Claude Code OAuth and the
Anthropic Console API), DeepSeek, Kimi, Zhipu GLM, OpenAI, Groq, and local
Ollama. "Custom" lets you point at any endpoint that speaks the Claude or
OpenAI chat protocol. See [`src/hyacine/llm/providers.py`](src/hyacine/llm/providers.py)
for the full registry.

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
- **Credentials** — API key / OAuth token for the selected provider, Microsoft tenant id (defaults to `common`)
- **Monitoring** — optional ntfy topic and healthchecks.io UUID

After first run you can edit the config at any time via the Web UI or by hand
in `./config/` and `./prompts/hyacine.md`.

## Architecture

The pipeline runs as `hyacine.pipeline.run`. It reads a watermark from
`./data/hyacine.db` to bound the fetch window, pulls mail and calendar events
from `graph.microsoft.com`, classifies each message with the rules in
`./config/rules.yaml`, and hands the JSON to whichever provider the config
points at — via a CLI subprocess (`claude -p …`) or an HTTP round-trip
against `/v1/messages` or `/v1/chat/completions`, depending on the provider's
`api_format`.

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
  LLM — Claude / DeepSeek / OpenAI / Groq / Ollama / …
        │ hyacine.md system prompt
        ▼
  /me/sendMail → your inbox
```

## Desktop app

A cross-platform desktop GUI (Tauri + SvelteKit) lives under `desktop/`. It
wraps the Python pipeline via a JSON-RPC sidecar (`hyacine-ipc`), adds an
animated first-run wizard, OS-keychain-backed secret storage, live
connectivity checks, and a dashboard for past runs. See
[`desktop/README.md`](desktop/README.md) and
[`docs/desktop-architecture.md`](docs/desktop-architecture.md).

## Links

- [First-run guide](docs/ONBOARDING.md)
- [Server deploy](docs/server-deploy.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Desktop architecture](docs/desktop-architecture.md)
- [Example: Alice the PM](examples/alice/)
- [Changelog](CHANGELOG.md)
- [Contributing](CONTRIBUTING.md)

## License

MIT — see [LICENSE](LICENSE).
