from datetime import UTC, datetime
from decimal import Decimal

from investment_tools.drift import DriftReport, Position, Target, calculate
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
