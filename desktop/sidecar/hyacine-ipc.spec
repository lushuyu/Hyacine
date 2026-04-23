# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Hyacine IPC sidecar.

Produces a single-file executable that Tauri's `externalBin` picks up
during `tauri build`. The file is renamed to include the target triple
suffix (``hyacine-ipc-<target>[.exe]``) by the CI step right after
PyInstaller finishes.

We explicitly skip the FastAPI / Uvicorn stack here: the sidecar is a
stdin/stdout JSON-RPC server, it doesn't host the web UI. Dropping
those shaves ~15 MB off the bundle.

The hiddenimports list pins every handler module (router.py imports
them dynamically, which PyInstaller's static analysis can't see) plus
every platform keyring backend we might need at runtime — otherwise
``keyring.get_keyring()`` returns the fail backend on Windows/macOS
and the sidecar can't read the stored OAuth token.
"""

block_cipher = None

a = Analysis(
    ["entry.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        # IPC handlers — imported by name in router.build_handlers().
        "hyacine.ipc.handlers.config_h",
        "hyacine.ipc.handlers.connectivity_h",
        "hyacine.ipc.handlers.graph_h",
        "hyacine.ipc.handlers.pipeline_h",
        "hyacine.ipc.handlers.providers_h",
        "hyacine.ipc.handlers.system_h",
        # LLM dispatcher picks a backend at runtime.
        "hyacine.llm.anthropic_http",
        "hyacine.llm.claude_code",
        "hyacine.llm.openai_chat",
        "hyacine.llm.providers",
        # Keyring per-platform backends. Without these, keyring falls back to
        # its "fail" backend inside a PyInstaller bundle and secrets.get()
        # raises NoKeyringError at first token lookup.
        "keyring.backends.macOS",
        "keyring.backends.Windows",
        "keyring.backends.SecretService",
        "keyring.backends.kwallet",
        "keyring.backends.chainer",
        "keyring.backends.fail",
        "keyring.backends.null",
        # Pydantic v2 has JSON-schema plumbing that's also loaded dynamically.
        "pydantic.deprecated.decorator",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Web UI stack — unused by the sidecar, ~15 MB saving.
        "fastapi",
        "starlette",
        "uvicorn",
        "uvicorn.workers",
        "h11",
        "httptools",
        "websockets",
        "anyio._backends._trio",
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
