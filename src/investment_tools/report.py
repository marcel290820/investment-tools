"""Turn a drift report into the text the owner reads. Pure formatting.

Plain text, no markup: the terminal prints it as it stands and the Telegram
front end wraps and escapes it there. The table is column-aligned, so whoever
displays it owes it a monospace font.
"""

from __future__ import annotations

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from .drift import BreachRun, Drift, DriftReport, top_up_eur

# Below this, a suggested contribution is noise rather than an instruction.
MIN_SUGGESTION_EUR = Decimal("100")


def _eur(amount: Decimal) -> str:
    rounded = amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return f"{rounded:,.0f}".replace(",", ".")


def _pct(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP):.1f}".replace(".", ",")


def _signed_pct(value: Decimal) -> str:
    quantized = value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    sign = "+" if quantized >= 0 else "-"
    return f"{sign}{abs(quantized):.1f}".replace(".", ",")


def _days(days: int) -> str:
    return "1 day" if days == 1 else f"{days} days"


def _checks(count: int) -> str:
    return "1 check" if count == 1 else f"{count} checks"


def _row(drift: Drift) -> str:
    marker = "!" if drift.breached else " "
    return (
        f"{marker} {drift.name[:22]:<22} "
        f"{_pct(drift.actual_pct):>6} "
        f"{_pct(drift.target_pct):>6} "
        f"{_signed_pct(drift.deviation_pct):>6} "
        f"{_pct(drift.band_pct):>5}"
    )


def format_report(
    report: DriftReport,
    *,
    now: datetime,
    breach_runs: dict[str, BreachRun] | None = None,
) -> str:
    """Render the report as plain text."""
    runs = breach_runs or {}
    breached = report.breached
    if len(breached) == 1:
        headline = "1 position outside its band"
    elif breached:
        headline = f"{len(breached)} positions outside their bands"
    else:
        headline = "All positions inside their bands"

    lines = [
        headline,
        f"Depot {_eur(report.total_eur)} EUR, {now:%d.%m.%Y %H:%M}",
        "",
        f"  {'Position':<22} {'now':>6} {'target':>6} {'dev':>6} {'band':>5}",
    ]
    lines.extend(_row(drift) for drift in report.rows)

    if breached:
        # A band this wide is not tripped by a short move, so what separates a
        # passing wobble from a real shift is how long it has lasted.
        ages = []
        for drift in breached:
            run = runs.get(drift.wkn)
            if run is None:
                continue
            days = (now - run.since).days
            ages.append(
                f"  {drift.name}: since {run.since:%d.%m.%Y}"
                f", {_days(days)} and {_checks(run.checks)}"
            )
        if ages:
            lines.append("")
            lines.append("Out of band:")
            lines.extend(ages)

        # Every underweight position is a place to put new money, whether or not
        # it is the one that breached. When the breach is on the overweight side
        # these are the only moves that fix it without realising a gain.
        suggestions = []
        for drift in report.rows:
            amount = top_up_eur(drift, report.total_eur)
            if amount >= MIN_SUGGESTION_EUR:
                suggestions.append(f"  {_eur(amount)} EUR into {drift.name}")
        if suggestions:
            lines.append("")
            lines.append("Buy rather than rebalance. Selling realises a taxable gain.")
            lines.append("To put each position back on target with new money alone:")
            lines.extend(suggestions)

        overweight = [d for d in report.rows if d.deviation_pct > 0]
        if overweight:
            lines.append("")
            lines.append(
                "Overweight: "
                + ", ".join(d.name for d in overweight)
                + ". Pause contributions here and let the others catch up."
            )

    return "\n".join(lines)
