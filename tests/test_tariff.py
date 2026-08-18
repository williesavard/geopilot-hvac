"""Tariff tests.

The figures are transcribed from Hydro-Québec's rate document. These tests do
not re-derive them; they pin the arithmetic that uses them, and above all the
distinction between a blended average and a marginal price.
"""

from __future__ import annotations

from datetime import date

import pytest
from geopilot.tariff import RATE_D, RATE_DT, TariffError


def test_the_published_prices_are_carried_exactly() -> None:
    """46,154 ¢/day, 7,065 ¢ to 40 kWh/day, 11,142 ¢ beyond. Article 2.5."""

    assert RATE_D.access_per_day == 0.46154
    assert RATE_D.first_tier_price == 0.07065
    assert RATE_D.first_tier_kwh_per_day == 40.0
    assert RATE_D.second_tier_price == 0.11142
    assert RATE_D.effective_from == date(2026, 4, 1)


def test_consumption_under_the_threshold_stays_in_the_first_tier() -> None:
    cost = RATE_D.bill(300.0, days=30)

    assert cost == pytest.approx(30 * 0.46154 + 300 * 0.07065)


def test_the_threshold_scales_with_the_days_in_the_period() -> None:
    """40 kWh per day, not 40 kWh per bill. A longer period gets more cheap kWh.

    Compared on the energy alone: the same 2000 kWh crosses the tier over 30
    days and stays under it over 60.
    """

    access_30 = 30 * RATE_D.access_per_day
    access_60 = 60 * RATE_D.access_per_day

    energy_30 = RATE_D.bill(2000.0, days=30) - access_30
    energy_60 = RATE_D.bill(2000.0, days=60) - access_60

    assert energy_30 > energy_60
    assert energy_60 == pytest.approx(2000 * RATE_D.first_tier_price)


def test_the_access_charge_grows_with_the_period_even_as_energy_gets_cheaper() -> None:
    """Worth pinning: a longer period is not uniformly cheaper.

    The daily charge is paid per day regardless, so stretching a period buys a
    larger cheap allowance and a larger fixed cost at the same time. Which wins
    depends on the consumption, and neither direction is a rule.
    """

    assert RATE_D.bill(400.0, days=60) > RATE_D.bill(400.0, days=30)
    assert RATE_D.bill(2000.0, days=60) < RATE_D.bill(2000.0, days=30)


def test_consumption_over_the_threshold_splits_between_the_tiers() -> None:
    cost = RATE_D.bill(2000.0, days=30)
    threshold = 40 * 30

    assert cost == pytest.approx(
        30 * 0.46154 + threshold * 0.07065 + (2000 - threshold) * 0.11142
    )


def test_a_heat_pumps_kwh_are_billed_at_the_second_tier() -> None:
    """In a house already past 40 kWh/day, they are the last kWh of the day."""

    assert RATE_D.marginal_cost(1000.0) == pytest.approx(111.42)


def test_the_marginal_cost_excludes_the_access_charge() -> None:
    """It is paid whether the machine runs or not, so it is not the machine's."""

    assert RATE_D.marginal_cost(0.0) == 0.0


def test_a_blended_average_understates_what_a_machine_costs() -> None:
    """The error that makes efficiency look less valuable than it is."""

    blended = RATE_D.blended_price(2000.0, days=30)

    assert blended < RATE_D.second_tier_price
    assert RATE_D.marginal_cost(1000.0) > 1000 * blended


def test_the_understatement_is_worth_real_money() -> None:
    """Roughly a fifth, at a consumption in this installation's range."""

    blended = RATE_D.blended_price(2000.0, days=30)
    understated = 1000 * blended
    honest = RATE_D.marginal_cost(1000.0)

    assert (honest - understated) / honest > 0.15


def test_negative_consumption_is_refused() -> None:
    with pytest.raises(TariffError, match="cannot be negative"):
        RATE_D.bill(-1.0, days=30)
    with pytest.raises(TariffError, match="cannot be negative"):
        RATE_D.marginal_cost(-1.0)


def test_a_period_of_no_days_is_refused() -> None:
    """The threshold is a product with the day count; zero days has no meaning."""

    with pytest.raises(TariffError, match="at least one day"):
        RATE_D.bill(100.0, days=0)


def test_a_blended_price_of_nothing_is_refused() -> None:
    with pytest.raises(TariffError, match="needs some consumption"):
        RATE_D.blended_price(0.0, days=30)


def test_rates_are_known_to_go_stale_every_first_of_april() -> None:
    assert not RATE_D.stale_after(date(2026, 4, 1))
    assert not RATE_D.stale_after(date(2027, 3, 31))
    assert RATE_D.stale_after(date(2027, 4, 1))
    assert RATE_D.stale_after(date(2028, 1, 15))


def test_dual_energy_is_cheaper_when_mild_and_punishing_when_cold() -> None:
    """The reason it is recorded but not offered as a saving."""

    assert RATE_DT.mild_price < RATE_D.second_tier_price / 2
    assert RATE_DT.cold_price > RATE_D.second_tier_price * 2.5
    assert RATE_DT.threshold_celsius == -12.0


def test_every_rate_carries_the_document_it_came_from() -> None:
    for rate in (RATE_D, RATE_DT):
        assert "Hydro-Québec" in rate.source
        assert "2026" in rate.source
