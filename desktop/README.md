# Hyacine Desktop

Cross-platform Tauri desktop shell over the existing `hyacine` Python pipeline.

- **Frontend**: SvelteKit (static export) + Tailwind v3 + Motion One + Lucide
- **Shell**: Tauri 2, Rust commands, OS keychain via `keyring`, Python sidecar
  via `tauri-plugin-shell`
- **Backend**: the existing `hyacine` package — launched as a JSON-RPC sidecar
  by the entry point `hyacine-ipc` (see `src/hyacine/ipc/`)

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│ Tauri main (Rust)                                       │
│  ├─ keyring       (Claude key, etc.)                    │
│  ├─ sidecar state (spawns hyacine-ipc)                  │
│  └─ commands      (secrets_*, rust_probe_*, sidecar_rpc)│
│        ▲                      │                          │
│        │ invoke / emit        │ stdin/stdout JSON-RPC 2  │
│        ▼                      ▼                          │
│  ┌──────────────────┐  ┌──────────────────────────────┐ │
│  │ Webview (Svelte) │  │ Python sidecar (hyacine-ipc) │ │
│  │  - Wizard (0-9)  │  │  - config / rules / prompt   │ │
│  │  - Dashboard     │  │  - connectivity probes       │ │
│  │  - Prompt Lab    │  │  - graph device-code OAuth   │ │
│  │  - Rules         │  │  - pipeline dry/real run     │ │
│  │  - Settings      │  │                              │ │
│  └──────────────────┘  └──────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

## Prerequisites

- Rust 1.77+
- Node 20+ (npm / pnpm / bun — examples use `npm`)
- Python 3.11+ with `hyacine` installed (run `uv sync` from the repo root)
- OS development deps for Tauri ([see upstream](https://v2.tauri.app/start/prerequisites/))

## Development

```bash
cd desktop
npm install
npm run tauri:dev
```

The dev loop spawns `python3 -m hyacine.ipc` as a sidecar fallback so you can
iterate without rebuilding the Python binary. For release builds, a bundled
standalone Python binary is expected at `src-tauri/binaries/hyacine-ipc<EXT>`.

## Building a release

```bash
cd desktop
npm run tauri:build
```

Outputs `.dmg` (macOS), `.msi` + `.exe` (Windows), `.AppImage` + `.deb` (Linux).

### Downloading a pre-built installer

Every push that touches `desktop/**` or `src/hyacine/ipc/**` runs the
[Desktop workflow](../.github/workflows/desktop.yml), which uploads an
unsigned installer for each OS as a run artifact (retention: 14 days).
Grab it from the workflow's "Artifacts" section:

- macOS arm64 — `hyacine-aarch64-apple-darwin.zip` → `.dmg` inside
- Windows x64 — `hyacine-x86_64-pc-windows-msvc.zip` → `.msi` / `.exe`
- Linux x64  — `hyacine-x86_64-unknown-linux-gnu.zip` → `.AppImage` / `.deb`

These bundles are **unsigned**, so the first launch requires manual
approval:

- **macOS**: Right-click the `.app` → Open → *Open* (or run
  `xattr -dr com.apple.quarantine /Applications/Hyacine.app`)
- **Windows**: SmartScreen → More info → *Run anyway*
- **Linux**: `chmod +x` the `.AppImage` and run it

## LLM providers

v1.0 introduces a provider catalogue — Hyacine no longer assumes Claude.
Each provider is one row in
[`src/hyacine/llm/providers.py`](../src/hyacine/llm/providers.py) and
comes in one of three flavours:

| `api_format`     | Wire format                              | Typical providers                                                   |
| ---------------- | ---------------------------------------- | ------------------------------------------------------------------- |
| `anthropic_cli`  | `claude -p …` subprocess (OAuth)         | Claude Code OAuth (default)                                         |
| `anthropic_http` | `POST /v1/messages` with `x-api-key`     | Anthropic Console, DeepSeek, Kimi, Zhipu GLM, OpenRouter, AiHubMix  |
| `openai_chat`    | `POST /v1/chat/completions` with Bearer  | OpenAI, Azure, Groq, LM Studio, Ollama, any custom endpoint         |

Built-in presets ship for Claude Code, Anthropic Console, DeepSeek, Kimi,
Zhipu GLM, OpenAI, Groq, and local Ollama. Anything else goes through the
**Custom** picker entry — pick a format, paste a base URL and (if needed)
a key.

## Wizard flow

| Step | Path                      | Purpose                                              |
| ---: | ------------------------- | ---------------------------------------------------- |
|    0 | `/wizard/splash`          | brand splash + auto-advance                          |
|    1 | `/wizard/welcome`         | language + theme                                     |
|    2 | `/wizard/identity`        | name / role / identity blurb                         |
|    3 | `/wizard/priorities`      | tag chips that promote mail to the top               |
|    4 | `/wizard/delivery`        | recipient email, timezone, output language           |
|    5 | `/wizard/provider`        | provider picker + per-format form + live ping        |
|    6 | `/wizard/graph`           | Microsoft device-code OAuth with polling animation   |
|    7 | `/wizard/connectivity`    | DNS / Claude / Graph / SendMail probes in parallel   |
|    8 | `/wizard/preview`         | dry-run pipeline, render HTML in sandboxed iframe    |
|    9 | `/wizard/done`            | schedule + startup + tray + launch                   |

## Security

- API keys are stored in the OS keychain (`keyring` crate): macOS Keychain,
  Windows DPAPI, Linux Secret Service. One slot per provider (slug = preset
  id), so a user can keep multiple tokens side-by-side.
- Secrets never round-trip to the webview; only `has_key: bool` does.
- The Rust parent reads the active provider's slot on sidecar spawn and
  exports the value as `CLAUDE_CODE_OAUTH_TOKEN` (for `anthropic_cli`) or
  `HYACINE_LLM_API_KEY` (for the HTTP backends); `ANTHROPIC_API_KEY` and
  `ANTHROPIC_AUTH_TOKEN` are scrubbed before spawn.
- CSP restricts `connect-src` to `api.anthropic.com`, `graph.microsoft.com`,
  and `login.microsoftonline.com` for the webview itself; the Python sidecar
  makes the actual LLM requests and is allowed arbitrary hosts (so custom
  providers work).
- Preview iframe is `sandbox=""` so rendered HTML has no privileges.
- Tracing redacts `sk-ant-…` / `…-oat01-…` / `Bearer …` patterns via the
  shared `redact::scrub` helper, on both the Rust and webview sides.

## Directory layout

```
desktop/
├── src/                       SvelteKit routes + lib
│   ├── routes/
│   │   ├── wizard/            first-run flow
│   │   └── app/               dashboard / prompt / rules / settings
│   └── lib/                   ipc, stores, validators, i18n
├── src-tauri/
│   ├── src/
│   │   ├── main.rs · lib.rs   entry + builder
│   │   ├── sidecar.rs         Python RPC lifecycle
│   │   ├── secrets.rs         keychain
│   │   └── commands/          invoke handlers
│   ├── capabilities/          Tauri v2 permissions
│   └── tauri.conf.json
└── README.md
```
