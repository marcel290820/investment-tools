import asyncio
from pathlib import Path

import pytest

from investment_tools import __main__ as cli
from investment_tools.checker import Say
from investment_tools.config import Config
from investment_tools.drift import Target
from investment_tools.history import History

BANK_ENV = {
    "COMDIRECT_CLIENT_ID": "client",
    "COMDIRECT_CLIENT_SECRET": "secret",
    "COMDIRECT_USERNAME": "12345678",
    "COMDIRECT_PASSWORD": "123456",
}


class StubChecker:
    """Stands in for a real check so the CLI can be exercised without a bank."""

    def __init__(self, config: Config, targets: list[Target], history: History) -> None:
        self._history = history

    async def check(self, say: Say) -> str:
        await say("Approve the login in your photoTAN app.")
        return "REPORT BODY"


class FailingChecker(StubChecker):
    async def check(self, say: Say) -> str:
        raise ValueError("the depot holds ZZZ, which the allocation does not name")


@pytest.fixture
def configured(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """A working environment with no Telegram settings in it."""
    allocation = tmp_path / "allocation.toml"
    allocation.write_text(
        '[[position]]\nwkn = "AAA"\nshare_pct = 60\n[[position]]\nwkn = "BBB"\nshare_pct = 40\n'
    )
    for name, value in BANK_ENV.items():
        monkeypatch.setenv(name, value)
    for name in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ALLOCATION_PATH", str(allocation))
    monkeypatch.setenv("HISTORY_DB_PATH", str(tmp_path / "history.db"))
    return tmp_path


def test_check_puts_the_report_on_stdout_and_progress_on_stderr(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], configured: Path
) -> None:
    # Redirecting the report to a file must not swallow the line telling you to
    # reach for your phone, and must not capture it either.
    monkeypatch.setattr(cli, "DepotChecker", StubChecker)

    assert cli.main(["check"]) == 0

    captured = capsys.readouterr()
    assert captured.out.strip() == "REPORT BODY"
    assert "photoTAN" in captured.err
    assert "REPORT BODY" not in captured.err


def test_check_runs_without_any_telegram_settings(
    monkeypatch: pytest.MonkeyPatch, configured: Path
) -> None:
    monkeypatch.setattr(cli, "DepotChecker", StubChecker)
    assert cli.main(["check"]) == 0


def test_the_bot_still_needs_its_telegram_settings(configured: Path) -> None:
    assert cli.main(["bot"]) == 1


def test_a_rejected_depot_exits_non_zero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], configured: Path
) -> None:
    monkeypatch.setattr(cli, "DepotChecker", FailingChecker)

    assert cli.main(["check"]) == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "which the allocation does not name" in captured.err


def test_missing_credentials_are_a_configuration_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    for name in (*BANK_ENV, "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
        monkeypatch.delenv(name, raising=False)

    assert cli.main(["check"]) == 1
    assert "configuration error" in capsys.readouterr().err


def test_progress_never_lands_on_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    asyncio.run(cli._progress("reaching for the phone"))
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "reaching for the phone"
