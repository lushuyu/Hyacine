# Desktop architecture

This document describes how the Tauri desktop app in `desktop/` relates to the
existing Python package under `src/hyacine/`.

## Repository layout

```
Hyacine/
├── desktop/                    Tauri 2 + SvelteKit shell (this document)
│   ├── src/                      Svelte routes + lib (ipc, stores, i18n…)
│   ├── src-tauri/                Rust crate: keychain, sidecar host, commands
│   └── README.md
├── src/hyacine/                Python package (unchanged, plus `ipc/` module)
│   ├── ipc/                      JSON-RPC 2.0 sidecar — the NEW surface
│   │   ├── __main__.py             `python -m hyacine.ipc` entry point
│   │   ├── protocol.py             frame parse + error codes
│   │   ├── server.py               single-threaded dispatch loop
│   │   ├── router.py               method registry
│   │   └── handlers/               area-scoped handlers
│   │       ├── system_h.py         ping, version, paths
│   │       ├── config_h.py         read/write config, prompt, rules
│   │       ├── connectivity_h.py   DNS/Claude/Graph/SendMail probes
│   │       ├── graph_h.py          device-code OAuth + /me
│   │       └── pipeline_h.py       dry_run, run, history
│   ├── cli/ · graph/ · llm/ · …   existing pipeline (unchanged)
├── scripts/ · config/ · prompts/  existing per-user state
└── docs/
    └── desktop-architecture.md  (this file)
```

We deliberately **kept the Python package in `src/hyacine/`** rather than
relocating it under `apps/backend/`. `src/` is a Python-tooling convention
(`pyproject.toml`'s `tool.hatch.build.targets.wheel.packages` points there,
`pytest.ini_options.pythonpath` anchors to it) and moving it would break
`uv sync`, `pip install -e`, and existing CI. Instead, the Python package is
treated as the *backend library* and the desktop app is a new first-class
consumer of it via the `ipc/` module.

### New Python entry points

```toml
[project.scripts]
hyacine      = "hyacine.__main__:main"        # existing CLI
hyacine-ipc  = "hyacine.ipc.__main__:main"    # NEW: sidecar for the desktop app
```

The `hyacine-ipc` script is what Tauri spawns. In dev it falls back to
`python3 -m hyacine.ipc` if the bundled binary isn't present.

## Process model

Three processes cooperate:

| Process           | Written in | Responsibilities                                  |
| ----------------- | ---------- | ------------------------------------------------- |
| Tauri main        | Rust       | OS keychain, sidecar lifecycle, invoke handlers   |
| Webview           | TypeScript | SvelteKit UI: wizard, dashboard, settings         |
| Python sidecar    | Python     | All existing `hyacine` logic; connectivity probes |

The Rust main never blocks on the network for anything the Python sidecar
already knows how to do — it just owns secrets and routes. Everything
business-logic-shaped (Graph, Claude, pipeline) lives in Python.

## Request/response protocol

Newline-delimited JSON-RPC 2.0 over stdin/stdout:

```
→ {"jsonrpc":"2.0","id":1,"method":"config.read","params":{}}
← {"jsonrpc":"2.0","id":1,"result":{…}}
```

Notifications flow Python → Rust → webview as Tauri events named
`rpc:<method>`:

```
← {"jsonrpc":"2.0","method":"graph.device_flow","params":{"state":"awaiting_user",…}}
```

## Security properties

1. **Secrets never enter the webview.** API keys travel: paste → webview →
   `invoke('secrets_set')` → Rust → OS keychain, then *only* `has_key: bool`
   comes back out.
2. **CSP lock-down.** `connect-src` whitelists exactly
   `api.anthropic.com`, `graph.microsoft.com`, `login.microsoftonline.com`;
   nothing else.
3. **Preview iframe sandbox.** Dry-run HTML renders with `sandbox=""` — no
   same-origin, no scripts, no network.
4. **Log redaction.** `redactKeys` replaces `sk-ant-…` before any webview
   logger writes; Rust's tracing layer does the same on the backend.

## Testing

- Python: `uv run pytest tests/test_ipc_protocol.py`
- Rust/frontend: `cd desktop && npm run check` (type-check) and
  `cargo check --manifest-path src-tauri/Cargo.toml`
- End-to-end: `cd desktop && npm run tauri:dev` (requires Tauri system deps)
