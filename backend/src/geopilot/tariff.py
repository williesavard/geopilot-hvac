"""What a kilowatt-hour costs, in Québec, on paper.

A recording in kilowatt-hours cannot settle a capital decision on its own.
The dossier's question — what fraction of annual heating energy passes through
the electric stage, and is a replacement worth its price — is answered in
dollars, and the conversion is not a single number.

Every figure here is transcribed from Hydro-Québec's own rate document, cited
below. Nothing is inferred, averaged from a news article, or carried over from
a previous year.

## The trap this module exists to avoid

Rate D is tiered **per day**: the first 40 kWh of each day are cheap and the
rest is not. Dividing an annual bill by annual kilowatt-hours produces a
blended average somewhere between the two prices — and that average is the
wrong number for every appliance question.

A heat pump in a house that already passes 40 kWh/day in winter does not
consume any cheap kilowatt-hours. Its kilowatt-hours are the *last* ones of the
day, every one of them billed at the second tier. Costing them at a blended
average **understates what the equipment costs to run, and therefore
understates what efficiency is worth** — which is precisely the error that
makes a replacement look less attractive than it is.

So `marginal_cost` is the function for equipment questions, and `bill` is only
for reconciling against an actual invoice.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

SOURCE = (
    "Hydro-Québec, Tarifs d'électricité, en vigueur le 1er avril 2026, "
    "ISBN 978-2-555-03533-1 (PDF), articles 2.5 and 2.34"
)
"""Where every number below was read from.

Transcribed from the official PDF with pdftotext, not from a summary. Both a
web search and a hand-decode of the same PDF's font tables produced different
figures, and all of them were wrong; the document is the only source that held
up.
"""

EFFECTIVE_FROM = date(2026, 4, 1)
"""Hydro-Québec rates change on 1 April every year.

A rate constant compiled into software goes stale silently, on a known date.
`stale_after` exists so a report can say so instead of quietly costing this
winter at last year's prices.
"""


class TariffError(ValueError):
    """Raised when a cost cannot be computed from what was given."""


@dataclass(frozen=True, slots=True)
class TieredRate:
    """A rate with a daily access charge and two energy tiers."""

    name: str
    access_per_day: float
    """Dollars per day in the consumption period, whether or not anything runs."""

    first_tier_price: float
    """Dollars per kWh, up to the daily threshold."""

    first_tier_kwh_per_day: float
    """The threshold, per day of the period — not per month."""

    second_tier_price: float
    """Dollars per kWh beyond it. The price an appliance actually pays."""

    effective_from: date
    source: str

    def bill(self, kwh: float, *, days: int) -> float:
        """The cost of a whole house's consumption over a period.

        Use this to reconcile against an invoice. Do **not** use it to cost a
        single appliance: the tiers belong to the meter, not to the machine.
        """

        if kwh < 0:
            raise TariffError("consumption cannot be negative")
        if days <= 0:
            raise TariffError("a consumption period must cover at least one day")

        threshold = self.first_tier_kwh_per_day * days
        cheap = min(kwh, threshold)
        dear = max(0.0, kwh - threshold)
        return self.access_per_day * days + cheap * self.first_tier_price + (
            dear * self.second_tier_price
        )

    def marginal_cost(self, kwh: float) -> float:
        """What an added load costs in a house already past the daily threshold.

        The honest number for equipment. A heat pump's kilowatt-hours are the
        last ones of the day, so they are billed at the second tier — all of
        them, not a blend.

        No access charge: the charge is paid whether the machine runs or not,
        so attributing it to the machine would overstate what turning the
        machine off would save.
        """

        if kwh < 0:
            raise TariffError("consumption cannot be negative")
        return kwh * self.second_tier_price

    def blended_price(self, kwh: float, *, days: int) -> float:
        """The average price per kWh a bill works out to.

        Provided to show what it is *not* good for. Comparing it against
        `second_tier_price` is the fastest way to see how much a blended
        average understates the cost of running one more machine.
        """

        if kwh <= 0:
            raise TariffError("a blended price needs some consumption to blend")
        return self.bill(kwh, days=days) / kwh

    def stale_after(self, on: date) -> bool:
        """Whether these prices have been superseded by an April revision."""

        april = date(on.year, 4, 1)
        latest = april if on >= april else date(on.year - 1, 4, 1)
        return latest > self.effective_from


RATE_D = TieredRate(
    name="Tarif D",
    access_per_day=0.46154,
    first_tier_price=0.07065,
    first_tier_kwh_per_day=40.0,
    second_tier_price=0.11142,
    effective_from=EFFECTIVE_FROM,
    source=SOURCE,
)
"""The standard residential rate, article 2.5.

46,154 ¢ per day, 7,065 ¢/kWh up to 40 kWh × days, 11,142 ¢/kWh beyond.
"""


@dataclass(frozen=True, slots=True)
class DualEnergyRate:
    """Rate DT, where the price depends on the outdoor temperature.

    Recorded for completeness and for a specific warning, not for use here.
    """

    name: str
    access_per_day: float
    mild_price: float
    cold_price: float
    threshold_celsius: float
    demand_price_per_kw: float
    effective_from: date
    source: str


RATE_DT = DualEnergyRate(
    name="Tarif DT",
    access_per_day=0.46154,
    mild_price=0.05131,
    cold_price=0.30001,
    threshold_celsius=-12.0,
    demand_price_per_kw=7.266,
    effective_from=EFFECTIVE_FROM,
    source=SOURCE,
)
"""Dual-energy, article 2.34. Mild energy is less than half the Rate D tier 2.

**And it is a trap for a house whose only backup is electric.** Below the
threshold — −12 °C or −15 °C by climate zone — every kilowatt-hour costs
30,001 ¢, nearly three times Rate D's second tier. The rate assumes the cold
hours are carried by a *fossil* backup that stops drawing electricity. A house
that answers deep cold with an electric second stage would meet that price with
its largest load of the year running.

Rate DT is therefore not a saving available to this installation as it stands.
Whether a replacement should be designed to qualify for it is an engineering
and fuel question, not a software one.
"""
