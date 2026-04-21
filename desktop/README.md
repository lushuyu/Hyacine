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

## Wizard flow

| Step | Path                      | Purpose                                              |
| ---: | ------------------------- | ---------------------------------------------------- |
|    0 | `/wizard/splash`          | brand splash + auto-advance                          |
|    1 | `/wizard/welcome`         | language + theme                                     |
|    2 | `/wizard/identity`        | name / role / identity blurb                         |
|    3 | `/wizard/priorities`      | tag chips that promote mail to the top               |
|    4 | `/wizard/delivery`        | recipient email, timezone, output language           |
|    5 | `/wizard/claude`          | API key (masked, keychain-stored, tested live)       |
|    6 | `/wizard/graph`           | Microsoft device-code OAuth with polling animation   |
|    7 | `/wizard/connectivity`    | DNS / Claude / Graph / SendMail probes in parallel   |
|    8 | `/wizard/preview`         | dry-run pipeline, render HTML in sandboxed iframe    |
|    9 | `/wizard/done`            | schedule + startup + tray + launch                   |

## Security

- API keys are stored in the OS keychain (`keyring` crate): macOS Keychain,
  Windows DPAPI, Linux Secret Service.
- Secrets never round-trip to the webview; only `has_key: bool` does.
- CSP restricts `connect-src` to `api.anthropic.com`, `graph.microsoft.com`
  and `login.microsoftonline.com`.
- Preview iframe is `sandbox=""` so rendered HTML has no privileges.
- Tracing redacts `sk-ant-…` patterns via the shared `redactKeys` helper.

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
