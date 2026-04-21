"""JSON-RPC 2.0 sidecar used by the Tauri desktop shell.

The sidecar is launched by the Rust parent process and speaks newline-delimited
JSON-RPC over stdin/stdout. Every frontend → backend call flows through here,
so this module is the single authority for what the desktop app can do against
the existing `hyacine` package.
"""
