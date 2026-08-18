"""Fuel comparison tests.

What is pinned here is the two conversions every heating comparison gets
wrong: energy content, and efficiency.
"""

from __future__ import annotations

from datetime import date

import pytest
from geopilot.fuel import (
    HEATING_OIL_SAGUENAY,
    NATURAL_GAS_ENERGIR,
    TYPICAL_EFFICIENCY,
    FuelError,
    fuel_option,
    heat_pump_option,
    ranked,
    resistance_option,
)
from geopilot.tariff import RATE_D


def test_the_published_fuel_prices_are_carried_with_their_dates() -> None:
    assert HEATING_OIL_SAGUENAY.price_per_unit == 2.0580
    assert HEATING_OIL_SAGUENAY.unit == "L"
    assert HEATING_OIL_SAGUENAY.as_of == date(2026, 8, 17)
    assert "Régie de l'énergie" in HEATING_OIL_SAGUENAY.source

    assert NATURAL_GAS_ENERGIR.price_per_unit == pytest.approx(0.59983)
    assert NATURAL_GAS_ENERGIR.unit == "m³"
    assert "Énergir" in NATURAL_GAS_ENERGIR.source


def test_a_litre_is_converted_through_its_energy_content_and_efficiency() -> None:
    """2.058 $/L over 10.61 kWh/L at 85 % is 22.8 c per useful kWh."""

    cost = HEATING_OIL_SAGUENAY.cost_per_useful_kwh(0.85)

    assert cost == pytest.approx(2.0580 / 10.61 / 0.85)
    assert cost == pytest.approx(0.2282, abs=0.0005)


def test_efficiency_moves_the_answer_the_right_way() -> None:
    """Worse equipment costs more per kWh delivered, not less."""

    good = NATURAL_GAS_ENERGIR.cost_per_useful_kwh(0.95)
    poor = NATURAL_GAS_ENERGIR.cost_per_useful_kwh(0.80)

    assert poor > good


def test_a_combustion_efficiency_above_one_is_refused() -> None:
    """Only a heat pump exceeds 1, and it burns nothing."""

    with pytest.raises(FuelError, match="at most 1"):
        HEATING_OIL_SAGUENAY.cost_per_useful_kwh(1.5)
    with pytest.raises(FuelError, match="above 0"):
        HEATING_OIL_SAGUENAY.cost_per_useful_kwh(0.0)


def test_a_heat_pump_divides_the_electricity_price_by_its_cop() -> None:
    option = heat_pump_option(3.0)

    assert option.cost_per_useful_kwh == pytest.approx(RATE_D.second_tier_price / 3)
    assert "COP 3" in option.basis


def test_a_heat_pump_defaults_to_the_marginal_electricity_price() -> None:
    """Not a blended average: its kWh are the last of the day."""

    assert heat_pump_option(1.0).cost_per_useful_kwh == RATE_D.second_tier_price


def test_a_different_electricity_price_can_be_supplied() -> None:
    """For a meter on another rate — Rate G's marginal price is lower."""

    option = heat_pump_option(3.0, price_per_kwh=0.09534)

    assert option.cost_per_useful_kwh == pytest.approx(0.09534 / 3)


def test_a_non_positive_cop_is_refused() -> None:
    with pytest.raises(FuelError, match="must be positive"):
        heat_pump_option(0.0)


def test_resistance_delivers_exactly_what_it_draws() -> None:
    assert resistance_option().cost_per_useful_kwh == RATE_D.second_tier_price


def test_an_unknown_equipment_type_is_refused_rather_than_assumed() -> None:
    with pytest.raises(FuelError, match="no typical efficiency"):
        fuel_option(HEATING_OIL_SAGUENAY, "wood stove")


def test_the_ranking_at_these_prices() -> None:
    """The comparison the whole module exists to make."""

    options = ranked(
        (
            fuel_option(HEATING_OIL_SAGUENAY, "oil furnace"),
            resistance_option(),
            fuel_option(NATURAL_GAS_ENERGIR, "gas furnace, condensing"),
            heat_pump_option(3.0),
        )
    )

    assert [option.name.split(",")[0].split(" (")[0] for option in options] == [
        "Heat pump",
        "Gaz naturel",
        "Electric resistance",
        "Mazout léger",
    ]


def test_oil_is_the_most_expensive_by_a_wide_margin() -> None:
    """At August 2026 prices, oil is twice resistance electricity."""

    oil = fuel_option(HEATING_OIL_SAGUENAY, "oil furnace")

    assert oil.cost_per_useful_kwh > 2 * resistance_option().cost_per_useful_kwh
    assert oil.cost_per_useful_kwh > 5 * heat_pump_option(3.0).cost_per_useful_kwh


def test_an_annual_cost_scales_with_the_heat_delivered() -> None:
    option = heat_pump_option(3.0)

    assert option.annual_cost(46_246) == pytest.approx(46_246 * option.cost_per_useful_kwh)
    assert option.annual_cost(0) == 0.0


def test_negative_heat_is_refused() -> None:
    with pytest.raises(FuelError, match="cannot be negative"):
        heat_pump_option(3.0).annual_cost(-1.0)


def test_the_efficiencies_flatter_combustion_rather_than_the_heat_pump() -> None:
    """Nameplate figures with no duct, cycling or chimney losses."""

    assert TYPICAL_EFFICIENCY["electric resistance"] == 1.00
    assert TYPICAL_EFFICIENCY["gas furnace, condensing"] >= 0.95
    assert TYPICAL_EFFICIENCY["oil furnace"] >= 0.85
