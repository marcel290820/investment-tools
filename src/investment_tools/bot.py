"""Telegram front end.

One command, /check. It exists because comdirect cannot be logged into
unattended: the owner has to approve the login in the photoTAN app, so the check
runs when they ask for it rather than on a timer.
"""

from __future__ import annotations

import asyncio
import html
import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, CommandHandler

from .checker import Check, CheckInProgress, DepotChecker
from .comdirect import ComdirectError
from .config import Config, TelegramConfig
from .drift import Target
from .history import History

logger = logging.getLogger(__name__)


def telegram_html(text: str) -> str:
    """Wrap plain report text for Telegram.

    <pre> because the report is a column-aligned table and Telegram's
    proportional font would shear it. Escaped because fund names come from the
    bank: a holding called "S&P 500" would otherwise make Telegram reject the
    whole message. Only <, > and & need escaping, and quotes inside <pre> read
    better left alone.
    """
    return f"<pre>{html.escape(text, quote=False)}</pre>"


class _Say:
    """Sends a message back to the chat that asked."""

    def __init__(self, update: Update) -> None:
        self._update = update

    async def __call__(self, text: str) -> None:
        message = self._update.effective_message
        if message is not None:
            await message.reply_text(telegram_html(text), parse_mode=ParseMode.HTML)


class _Approval:
    """Carries /done back to the check that is waiting on it."""

    def __init__(self, say: _Say) -> None:
        self._say = say
        self._approved = asyncio.Event()

    def approve(self) -> None:
        self._approved.set()

    async def __call__(self) -> None:
        await self._say("Send /done once the app says it accepted it.")
        await self._approved.wait()


class _Commands:
    """The two commands and the one piece of state they share.

    /check blocks on an approval only /done can deliver, so both need to see the
    same slot. Nothing else does, which is why it lives here and not on the
    checker.
    """

    def __init__(self, checker: Check, telegram: TelegramConfig) -> None:
        self._checker = checker
        self._telegram = telegram
        self._waiting: _Approval | None = None

    def _authorised(self, update: Update, command: str) -> bool:
        """Anyone can message a bot if they find its name. Portfolio figures go
        to exactly one chat, and so does the power to release a bank session."""
        chat = update.effective_chat
        if chat is None or chat.id != self._telegram.chat_id:
            logger.warning("ignored /%s from unauthorised chat", command)
            return False
        return True

    async def check(self, update: Update, _context: object) -> None:
        if not self._authorised(update, "check"):
            return

        say = _Say(update)
        if self._waiting is not None:
            await say("A check is already waiting. Send /done once the app has accepted it.")
            return

        approval = _Approval(say)
        self._waiting = approval
        try:
            report = await self._checker.check(say, approval)
        except CheckInProgress as error:
            await say(str(error))
        except ComdirectError as error:
            logger.warning("depot check failed: %s", error)
            await say(f"Check failed: {error}")
        except ValueError as error:
            logger.warning("allocation rejected the depot: %s", error)
            await say(f"Check failed: {error}")
        else:
            await say(report)
        finally:
            # Only ours. Clearing the slot unconditionally would strand a later
            # check that is still waiting for its own /done.
            if self._waiting is approval:
                self._waiting = None

    async def done(self, update: Update, _context: object) -> None:
        if not self._authorised(update, "done"):
            return
        if self._waiting is None:
            await _Say(update)("Nothing is waiting for approval. Send /check to start one.")
            return
        self._waiting.approve()


def run(config: Config, telegram: TelegramConfig, targets: list[Target]) -> None:
    """Build the bot and serve /check until the process is stopped."""
    commands = _Commands(DepotChecker(config, targets, History(config.history_db_path)), telegram)
    application = ApplicationBuilder().token(telegram.bot_token).build()
    # block=False, or the update loop would sit inside /check and /done could
    # never arrive: the one thing the check is waiting for would deadlock it.
    application.add_handler(CommandHandler("check", commands.check, block=False))
    application.add_handler(CommandHandler("done", commands.done))
    application.run_polling()
