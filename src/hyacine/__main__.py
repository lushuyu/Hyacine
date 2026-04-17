"""python -m hyacine <subcommand>

Subcommands:
  init   — interactive setup wizard (writes XDG config files)
"""
from __future__ import annotations

import argparse
import sys


def _main() -> None:
    parser = argparse.ArgumentParser(
        prog="hyacine",
        description="briefing — daily email briefing powered by Microsoft Graph + Claude.",
    )
    subparsers = parser.add_subparsers(dest="subcommand")

    # Register known subcommands (args are parsed by the subcommand itself)
    subparsers.add_parser("init", help="Interactive setup wizard.")

    # Parse only the first positional to determine subcommand; pass the rest through
    args, remaining = parser.parse_known_args()

    if args.subcommand == "init":
        from hyacine.cli.init import run_init  # noqa: PLC0415
        sys.exit(run_init(remaining))
    else:
        parser.print_help()
        sys.exit(2)


if __name__ == "__main__":
    _main()
