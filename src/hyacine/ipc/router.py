"""Method registry — maps JSON-RPC method names to callables.

Methods are namespaced `area.verb` (e.g. `wizard.save_identity`). Keep this
file thin: each handler defers to a module under `hyacine.ipc.handlers` so
real logic stays testable without spinning the full RPC loop.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from hyacine.ipc.handlers import (
    config_h,
    connectivity_h,
    graph_h,
    pipeline_h,
    providers_h,
    system_h,
)


def build_handlers(
    *,
    emit: Callable[[str, Any], None],
    log: Callable[..., None],
) -> dict[str, Callable[..., Any]]:
    return {
        # system
        "system.ping": system_h.ping,
        "system.version": system_h.version,
        "system.paths": system_h.paths,
        # wizard / config
        "config.read": config_h.read_config,
        "config.write": config_h.write_config,
        "config.read_prompt": config_h.read_prompt,
        "config.write_prompt": config_h.write_prompt,
        "config.read_rules": config_h.read_rules,
        "config.write_rules": config_h.write_rules,
        "config.bootstrap": config_h.bootstrap,
        # connectivity
        "connectivity.probe": lambda kind, **kw: connectivity_h.probe(kind, emit=emit, **kw),
        "connectivity.probe_all": lambda **kw: connectivity_h.probe_all(emit=emit, **kw),
        # graph / oauth
        "graph.start_device_flow": lambda **kw: graph_h.start_device_flow(emit=emit, **kw),
        "graph.cancel_device_flow": graph_h.cancel_device_flow,
        "graph.me": graph_h.me,
        # pipeline
        "pipeline.dry_run": lambda **kw: pipeline_h.dry_run(emit=emit, log=log, **kw),
        "pipeline.run": lambda **kw: pipeline_h.run(emit=emit, log=log, **kw),
        "pipeline.history": pipeline_h.history,
        # providers (multi-LLM catalogue)
        "providers.list": providers_h.list_providers,
        "providers.current": providers_h.current_provider,
        "providers.test": lambda **kw: providers_h.test(emit=emit, **kw),
    }
