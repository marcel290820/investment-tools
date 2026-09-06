from decimal import Decimal

import pytest

from investment_tools.drift import (
    Position,
    Target,
    band_for,
    calculate,
    top_up_eur,
)


def pos(wkn: str, value: str) -> Position:
    return Position(wkn=wkn, name=f"Fund {wkn}", value_eur=Decimal(value))


def tgt(wkn: str, share: str) -> Target:
    return Target(wkn=wkn, name=f"Fund {wkn}", share_pct=Decimal(share))


class TestBandFor:
    def test_large_target_uses_the_absolute_band(self) -> None:
        assert band_for(Decimal("40")) == Decimal("5")

    def test_small_target_uses_the_relative_band(self) -> None:
        # A flat five points would let a five percent position double first.
        assert band_for(Decimal("5")) == Decimal("1.25")

    def test_twenty_percent_is_the_crossover(self) -> None:
        assert band_for(Decimal("20")) == Decimal("5")


class TestCalculate:
    def test_shares_are_measured_against_the_depot_total(self) -> None:
        report = calculate(
            [pos("AAA", "25000"), pos("BBB", "75000")],
            [tgt("AAA", "25"), tgt("BBB", "75")],
        )
        assert report.total_eur == Decimal("100000")
        assert [row.actual_pct for row in report.rows] == [Decimal("25"), Decimal("75")]
        assert report.breached == ()

    def test_a_position_just_outside_its_band_is_flagged(self) -> None:
        # AAA target 40, band 5, sitting at 46. The other two absorb the move
        # between them so neither leaves its own band.
        report = calculate(
            [pos("AAA", "46000"), pos("BBB", "27000"), pos("CCC", "27000")],
            [tgt("AAA", "40"), tgt("BBB", "30"), tgt("CCC", "30")],
        )
        assert [row.wkn for row in report.breached] == ["AAA"]

    def test_a_position_exactly_on_the_band_edge_is_not_flagged(self) -> None:
        report = calculate(
            [pos("AAA", "45000"), pos("BBB", "55000")],
            [tgt("AAA", "40"), tgt("BBB", "60")],
        )
        assert report.breached == ()

    def test_both_sides_of_a_two_asset_depot_breach_together(self) -> None:
        # With only two holdings a deviation is mirrored, so both are out at once.
        report = calculate(
            [pos("AAA", "46000"), pos("BBB", "54000")],
            [tgt("AAA", "40"), tgt("BBB", "60")],
        )
        assert [row.wkn for row in report.breached] == ["AAA", "BBB"]

    def test_a_sold_out_position_still_appears_at_zero(self) -> None:
        report = calculate([pos("BBB", "100000")], [tgt("AAA", "40"), tgt("BBB", "60")])
        missing = next(row for row in report.rows if row.wkn == "AAA")
        assert missing.actual_pct == Decimal("0")
        assert missing.breached

    def test_a_holding_with_no_target_is_an_error(self) -> None:
        # Ignoring it would quietly understate every other position's share.
        with pytest.raises(ValueError, match="no target"):
            calculate([pos("AAA", "50000"), pos("ZZZ", "50000")], [tgt("AAA", "100")])

    def test_targets_that_do_not_sum_to_a_hundred_are_rejected(self) -> None:
        with pytest.raises(ValueError, match="sums to"):
            calculate([pos("AAA", "1000")], [tgt("AAA", "90")])

    def test_an_empty_depot_is_an_error(self) -> None:
        with pytest.raises(ValueError, match="no value"):
            calculate([pos("AAA", "0")], [tgt("AAA", "100")])


class TestTopUp:
    def test_a_contribution_lands_the_position_on_target(self) -> None:
        report = calculate(
            [pos("AAA", "30000"), pos("BBB", "70000")],
            [tgt("AAA", "40"), tgt("BBB", "60")],
        )
        row = next(r for r in report.rows if r.wkn == "AAA")
        amount = top_up_eur(row, report.total_eur)

        new_share = (row.value_eur + amount) / (report.total_eur + amount) * Decimal("100")
        assert abs(new_share - row.target_pct) < Decimal("0.0001")

    def test_an_overweight_position_cannot_be_fixed_by_buying(self) -> None:
        report = calculate(
            [pos("AAA", "60000"), pos("BBB", "40000")],
            [tgt("AAA", "40"), tgt("BBB", "60")],
        )
        row = next(r for r in report.rows if r.wkn == "AAA")
        assert top_up_eur(row, report.total_eur) < 0
