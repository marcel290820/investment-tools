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


async def _confirm() -> None:
    """Wait for Enter.

    The bank cannot be asked whether the push has been approved, so a person has
    to say so. Reading the descriptor directly rather than through a thread keeps
    Ctrl-C working: a cancelled wait still unwinds into the revoke.
    """
    print(
        "Press Enter once the photoTAN app says it accepted it: ",
        end="",
        file=sys.stderr,
        flush=True,
    )
    loop = asyncio.get_running_loop()
    pressed: asyncio.Future[None] = loop.create_future()

    def _on_readable() -> None:
        sys.stdin.readline()
        if not pressed.done():
            pressed.set_result(None)

    loop.add_reader(sys.stdin.fileno(), _on_readable)
    try:
        await pressed
    finally:
        loop.remove_reader(sys.stdin.fileno())


async def _check(config: Config, targets: list[Target]) -> int:
    if not sys.stdin.isatty():
        # Checked before the login, because reaching the bank at all spends one
        # of the five TAN challenges it allows before it locks online banking.
        print(
            "check needs a terminal: nothing but you can tell the bank that you "
            "approved the prompt in the photoTAN app.",
            file=sys.stderr,
        )
        return 1

    checker = DepotChecker(config, targets, History(config.history_db_path))
    try:
        report = await checker.check(_progress, _confirm)
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
