"""Terminal front end and entry point: investment-tools <command>.

`check` runs one check and prints the report. `bot` serves the same check as
/check in Telegram. Both do exactly the same work; only the audience differs.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from .bot import run
from .checker import CheckInProgress, DepotChecker
from .comdirect import ComdirectError
from .config import Config, load_config, load_targets, load_telegram_config
from .drift import Target
from .history import History


async def _progress(text: str) -> None:
    """Progress and warnings are diagnostics, so they go to stderr and leave
    stdout holding nothing but the report."""
    print(text, file=sys.stderr, flush=True)


async def _check(config: Config, targets: list[Target]) -> int:
    checker = DepotChecker(config, targets, History(config.history_db_path))
    try:
        report = await checker.check(_progress)
    except (CheckInProgress, ComdirectError, ValueError) as error:
        print(f"check failed: {error}", file=sys.stderr)
        return 1
    print(report)
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="investment-tools",
        description="Compare a comdirect depot against a target allocation. Read-only.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check", help="read the depot once and print the drift report")
    commands.add_parser("bot", help="answer /check in Telegram until stopped")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
    )

    try:
        config = load_config()
        targets = load_targets(config.allocation_path)
        telegram = load_telegram_config() if args.command == "bot" else None
    except (OSError, ValueError) as error:
        print(f"configuration error: {error}", file=sys.stderr)
        return 1

    if telegram is not None:
        run(config, telegram, targets)
        return 0

    return asyncio.run(_check(config, targets))


if __name__ == "__main__":
    raise SystemExit(main())
