"""Telegram front end.

One command, /check. It exists because comdirect cannot be logged into
unattended: the owner has to approve the login in the photoTAN app, so the check
runs when they ask for it rather than on a timer.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

from .comdirect import ComdirectError, ComdirectSession
from .config import Config
from .drift import Target, calculate
from .history import History
from .report import format_report

logger = logging.getLogger(__name__)


class DepotChecker:
    """Runs one depot check at a time, on request."""

    def __init__(self, config: Config, targets: list[Target], history: History) -> None:
        self._config = config
        self._targets = targets
        self._history = history
        self._lock = asyncio.Lock()

    async def check(self, say: _Say) -> None:
        if self._lock.locked():
            await say("A check is already running. Approve the prompt in the photoTAN app.")
            return

        async with self._lock:
            async with ComdirectSession(
                client_id=self._config.comdirect_client_id,
                client_secret=self._config.comdirect_client_secret,
                username=self._config.comdirect_username,
                password=self._config.comdirect_password,
            ) as session:
                challenge_id = await session.start_login()
                await say("Approve the login in your photoTAN app.")
                await session.await_approval(challenge_id)
                positions = await session.all_positions()

            now = datetime.now(UTC)
            report = calculate(positions, self._targets)
            # Record before reading the runs back, so a breach that starts
            # today is reported as starting today rather than as unknown.
            self._history.record(report, now=now)
            await say(format_report(report, now=now, breach_runs=self._history.breach_runs()))


class _Say:
    """Sends a message back to the chat that asked."""

    def __init__(self, update: Update) -> None:
        self._update = update

    async def __call__(self, text: str) -> None:
        message = self._update.effective_message
        if message is not None:
            await message.reply_text(text, parse_mode=ParseMode.HTML)


def run(config: Config, targets: list[Target]) -> None:
    """Build the bot and serve /check until the process is stopped."""
    checker = DepotChecker(config, targets, History(config.history_db_path))

    async def check_command(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        chat = update.effective_chat
        if chat is None or chat.id != config.telegram_chat_id:
            # Anyone can message a bot if they find its name. Portfolio figures
            # go to exactly one chat and no error goes back to the others.
            logger.warning("ignored /check from unauthorised chat")
            return

        say = _Say(update)
        try:
            await checker.check(say)
        except ComdirectError as error:
            logger.warning("depot check failed: %s", error)
            await say(f"Check failed: {error}")
        except ValueError as error:
            logger.warning("allocation rejected the depot: %s", error)
            await say(f"Check failed: {error}")

    application = ApplicationBuilder().token(config.telegram_bot_token).build()
    application.add_handler(CommandHandler("check", check_command))
    application.run_polling()
