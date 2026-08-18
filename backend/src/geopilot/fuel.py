"""What a delivered kilowatt-hour of heat costs, whatever it is burnt from.

Comparing heating options means comparing the same thing: **one kilowatt-hour
of heat inside the house**. Getting there from a posted price takes two
conversions, and both are places where comparisons usually go wrong.

1. **Energy content.** Oil is sold by the litre and gas by the cubic metre.
   Neither is a kilowatt-hour.
2. **Efficiency.** A litre of oil burnt at 85 % delivers 85 % of its content
   into the house. A heat pump at COP 3 delivers *three times* the electricity
   it draws, which is why it is the only entry here whose efficiency exceeds
   100 % and why comparing fuel prices without it is meaningless.

Every price below carries its source and its date. Fuel prices move weekly and
gas supply prices move monthly, so a figure compiled into software is a
snapshot — `as_of` says which one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from geopilot.tariff import RATE_D, TariffError

# --------------------------------------------------------------------------
# Energy content
# --------------------------------------------------------------------------

OIL_KWH_PER_LITRE = 10.61
"""Light heating oil, no. 2: 38.2 MJ/L higher heating value.

Natural Resources Canada's conversion factor for furnace oil. 38.2 MJ ÷ 3.6
MJ/kWh = 10.61 kWh/L.
"""

PROPANE_KWH_PER_LITRE = 7.03
"""Propane: 25,3 MJ/L higher heating value, ÷ 3,6 = 7,03 kWh/L.

Natural Resources Canada's conversion factor.

**This is the number that makes propane comparisons go wrong.** A litre of
propane carries barely two thirds of a litre of oil (10,61 kWh), so a propane
price that looks a fifth cheaper per litre is materially *more* expensive per
unit of heat. Litres of different fuels are not comparable quantities and
nothing but the energy content makes them so.
"""

GAS_KWH_PER_CUBIC_METRE = 10.42
"""Natural gas: 37.5 MJ/m³ higher heating value, ÷ 3.6 = 10.42 kWh/m³.

Énergir bills in cubic metres and converts using a measured heating value that
varies slightly with the gas delivered. 37.5 MJ/m³ is the conventional figure;
a bill showing gigajoules is the authority for a given month.
"""

# --------------------------------------------------------------------------
# Efficiency
# --------------------------------------------------------------------------

TYPICAL_EFFICIENCY = {
    "oil furnace": 0.85,
    "gas furnace, condensing": 0.95,
    "gas furnace, non-condensing": 0.80,
    "propane furnace, condensing": 0.95,
    "propane furnace, non-condensing": 0.80,
    "electric resistance": 1.00,
}
"""What fraction of the fuel's energy reaches the house.

Nameplate figures for equipment in good repair. A real installation is worse:
duct losses, cycling losses and a chimney all take their share. These are
optimistic for combustion and exactly right for resistance, which flatters
combustion in every comparison below.
"""


class FuelError(ValueError):
    """Raised when a price cannot be converted into cost per useful kWh."""


@dataclass(frozen=True, slots=True)
class FuelPrice:
    """A posted price for a combustion fuel, and what it is per unit of energy."""

    name: str
    price_per_unit: float
    unit: str
    kwh_per_unit: float
    as_of: date
    source: str

    def cost_per_useful_kwh(self, efficiency: float) -> float:
        """Dollars per kilowatt-hour of heat actually delivered indoors."""

        if not 0 < efficiency <= 1:
            raise FuelError(
                "a combustion efficiency must be above 0 and at most 1; "
                "only a heat pump exceeds 1, and it burns nothing"
            )
        return self.price_per_unit / self.kwh_per_unit / efficiency


HEATING_OIL_SAGUENAY = FuelPrice(
    name="Mazout léger, Saguenay–Lac-Saint-Jean",
    price_per_unit=2.0580,
    unit="L",
    kwh_per_unit=OIL_KWH_PER_LITRE,
    as_of=date(2026, 8, 17),
    source=(
        "Régie de l'énergie du Québec, Relevé hebdomadaire des prix du mazout léger, "
        "semaine du 17 août 2026, région 02 Saguenay–Lac-Saint-Jean, "
        "moyenne de la saison en cours, 205,80 ¢/L avant escompte"
    ),
)
"""205,80 ¢/L, the current-season regional average.

A season average rather than the latest week, because heating happens over a
season. The most recent weekly figure in the same table was 210,07 ¢/L and the
provincial weighted average 207,60 ¢/L, so this is not a favourable pick.

**Before discount.** Retail customers commonly negotiate a few cents off, which
moves the delivered price down but nowhere near enough to change the ranking.
"""

NATURAL_GAS_ENERGIR = FuelPrice(
    name="Gaz naturel, Énergir tarif D1",
    price_per_unit=0.59983,
    unit="m³",
    kwh_per_unit=GAS_KWH_PER_CUBIC_METRE,
    as_of=date(2024, 12, 1),
    source=(
        "Énergir, Conditions de service et Tarif au 1er décembre 2024: "
        "distribution 34,015 ¢/m³ (first 30 m³/day, art. 14.2.2.2) + transport "
        "2,833 ¢/m³ (art. 12.1.2.1.1) + équilibrage 5,122 ¢/m³ (art. 13.1.2.1) + "
        "fourniture 9,814 ¢/m³ (art. 11.1.2.1) + SPEDE 8,199 ¢/m³ (art. 15.1.2.1)"
    ),
)
"""59,983 ¢/m³ delivered, being the sum of five separately published components.

