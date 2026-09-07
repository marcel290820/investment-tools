"""The Telegram front end.

/done releases a live bank session whose token can place orders, so who may send
it matters as much as what it does.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from types import SimpleNamespace
from typing import cast

import pytest
from telegram import Update

from investment_tools.bot import _Commands, telegram_html
from investment_tools.checker import Confirm, Say
from investment_tools.comdirect import ComdirectError
from investment_tools.config import TelegramConfig

OWNER_CHAT = 4242
TELEGRAM = TelegramConfig(bot_token="token", chat_id=OWNER_CHAT)


def test_a_fund_name_with_an_ampersand_does_not_break_the_message() -> None:
    # The bank names the funds. One called "S&P 500" would make Telegram reject
    # the whole message rather than the one line it appears on.
    assert telegram_html("! S&P 500") == "<pre>! S&amp;P 500</pre>"


def test_markup_in_a_fund_name_is_shown_not_obeyed() -> None:
    assert telegram_html("<b>x</b>") == "<pre>&lt;b&gt;x&lt;/b&gt;</pre>"


def test_quotes_survive_intact() -> None:
    # Inside <pre> they need no escaping and &#x27; would only be noise.
    assert telegram_html('the "World" fund') == '<pre>the "World" fund</pre>'


class FakeMessage:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def reply_text(self, text: str, parse_mode: str | None = None) -> None:
        self.sent.append(text)


def message_from(chat_id: int) -> tuple[Update, FakeMessage]:
    message = FakeMessage()
    update = SimpleNamespace(effective_chat=SimpleNamespace(id=chat_id), effective_message=message)
    return cast(Update, update), message


class WaitingChecker:
    """A check that gets as far as the approval and then stops there."""

    def __init__(self) -> None:
        self.confirmed = False

    async def check(self, say: Say, confirm: Confirm) -> str:
        await confirm()
        self.confirmed = True
        return "REPORT BODY"


async def until(predicate: Callable[[], bool], what: str) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 2.0
    while not predicate():
        if loop.time() > deadline:
            raise AssertionError(f"{what} never happened")
        await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_done_completes_a_waiting_check() -> None:
    checker = WaitingChecker()
    commands = _Commands(checker, TELEGRAM)
    update, message = message_from(OWNER_CHAT)

    running = asyncio.create_task(commands.check(update, None))
    await until(lambda: any("Send /done" in line for line in message.sent), "the prompt")
    assert not checker.confirmed

    await commands.done(update, None)
    await running

    assert checker.confirmed
    assert message.sent[-1] == telegram_html("REPORT BODY")


@pytest.mark.asyncio
async def test_done_from_another_chat_cannot_release_the_session() -> None:
    # The token behind that session can place orders. A stranger who guessed the
    # bot's name must not be able to hand it over.
    checker = WaitingChecker()
    commands = _Commands(checker, TELEGRAM)
    owner, owner_message = message_from(OWNER_CHAT)
    stranger, stranger_message = message_from(9999)

    running = asyncio.create_task(commands.check(owner, None))
    await until(lambda: any("Send /done" in line for line in owner_message.sent), "the prompt")

    await commands.done(stranger, None)
    await asyncio.sleep(0.05)

    assert not checker.confirmed
    assert stranger_message.sent == []

    await commands.done(owner, None)
    await running
    assert checker.confirmed


@pytest.mark.asyncio
async def test_check_from_another_chat_never_reaches_the_bank() -> None:
    class Exploding:
        async def check(self, say: Say, confirm: Confirm) -> str:
            raise AssertionError("the bank must not be touched for a stranger")

    commands = _Commands(Exploding(), TELEGRAM)
    stranger, message = message_from(9999)

    await commands.check(stranger, None)

    assert message.sent == []


@pytest.mark.asyncio
async def test_done_with_nothing_waiting_says_so() -> None:
    commands = _Commands(WaitingChecker(), TELEGRAM)
    update, message = message_from(OWNER_CHAT)

    await commands.done(update, None)

    assert message.sent == [
        telegram_html("Nothing is waiting for approval. Send /check to start one.")
    ]


@pytest.mark.asyncio
async def test_a_second_check_is_refused_and_leaves_the_first_alone() -> None:
    checker = WaitingChecker()
    commands = _Commands(checker, TELEGRAM)
    first, first_message = message_from(OWNER_CHAT)
    second, second_message = message_from(OWNER_CHAT)

    running = asyncio.create_task(commands.check(first, None))
    await until(lambda: any("Send /done" in line for line in first_message.sent), "the prompt")

    await commands.check(second, None)
    assert second_message.sent == [
        telegram_html("A check is already waiting. Send /done once the app has accepted it.")
    ]

    await commands.done(first, None)
    await running
    assert first_message.sent[-1] == telegram_html("REPORT BODY")


@pytest.mark.asyncio
async def test_a_failed_check_frees_the_slot_for_the_next_one() -> None:
    class Failing:
        async def check(self, say: Say, confirm: Confirm) -> str:
            raise ComdirectError("the bank rejected the activation")

    commands = _Commands(Failing(), TELEGRAM)
    update, message = message_from(OWNER_CHAT)

    await commands.check(update, None)
    assert "the bank rejected the activation" in message.sent[-1]

    # The slot has to be clear, or one bad check would wedge the bot for good.
    await commands.done(update, None)
    assert message.sent[-1] == telegram_html(
        "Nothing is waiting for approval. Send /check to start one."
    )
