"""Allocation drift: pure calculation, no I/O.

Given what the depot actually holds and what it is supposed to hold, decide
which positions have wandered far enough to be worth acting on.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

# Swedroe's 5/25 rule. A position is out of band once it moves either 5
# percentage points away from its target, or a quarter of the target's own
# size, whichever comes first. The relative half is what protects small
# positions: 25 percent of a 5 percent target is a 1.25 point band, while a
# flat 5 points would let that position double before anything fired.
ABSOLUTE_BAND_POINTS = Decimal("5")
RELATIVE_BAND_FRACTION = Decimal("0.25")

_HUNDRED = Decimal("100")


@dataclass(frozen=True)
class Position:
    """A holding, valued by the bank at current prices."""

    wkn: str
    name: str
    value_eur: Decimal


@dataclass(frozen=True)
class Target:
    """The share of the depot a holding is supposed to occupy, in percent."""

    wkn: str
    name: str
    share_pct: Decimal


@dataclass(frozen=True)
class Drift:
    wkn: str
    name: str
    target_pct: Decimal
    actual_pct: Decimal
    value_eur: Decimal
    band_pct: Decimal

    @property
    def deviation_pct(self) -> Decimal:
        """Signed distance from target, in percentage points."""
        return self.actual_pct - self.target_pct

    @property
    def breached(self) -> bool:
        return abs(self.deviation_pct) > self.band_pct


@dataclass(frozen=True)
class DriftReport:
    total_eur: Decimal
    rows: tuple[Drift, ...]

    @property
    def breached(self) -> tuple[Drift, ...]:
        return tuple(row for row in self.rows if row.breached)


def band_for(target_pct: Decimal) -> Decimal:
    """Half-width of the no-action band around a target, in percentage points."""
    return min(ABSOLUTE_BAND_POINTS, target_pct * RELATIVE_BAND_FRACTION)


def top_up_eur(drift: Drift, total_eur: Decimal) -> Decimal:
    """Cash to put into this one position to land it back on target.

    Selling a winner in a German depot realises a taxable gain, so the cheap way
    back to the target allocation is new money rather than a rebalance. This
    solves (value + x) / (total + x) = target for x, which assumes the
    contribution goes to this position alone. Negative for an overweight
    position, where no contribution can help and the drift has to be absorbed by
    topping up the others.
    """
    target = drift.target_pct / _HUNDRED
    if target >= 1:
        raise ValueError(f"target share for {drift.wkn} must be below 100 percent")
    return (target * total_eur - drift.value_eur) / (1 - target)


def calculate(positions: list[Position], targets: list[Target]) -> DriftReport:
    """Compare a depot against its target allocation.

    Raises if the two sides disagree about which instruments exist, because a
    silently ignored position would understate the drift on every other one.
    """
    if not targets:
        raise ValueError("no target allocation configured")

    total_share = sum((t.share_pct for t in targets), Decimal(0))
    if abs(total_share - _HUNDRED) > Decimal("0.05"):
        raise ValueError(f"target allocation sums to {total_share}, expected 100")

    held = {p.wkn: p for p in positions}
    wanted = {t.wkn for t in targets}

    untracked = sorted(set(held) - wanted)
    if untracked:
        raise ValueError(f"depot holds positions with no target: {', '.join(untracked)}")

    total_eur = sum((p.value_eur for p in positions), Decimal(0))
    if total_eur <= 0:
        raise ValueError("depot has no value to allocate")

    rows = []
    for target in targets:
        position = held.get(target.wkn)
        value = position.value_eur if position else Decimal(0)
        rows.append(
            Drift(
                wkn=target.wkn,
                name=position.name if position else target.name,
                target_pct=target.share_pct,
                actual_pct=value / total_eur * _HUNDRED,
                value_eur=value,
                band_pct=band_for(target.share_pct),
            )
        )

    return DriftReport(total_eur=total_eur, rows=tuple(rows))


@dataclass(frozen=True)
class BreachRun:
    """How long a position has been continuously out of band."""

    since: datetime
    checks: int
