"""Check history, so drift can be read as persistent or momentary.

A single reading says nothing. The bands are wide enough that no short move
trips them, but knowing a position has sat outside its band since August is a
different fact from knowing it crossed this morning, and only the store can tell
the two apart.

Amounts are kept as text. A share written through a float and read back is no
longer the number that was measured.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import datetime
from pathlib import Path

from .drift import BreachRun, DriftReport

SCHEMA = """
CREATE TABLE IF NOT EXISTS observation (
    checked_at TEXT    NOT NULL,
    wkn        TEXT    NOT NULL,
    value_eur  TEXT    NOT NULL,
    actual_pct TEXT    NOT NULL,
    target_pct TEXT    NOT NULL,
    band_pct   TEXT    NOT NULL,
    breached   INTEGER NOT NULL,
    PRIMARY KEY (checked_at, wkn)
);
"""


class History:
    """Every observation the bot has made, keyed by check time and instrument."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(self._path)) as connection, connection:
            yield connection

    def record(self, report: DriftReport, *, now: datetime) -> None:
        """Append one check. Re-recording the same instant replaces it."""
        rows = [
            (
                now.isoformat(),
                row.wkn,
                str(row.value_eur),
                str(row.actual_pct),
                str(row.target_pct),
                str(row.band_pct),
                int(row.breached),
            )
            for row in report.rows
        ]
        with self._connect() as connection:
            connection.executemany(
                "INSERT OR REPLACE INTO observation "
                "(checked_at, wkn, value_eur, actual_pct, target_pct, band_pct, breached) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                rows,
            )

    def breach_runs(self) -> dict[str, BreachRun]:
        """For each position currently out of band, when the run started.

        A check that came back inside the band ends the run: the drift went away
        and whatever comes later is a new episode, not a continuation.

        ponytail: reads every row. The table gains four rows per check, so this
        stays trivial for years. Add a per-wkn window query if it ever does not.
        """
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT wkn, checked_at, breached FROM observation ORDER BY wkn, checked_at DESC"
            ).fetchall()

        runs: dict[str, BreachRun] = {}
        by_wkn: dict[str, list[tuple[str, int]]] = {}
        for wkn, checked_at, breached in rows:
            by_wkn.setdefault(wkn, []).append((checked_at, breached))

        for wkn, observations in by_wkn.items():
            if not observations[0][1]:
                continue  # newest check is inside the band, so there is no run
            run = list(_take_while_breached(observations))
            runs[wkn] = BreachRun(since=datetime.fromisoformat(run[-1]), checks=len(run))
        return runs


def _take_while_breached(observations: list[tuple[str, int]]) -> Iterator[str]:
    for checked_at, breached in observations:
        if not breached:
            return
        yield checked_at
