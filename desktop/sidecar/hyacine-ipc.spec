# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Hyacine IPC sidecar.

Produces a single-file executable that Tauri's `externalBin` picks up
during `tauri build`. The file is renamed to include the target triple
suffix (``hyacine-ipc-<target>[.exe]``) by the CI step right after
PyInstaller finishes.

We explicitly skip the FastAPI / Uvicorn stack here: the sidecar is a
stdin/stdout JSON-RPC server, it doesn't host the web UI. Dropping
those shaves ~15 MB off the bundle.

No ``hiddenimports`` needed: every module the sidecar touches
(``hyacine.ipc.*``, ``hyacine.llm.*``, each handler) is reached through
a static ``from ... import ...`` chain starting at ``entry.py``, so
PyInstaller's graph analysis picks them up automatically. Secret
storage is owned by the Rust parent (``src-tauri/src/secrets.rs`` via
the ``keyring`` crate); the Python side never calls Python's keyring
package, and we don't depend on it.
"""

block_cipher = None

a = Analysis(
    ["entry.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Web UI stack — unused by the sidecar, ~15 MB saving.
        "fastapi",
        "starlette",
        "uvicorn",
        "uvicorn.workers",
        "httptools",
        "websockets",
        # NOTE: `h11` is *kept* on purpose. It's an HTTP/1.1 parser used by
        # uvicorn (which we drop) AND by httpcore / httpx (which we keep for
        # every non-CLI provider call). Excluding it broke the
        # anthropic_http and openai_chat probes with
        # `No module named 'h11'` at first request. See issue #16.
        # Test / dev tooling that pyproject pulls transitively.
        "pytest",
        "mypy",
        "ruff",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="hyacine-ipc",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX compression trips Defender / Gatekeeper heuristics and breaks the
    # macOS code-sign workflow. Leaving the binary uncompressed is a ~10 MB
    # hit we prefer over false positives.
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
