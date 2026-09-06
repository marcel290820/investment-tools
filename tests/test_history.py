from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from investment_tools.drift import Position, Target, calculate
from investment_tools.history import History

START = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)

BALANCED = {"AAA": "40000", "BBB": "30000", "CCC": "30000"}
AAA_OUT = {"AAA": "46000", "BBB": "27000", "CCC": "27000"}
TARGETS = {"AAA": "40", "BBB": "30", "CCC": "30"}


def report_for(values: dict[str, str]):  # type: ignore[no-untyped-def]
    return calculate(
        [Position(wkn=w, name=w, value_eur=Decimal(v)) for w, v in values.items()],
        [Target(wkn=w, name=w, share_pct=Decimal(s)) for w, s in TARGETS.items()],
    )


def history(tmp_path: Path) -> History:
    return History(tmp_path / "state" / "history.db")


def test_a_new_database_is_created_with_its_directory(tmp_path: Path) -> None:
    store = history(tmp_path)
    assert (tmp_path / "state" / "history.db").exists()
    assert store.breach_runs() == {}


def test_a_position_inside_its_band_starts_no_run(tmp_path: Path) -> None:
    store = history(tmp_path)
    store.record(report_for(BALANCED), now=START)
    assert store.breach_runs() == {}


def test_a_run_starts_at_the_first_breached_check(tmp_path: Path) -> None:
    store = history(tmp_path)
    store.record(report_for(BALANCED), now=START)
    store.record(report_for(AAA_OUT), now=START + timedelta(days=30))
    store.record(report_for(AAA_OUT), now=START + timedelta(days=60))

    runs = store.breach_runs()
    assert set(runs) == {"AAA"}
    assert runs["AAA"].since == START + timedelta(days=30)
    assert runs["AAA"].checks == 2


def test_coming_back_inside_the_band_ends_the_run(tmp_path: Path) -> None:
    # The drift went away, so a later breach is a new episode rather than a
    # continuation of the old one.
    store = history(tmp_path)
    store.record(report_for(AAA_OUT), now=START)
    store.record(report_for(BALANCED), now=START + timedelta(days=30))
    store.record(report_for(AAA_OUT), now=START + timedelta(days=60))

    runs = store.breach_runs()
    assert runs["AAA"].since == START + timedelta(days=60)
    assert runs["AAA"].checks == 1


def test_a_resolved_breach_leaves_no_run(tmp_path: Path) -> None:
    store = history(tmp_path)
    store.record(report_for(AAA_OUT), now=START)
    store.record(report_for(BALANCED), now=START + timedelta(days=30))
    assert store.breach_runs() == {}


def test_recording_the_same_instant_twice_does_not_duplicate(tmp_path: Path) -> None:
    store = history(tmp_path)
    store.record(report_for(AAA_OUT), now=START)
    store.record(report_for(AAA_OUT), now=START)
    assert store.breach_runs()["AAA"].checks == 1


def test_history_survives_reopening_the_file(tmp_path: Path) -> None:
    history(tmp_path).record(report_for(AAA_OUT), now=START)
    assert history(tmp_path).breach_runs()["AAA"].since == START


def test_amounts_are_stored_exactly_and_not_through_a_float(tmp_path: Path) -> None:
    # A share written as a float and read back is no longer the number that was
    # measured, and this file is the record of what the depot actually held.
    import sqlite3

    path = tmp_path / "state" / "history.db"
    store = History(path)
    store.record(report_for({"AAA": "40000.07", "BBB": "29999.93", "CCC": "30000"}), now=START)

    with sqlite3.connect(path) as connection:
        stored = dict(connection.execute("SELECT wkn, value_eur FROM observation").fetchall())
    assert stored["AAA"] == "40000.07"
    assert Decimal(stored["BBB"]) == Decimal("29999.93")
