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
| `windows-latest`   | `x86_64-pc-windows-msvc`       |
| `windows-11-arm`   | `aarch64-pc-windows-msvc`      |
| `ubuntu-22.04`     | `x86_64-unknown-linux-gnu`     |
| `ubuntu-24.04-arm` | `aarch64-unknown-linux-gnu`    |

Intel Mac (`x86_64-apple-darwin`) isn't in the matrix — the macos-13
runner pool is too saturated for reliable CI. Intel users can run the
Apple Silicon bundle via Rosetta.

Cross-arch PyInstaller builds aren't supported — each runner produces
the binary for its own host.

## Data directory

A one-file build extracts itself to a temp dir, so `hyacine.config`'s
repo-root fallback would put `config/config.yaml`, `data/hyacine.db` and
the Graph auth record in the OS temp dir. The Tauri parent passes
`HYACINE_REPO_ROOT` pointing at the per-user app data dir
(`app_local_data_dir()`: `~/.local/share/com.hyacine.desktop`,
`~/Library/Application Support/com.hyacine.desktop`,
`%LOCALAPPDATA%\com.hyacine.desktop`), and `entry.py` pins the same
directory when the binary runs on its own. Export `HYACINE_REPO_ROOT`
before `npm run tauri:dev` to point the app at a repo checkout instead.

## UTF-8 stdio

The spec passes the `X utf8` bootloader option. The Rust parent writes raw
UTF-8 JSON, Windows Python decodes piped stdin with the ANSI code page by
default, and a frozen interpreter ignores `PYTHONUTF8`.

## Why no UPX

The spec sets `upx=False`. UPX trips Windows Defender and breaks macOS
codesigning; the ~10 MB saving isn't worth the support load.

## What's excluded

The spec explicitly drops `fastapi`, `starlette`, `uvicorn` and friends.
The sidecar is a stdin/stdout JSON-RPC server — it doesn't host the web
UI at `web.py`. Dropping the ASGI stack trims ~15 MB.
