from datetime import UTC, datetime
from decimal import Decimal

from investment_tools.drift import BreachRun, DriftReport, Position, Target, calculate
from investment_tools.report import format_report

NOW = datetime(2026, 9, 6, 18, 30, tzinfo=UTC)


def report_for(values: dict[str, str], targets: dict[str, str]) -> DriftReport:
    return calculate(
        [Position(wkn=w, name=f"Fund {w}", value_eur=Decimal(v)) for w, v in values.items()],
        [Target(wkn=w, name=f"Fund {w}", share_pct=Decimal(s)) for w, s in targets.items()],
    )


def test_a_balanced_depot_reports_no_action() -> None:
    report = report_for({"AAA": "40000", "BBB": "60000"}, {"AAA": "40", "BBB": "60"})
    text = format_report(report, now=NOW)
    assert "All positions inside their bands" in text
    assert "taxable" not in text


def test_a_drifted_depot_suggests_buying_not_selling() -> None:
    report = report_for({"AAA": "30000", "BBB": "70000"}, {"AAA": "40", "BBB": "60"})
    text = format_report(report, now=NOW)
    assert "2 positions outside their bands" in text
    assert "Selling realises a taxable gain" in text
    assert "into Fund AAA" in text


def test_the_overweight_side_is_told_to_pause_rather_than_sell() -> None:
    report = report_for({"AAA": "30000", "BBB": "70000"}, {"AAA": "40", "BBB": "60"})
    text = format_report(report, now=NOW)
    assert "Pause contributions" in text
    assert "Fund BBB. Pause contributions" in text


def test_totals_use_german_thousands_separators() -> None:
    report = report_for({"AAA": "40000", "BBB": "60000"}, {"AAA": "40", "BBB": "60"})
    text = format_report(report, now=NOW)
    assert "Depot 100.000 EUR" in text


def test_an_overweight_breach_still_names_somewhere_to_put_money() -> None:
    # The breach is on the overweight side, so no contribution fixes that
    # position directly. The report has to point at the underweight ones
    # instead, otherwise it flags a problem and offers nothing but a sale.
    report = report_for(
        {"AAA": "46000", "BBB": "27000", "CCC": "27000"},
        {"AAA": "40", "BBB": "30", "CCC": "30"},
    )
    text = format_report(report, now=NOW)
    assert "1 position outside its band" in text
    assert "into Fund BBB" in text
    assert "into Fund CCC" in text


def test_a_breach_reports_how_long_it_has_lasted() -> None:
    report = report_for(
        {"AAA": "46000", "BBB": "27000", "CCC": "27000"},
        {"AAA": "40", "BBB": "30", "CCC": "30"},
    )
    runs = {"AAA": BreachRun(since=datetime(2026, 8, 12, tzinfo=UTC), checks=4)}
    text = format_report(report, now=NOW, breach_runs=runs)
    assert "Out of band:" in text
    assert "since 12.08.2026, 25 days and 4 checks" in text


def test_a_fresh_breach_reads_as_one_check() -> None:
    report = report_for(
        {"AAA": "46000", "BBB": "27000", "CCC": "27000"},
        {"AAA": "40", "BBB": "30", "CCC": "30"},
    )
    runs = {"AAA": BreachRun(since=NOW, checks=1)}
    text = format_report(report, now=NOW, breach_runs=runs)
    assert "0 days and 1 check" in text


def test_the_report_carries_no_markup() -> None:
    # The terminal prints this as it stands. Markup belongs to whichever front
    # end needs it, and the Telegram one adds its own.
    report = report_for({"AAA": "30000", "BBB": "70000"}, {"AAA": "40", "BBB": "60"})
    text = format_report(report, now=NOW)
    assert "<" not in text
    assert ">" not in text


def test_columns_line_up_under_a_monospace_font() -> None:
    report = report_for({"AAA": "30000", "BBB": "70000"}, {"AAA": "40", "BBB": "60"})
    lines = format_report(report, now=NOW).splitlines()
    header_at = next(index for index, line in enumerate(lines) if "Position" in line)
    rows = lines[header_at + 1 : header_at + 1 + len(report.rows)]
    assert len(rows) == 2
    assert all(len(row) == len(lines[header_at]) for row in rows)
