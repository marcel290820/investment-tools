"""Telegram front end.

One command, /check. It exists because comdirect cannot be logged into
unattended: the owner has to approve the login in the photoTAN app, so the check
runs when they ask for it rather than on a timer.
"""

from __future__ import annotations

import html
import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

from .checker import CheckInProgress, DepotChecker
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


def run(config: Config, telegram: TelegramConfig, targets: list[Target]) -> None:
    """Build the bot and serve /check until the process is stopped."""
    checker = DepotChecker(config, targets, History(config.history_db_path))

    async def check_command(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        chat = update.effective_chat
        if chat is None or chat.id != telegram.chat_id:
            # Anyone can message a bot if they find its name. Portfolio figures
            # go to exactly one chat and no error goes back to the others.
            logger.warning("ignored /check from unauthorised chat")
            return

        say = _Say(update)
        try:
            report = await checker.check(say)
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

    application = ApplicationBuilder().token(telegram.bot_token).build()
    application.add_handler(CommandHandler("check", check_command))
    application.run_polling()
