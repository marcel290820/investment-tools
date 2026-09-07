"""One depot check, from login to finished report.

Both front ends run this same sequence and differ only in where the words come
out. Progress goes to a callback because the terminal and Telegram put it in
different places; the report is returned so the caller decides what it is. In a
terminal that distinction is what keeps the report on stdout and the "approve
the prompt" line on stderr.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Protocol

from .comdirect import ComdirectError, ComdirectSession
from .config import Config
from .drift import Target, calculate
from .history import History
from .report import format_report

Say = Callable[[str], Awaitable[None]]
"""Where progress and warnings go. The report itself is returned, not said."""

Confirm = Callable[[], Awaitable[None]]
"""Resolves once the owner says the photoTAN app accepted the prompt.

There is nothing to poll. With photoTAN-Push the bank answers the activation
with 400 until the approval lands, which is the same answer it gives a malformed
request, and repeating the call risks the lockout counters in the spec. So a
person tells us, and only then does the activation go out.
"""

# A bounded wait, because until it ends the bank session is open and the token
# it issued can trade.
APPROVAL_TIMEOUT_SECONDS = 180.0


class CheckInProgress(RuntimeError):
    """A check is already running. The bank holds one session at a time."""


class Check(Protocol):
    """All a front end needs from a checker: ask, be told, get a report back."""

    async def check(self, say: Say, confirm: Confirm) -> str: ...


class DepotChecker:
    """Runs one depot check at a time, on request."""

    def __init__(self, config: Config, targets: list[Target], history: History) -> None:
        self._config = config
        self._targets = targets
        self._history = history
        self._lock = asyncio.Lock()

    async def check(self, say: Say, confirm: Confirm) -> str:
        """Read the depot and return the report.

        Raises CheckInProgress if one is already running, ComdirectError if the
        bank refuses or nobody confirms in time, and ValueError if the depot does
        not match the targets.
        """
        if self._lock.locked():
            raise CheckInProgress(
                "A check is already running. Approve the prompt in the photoTAN app."
            )

        async with self._lock:
            async with ComdirectSession(
                client_id=self._config.comdirect_client_id,
                client_secret=self._config.comdirect_client_secret,
                username=self._config.comdirect_username,
                password=self._config.comdirect_password,
            ) as session:
                challenge_id = await session.start_login()
                await say("Approve the login in your photoTAN app.")
                try:
                    async with asyncio.timeout(APPROVAL_TIMEOUT_SECONDS):
                        await confirm()
                except TimeoutError:
                    raise ComdirectError(
                        f"nobody confirmed the approval within {APPROVAL_TIMEOUT_SECONDS:.0f}s"
                    ) from None
                await session.activate(challenge_id)
                positions = await session.all_positions()

            if not session.revoked:
                # The bank did not confirm the session is dead, and the token it
                # issued can place orders. Say so rather than let it lapse quietly.
                await say(
                    "Warning: the bank did not confirm the session was revoked. "
                    "It expires on its own within about 10 minutes. "
                    "If you did not trigger this check, change your PIN."
                )

            now = datetime.now(UTC)
            report = calculate(positions, self._targets)
            # Record before reading the runs back, so a breach that starts
            # today is reported as starting today rather than as unknown.
            self._history.record(report, now=now)
            return format_report(report, now=now, breach_runs=self._history.breach_runs())