**This is the least trustworthy number in the file, and it is the volatile one.**
Two reasons:

- the supply component is adjusted *monthly*. It was 9,814 ¢/m³ in the retrieved
  document and Énergir published 15,611 ¢/m³ for June 2026 — a change larger
  than the whole SPEDE charge;
- the retrieved tariff is the December 2024 edition; a December 2025 edition
  exists and was not obtained.

Treat this as a structure with a stale supply price. Énergir publishes the
current components monthly, and a recent bill is better than either.

It also excludes the fixed charge of 67,948 ¢ per meter per day, which is a
subscription rather than a price of heat — the same reasoning that keeps the
electricity access charge out of `marginal_cost`.
"""


def propane_price(
    price_per_litre: float,
    *,
    as_of: date,
    supplier: str,
) -> FuelPrice:
    """Build a propane price from an invoice. There is no default, deliberately.

    Every other price in this module has a published source that can be cited
    and re-checked. **Propane does not.** The Régie de l'énergie surveys light
    heating oil weekly by administrative region; Statistics Canada publishes
    gasoline and fuel oil. Neither publishes a residential propane price for
    Québec.

    What propane costs depends on the contract: annual volume, tank rental,
    whether the price is fixed or floating, seasonal pre-buy, and — for a
    cooperative — member pricing and any patronage rebate. Two houses on the
    same street can pay prices that differ by a third, and neither is wrong.

    So the price must come from an invoice, and the invoice's date and supplier
    travel with it. A baked-in default would look like a citation and be a
    guess.
    """

    if price_per_litre <= 0:
        raise FuelError("a propane price per litre must be positive")

    return FuelPrice(
        name=f"Propane, {supplier}",
        price_per_unit=price_per_litre,
        unit="L",
        kwh_per_unit=PROPANE_KWH_PER_LITRE,
        as_of=as_of,
        source=f"invoice from {supplier}, {as_of.isoformat()}, before rebate",
    )


@dataclass(frozen=True, slots=True)
class HeatingOption:
    """One way of putting a kilowatt-hour of heat into the house."""

    name: str
    cost_per_useful_kwh: float
    basis: str

    def annual_cost(self, useful_kwh: float) -> float:
        if useful_kwh < 0:
            raise FuelError("heat delivered cannot be negative")
        return useful_kwh * self.cost_per_useful_kwh


def heat_pump_option(cop: float, *, price_per_kwh: float | None = None) -> HeatingOption:
    """A heat pump at a stated coefficient of performance.

    COP is not a constant. It falls as the source gets colder, so a seasonal
    average is the honest input and a nameplate figure at rating conditions is
    not. This function will not choose one: the caller states it and the result
    says which was used.
    """

    if cop <= 0:
        raise FuelError("a coefficient of performance must be positive")

    price = RATE_D.second_tier_price if price_per_kwh is None else price_per_kwh
    if price < 0:
        raise TariffError("a price per kWh cannot be negative")

    return HeatingOption(
        name=f"Heat pump, COP {cop:g}",
        cost_per_useful_kwh=price / cop,
        basis=f"{price * 100:.3f} ¢/kWh ÷ COP {cop:g}",
    )


def resistance_option(*, price_per_kwh: float | None = None) -> HeatingOption:
    """Electric resistance: every kilowatt-hour in becomes one of heat."""

    price = RATE_D.second_tier_price if price_per_kwh is None else price_per_kwh
    return HeatingOption(
        name="Electric resistance",
        cost_per_useful_kwh=price,
        basis=f"{price * 100:.3f} ¢/kWh at 100 %",
    )


def fuel_option(fuel: FuelPrice, equipment: str) -> HeatingOption:
    """A combustion fuel burnt in named equipment."""

    if equipment not in TYPICAL_EFFICIENCY:
        raise FuelError(
            f"no typical efficiency for {equipment!r}; "
            f"known: {', '.join(sorted(TYPICAL_EFFICIENCY))}"
        )
    efficiency = TYPICAL_EFFICIENCY[equipment]
    return HeatingOption(
        name=f"{fuel.name} ({equipment})",
        cost_per_useful_kwh=fuel.cost_per_useful_kwh(efficiency),
        basis=(
            f"{fuel.price_per_unit:.4f} $/{fuel.unit} ÷ "
            f"{fuel.kwh_per_unit:g} kWh/{fuel.unit} ÷ {efficiency:.0%}"
        ),
    )


def ranked(options: tuple[HeatingOption, ...]) -> tuple[HeatingOption, ...]:
    """Cheapest first. Ranking is the whole point of putting them on one scale."""

    return tuple(sorted(options, key=lambda option: option.cost_per_useful_kwh))
