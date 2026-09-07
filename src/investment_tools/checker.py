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

from .comdirect import ComdirectSession
from .config import Config
from .drift import Target, calculate
from .history import History
from .report import format_report

Say = Callable[[str], Awaitable[None]]
"""Where progress and warnings go. The report itself is returned, not said."""


class CheckInProgress(RuntimeError):
    """A check is already running. The bank holds one session at a time."""


class DepotChecker:
    """Runs one depot check at a time, on request."""

    def __init__(self, config: Config, targets: list[Target], history: History) -> None:
        self._config = config
        self._targets = targets
        self._history = history
        self._lock = asyncio.Lock()

    async def check(self, say: Say) -> str:
        """Read the depot and return the report.

        Raises CheckInProgress if one is already running, ComdirectError if the
        bank refuses, and ValueError if the depot does not match the targets.
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
                await session.await_approval(challenge_id)
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
