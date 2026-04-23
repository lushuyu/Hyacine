# Bundled sidecar

PyInstaller spec for packaging `hyacine.ipc` as a standalone binary that
ships inside the Tauri installer. `tauri build` picks the binary up via
the `externalBin` entry in `src-tauri/tauri.conf.json`, so every
installer carries its own Python runtime and end users don't need to
install Python 3.11+ or `pip install hyacine`.

## Layout

```
sidecar/
├── entry.py             # PyInstaller entry — imports hyacine.ipc.__main__.main
├── hyacine-ipc.spec     # PyInstaller build spec
└── README.md            # this file
```

## Build locally

From the repo root (needs Python 3.11+ and the project synced via `uv`):

```bash
uv sync --all-extras
uv run pip install pyinstaller
cd desktop/sidecar
uv run pyinstaller hyacine-ipc.spec --distpath ../src-tauri/binaries --clean -y
```

PyInstaller picks a platform-appropriate scratch dir when `--workpath`
is omitted (CI pins it to `--workpath ../../.pyi-work` so the cache is
repo-local and easy to prune; locally, the default is fine).

Then rename the output to match your host triple — Tauri looks for
`binaries/hyacine-ipc-<target>[.exe]`:

```bash
# Example: Apple Silicon macOS
mv ../src-tauri/binaries/hyacine-ipc ../src-tauri/binaries/hyacine-ipc-aarch64-apple-darwin
```

Now `cd .. && npm run tauri:dev` or `tauri:build` will bundle it.

## Supported target triples

CI matrix covers:

| Runner             | Target triple                  |
| ------------------ | ------------------------------ |
| `macos-latest`     | `aarch64-apple-darwin`         |
| `macos-13`         | `x86_64-apple-darwin`          |
| `windows-latest`   | `x86_64-pc-windows-msvc`       |
| `windows-11-arm`   | `aarch64-pc-windows-msvc`      |
| `ubuntu-22.04`     | `x86_64-unknown-linux-gnu`     |
| `ubuntu-24.04-arm` | `aarch64-unknown-linux-gnu`    |

Cross-arch PyInstaller builds aren't supported — each runner produces
the binary for its own host.

## Why no UPX

The spec sets `upx=False`. UPX trips Windows Defender and breaks macOS
codesigning; the ~10 MB saving isn't worth the support load.

## What's excluded

The spec explicitly drops `fastapi`, `starlette`, `uvicorn` and friends.
The sidecar is a stdin/stdout JSON-RPC server — it doesn't host the web
UI at `web.py`. Dropping the ASGI stack trims ~15 MB.
