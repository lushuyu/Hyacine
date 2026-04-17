"""python -m hyacine <subcommand>

Subcommands:
  init   — interactive setup wizard (writes ./config/ and ./prompts/ in the repo)
  run    — execute one pipeline iteration (fetch → LLM → sendMail)
"""
from __future__ import annotations

import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="hyacine",
        description="Hyacine — daily Outlook + Claude report delivered to your inbox.",
    )
    subparsers = parser.add_subparsers(dest="subcommand")

    subparsers.add_parser("init", help="Interactive setup wizard.")
    subparsers.add_parser("run", help="Run one pipeline iteration.")

    args, remaining = parser.parse_known_args()

    if args.subcommand == "init":
        from hyacine.cli.init import run_init  # noqa: PLC0415
        sys.exit(run_init(remaining))
    if args.subcommand == "run":
        from hyacine.pipeline.run import main as run_main  # noqa: PLC0415
        sys.exit(run_main())
    parser.print_help()
    sys.exit(2)


if __name__ == "__main__":
    main()
