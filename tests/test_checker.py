"""The waiting is the part worth testing.

Between the login and the activation the bank session is open, and the token it
issued can place orders. Nothing may hold that open indefinitely.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from pathlib import Path

import pytest

from investment_tools import checker as checker_module
from investment_tools.checker import DepotChecker
from investment_tools.comdirect import ComdirectError
from investment_tools.config import Config
from investment_tools.drift import Position, Target
from investment_tools.history import History


class FakeSession:
    """A bank that logs in instantly and reports what was asked of it."""

    last: FakeSession | None = None

    def __init__(self, **_: str) -> None:
        self.activated_with: str | None = None
        self.revoked = False
        FakeSession.last = self

    async def __aenter__(self) -> FakeSession:
        return self

    async def __aexit__(self, *_: object) -> None:
        self.revoked = True

    async def start_login(self) -> str:
        return "challenge-1"

    async def activate(self, challenge_id: str) -> None:
        self.activated_with = challenge_id

    async def all_positions(self) -> list[Position]:
        return [
            Position(wkn="AAA", name="Fund A", value_eur=Decimal("6000")),
            Position(wkn="BBB", name="Fund B", value_eur=Decimal("4000")),
        ]


def checker_for(tmp_path: Path) -> DepotChecker:
    config = Config(
        comdirect_client_id="id",
        comdirect_client_secret="secret",
        comdirect_username="user",
        comdirect_password="pin",
        allocation_path=tmp_path / "allocation.toml",
        history_db_path=tmp_path / "history.db",
    )
    targets = [
        Target(wkn="AAA", name="Fund A", share_pct=Decimal("60")),
        Target(wkn="BBB", name="Fund B", share_pct=Decimal("40")),
    ]
    return DepotChecker(config, targets, History(config.history_db_path))


async def _said(_: str) -> None:
    pass


@pytest.mark.asyncio
async def test_the_session_is_only_activated_after_someone_confirms(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(checker_module, "ComdirectSession", FakeSession)
    confirmed = asyncio.Event()

    async def confirm() -> None:
        confirmed.set()

    report = await checker_for(tmp_path).check(_said, confirm)

    assert confirmed.is_set()
    assert FakeSession.last is not None
    assert FakeSession.last.activated_with == "challenge-1"
    assert "All positions inside their bands" in report


@pytest.mark.asyncio
async def test_nobody_confirming_ends_the_session_rather_than_waiting(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(checker_module, "ComdirectSession", FakeSession)
    monkeypatch.setattr(checker_module, "APPROVAL_TIMEOUT_SECONDS", 0.05)

    async def never() -> None:
        await asyncio.Event().wait()

    with pytest.raises(ComdirectError, match="within 0s"):
        await checker_for(tmp_path).check(_said, never)

    assert FakeSession.last is not None
    assert FakeSession.last.activated_with is None
    assert FakeSession.last.revoked


@pytest.mark.asyncio
async def test_a_warning_is_raised_when_the_bank_did_not_confirm_the_revoke(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class UnrevokedSession(FakeSession):
        async def __aexit__(self, *_: object) -> None:
            self.revoked = False

    monkeypatch.setattr(checker_module, "ComdirectSession", UnrevokedSession)
    said: list[str] = []

    async def say(text: str) -> None:
        said.append(text)

    async def confirm() -> None:
        pass

    await checker_for(tmp_path).check(say, confirm)

    assert any("did not confirm the session was revoked" in line for line in said)
