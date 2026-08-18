# Energy Cost

**Status:** Implemented
**Scope:** converting recorded kilowatt-hours into Québec dollars

A recording in kilowatt-hours cannot settle a capital decision. The dossier's
question — what fraction of annual heating energy passes through the electric
stage, and is a replacement worth its price — is answered in dollars, and the
conversion is not one number.

## The rates

Transcribed from Hydro-Québec, *Tarifs d'électricité*, in force **1 April
2026**, ISBN 978-2-555-03533-1 (PDF).

**Rate D**, article 2.5:

| | |
| --- | --- |
| Access charge | 46,154 ¢ per day in the period |
| First tier | 7,065 ¢/kWh, up to 40 kWh × the number of days |
| Beyond | 11,142 ¢/kWh |

**Rate DT**, dual energy, article 2.34, recorded for a warning rather than for
use — see below.

| | |
| --- | --- |
| Access charge | 46,154 ¢ per day |
| At or above −12 °C (−15 °C by zone) | 5,131 ¢/kWh |
| Below it | 30,001 ¢/kWh |
| Demand | 7,266 $/kW past the billing threshold |

### Getting these right took three attempts

Worth recording, because it is a lesson about sourcing rather than about
tariffs. A web search returned 6.76 ¢ / 10.52 ¢ / 0.4641 $ — wrong. Decoding
the official PDF by hand through its font tables returned 7.082 ¢ / 11.163 ¢ /
0.68126 $ and a 60 kWh threshold — also wrong, because merged font encodings
collided and quietly changed digits. Only `pdftotext` on the official document
agreed with itself, and it disagreed with both.

Three sources, three answers, and two of them looked entirely plausible. The
figures above come from the document.

## The trap: never use a blended average for an appliance

Rate D is tiered **per day**. Dividing a bill by its kilowatt-hours gives an
average somewhere between the two prices, and that average is the wrong number
for every equipment question.

A heat pump in a house that already passes 40 kWh/day in winter consumes **no
cheap kilowatt-hours**. Its kilowatt-hours are the last ones of the day, every
one billed at the second tier. Costing them at a blended average understates
what the machine costs to run, and therefore **understates what efficiency is
worth** — the exact error that makes a replacement look less attractive than it
is.

On this installation's own consumption, from `SITE.md`:

| Season | Heating kWh | At the blended average | At the marginal tier | Understated by |
| --- | ---: | ---: | ---: | ---: |
| 2024-2025 | 37,092 | 3,867 $ | **4,133 $** | 266 $ |
| 2025-2026 | 46,246 | 4,909 $ | **5,153 $** | 244 $ |

Roughly a quarter of a thousand dollars a year, in the direction that argues
against spending money.

So `marginal_cost` is the function for equipment, and `bill` exists only to
reconcile against an actual invoice.

## What this is worth, per point of resistance heat

At the marginal tier, if a COP 3 machine carried what the electric second stage
carries today:

| Share through resistance | kWh | Saved per year |
| ---: | ---: | ---: |
| 10 % | 4,625 | 344 $ |
| 20 % | 9,249 | 687 $ |
| 30 % | 13,874 | 1,031 $ |

**These are illustrations of an arithmetic, not a forecast.** The share is
unknown — measuring it is the whole reason the meter outranks the temperature
sensors — and COP 3 is an assumption about a machine nobody has chosen. What
the table does show is the shape: the answer scales linearly with the share, so
the measurement is the thing that decides, and a year of it costs one meter.

## Which rate applies is a question, not an assumption

**Rate D *is* the standard residential rate.** A Québec home that has not
specifically signed up for dual energy or Flex D is on it; there is no separate
"normal" rate underneath.

But a multi-unit building's mechanical room is often metered separately, and a
separate meter serving common equipment is not automatically domestic. If it is
on **Rate G**, article 3.2, the structure is the reverse of Rate D:

| | Rate D | Rate G |
| --- | --- | --- |
| Access | 46,154 ¢/day | 15,426 $/month |
| Tiers | cheap first, 40 kWh/day | **expensive first**, 15 090 kWh/month |
| First tier | 7,065 ¢ | 12,388 ¢ |
| Beyond | 11,142 ¢ | **9,534 ¢** |
| Demand | none | 22,071 $/kW past 50 kW |

For a large heating load the marginal price on Rate G is **9,534 ¢ — below Rate
D's 11,142 ¢**. Rate G also carries a demand charge on the highest power drawn,
under which a machine that draws hard for fifteen minutes costs the same as one
that draws hard all month.

**Read the rate code off the bill for the meter the heat pump is actually on.**
Every dollar figure in this document assumes Rate D, and the answer moves by
about 14 % at the margin if that assumption is wrong.

## Rate DT is not the saving it looks like

Mild-weather energy at 5,131 ¢ is less than half of Rate D's second tier. It is
still not available to this installation as it stands.

Below −12 °C every kilowatt-hour costs **30,001 ¢**, nearly three times Rate D's
second tier. The rate assumes the cold hours are carried by a *fossil* backup
that stops drawing electricity. A house that answers deep cold with an
**electric** second stage would meet that price with its largest load of the
year running.

Whether a replacement should be designed to qualify is an engineering and fuel
question, not a software one.

## The other fuels, on one scale

Comparing heating options means comparing **one kilowatt-hour of heat inside
the house**. Getting there from a posted price takes two conversions, and both
are where comparisons usually go wrong: energy content, then efficiency.

| Option | ¢ per useful kWh | On 46 246 kWh |
| --- | ---: | ---: |
| Heat pump, COP 3 | **3.71** | 1 718 $ |
| Heat pump, COP 2 | 5.57 | 2 576 $ |
| Natural gas, condensing¹ | 6.06 | 2 802 $ |
| Natural gas, non-condensing¹ | 7.20 | 3 328 $ |
| Electric resistance | 11.14 | 5 153 $ |
| Heating oil | 22.82 | 10 553 $ |
| **Propane, condensing, at 2,15 $/L** | **32.19** | **14 888 $** |
| **Propane, condensing, at 2,55 $/L** | **38.18** | **17 658 $** |

¹ Natural gas is listed for completeness and is not available at this address.

Propane is the **most expensive** option on the list: nine times a COP 3 heat
pump, three times electric resistance, and half again more than oil.

### Propane has no published price, and that is a design constraint

Every other price here has a source that can be cited and re-checked. **Propane
does not.** The Régie de l'énergie surveys light heating oil weekly by
administrative region; Statistics Canada publishes gasoline and fuel oil.
Neither publishes a residential propane price for Québec.

What propane costs depends on the contract — annual volume, tank rental, fixed
or floating price, seasonal pre-buy, and for a cooperative, member pricing and
any patronage rebate. Two houses on the same street can pay prices a third
apart and neither is wrong.

So `propane_price` **has no default and requires one**, and it carries the
supplier and the invoice date with it. A baked-in figure would look like a
citation and be a guess. The 2,15–2,55 $/L used above is a regional estimate
from a secondary source with an interest in the answer; **replace it with a
Nutrinor invoice** before it decides anything.

### The litre trap

A litre of propane carries **25,3 MJ** against light oil's **38,2 MJ** — barely
two thirds. Propane priced a fifth below oil per litre is still materially more
expensive per unit of heat, and comparing the two by the litre is comparing
different quantities. This is the single most common error in fuel comparisons
and the module refuses to make it: every price is converted through its own
energy content before anything is ranked.

### Where those come from

**Heating oil: 205,80 ¢/L.** Régie de l'énergie du Québec, weekly survey, week
of 17 August 2026, region 02 Saguenay–Lac-Saint-Jean, current-season average,
before discount. A season average rather than the latest week, because heating
happens over a season — the most recent weekly figure was 210,07 ¢/L and the
provincial weighted average 207,60 ¢/L, so this is not a favourable pick.
Energy content 38,2 MJ/L = 10,61 kWh/L, at 85 %.

**Natural gas: 59,983 ¢/m³**, the sum of five separately published components
from Énergir's *Conditions de service et Tarif* — distribution 34,015 ¢
(art. 14.2.2.2), transport 2,833 ¢ (12.1.2.1.1), load balancing 5,122 ¢
(13.1.2.1), supply 9,814 ¢ (11.1.2.1) and SPEDE 8,199 ¢ (15.1.2.1). Energy
content 37,5 MJ/m³ = 10,42 kWh/m³.

**The gas figure is the least trustworthy number in this project.** The supply
component is adjusted *monthly* — Énergir published 15,611 ¢/m³ for June 2026
against the 9,814 ¢ in the retrieved document, a change larger than the entire
carbon charge — and the edition obtained was December 2024 where a December
2025 edition exists. Treat it as a correct *structure* with a stale supply
price, and use a recent bill in preference.

The efficiencies are nameplate figures with no duct, cycling or chimney losses,
which **flatters combustion** against the heat pump in every row above.

### Two things this settles

**No fossil backup makes Rate DT worth having here.** The dual-energy rate's
cheap tier only pays if the cold hours are carried by a fossil fuel, and both
fuels actually available cost more per unit of heat than Rate D charges for
resistance electricity — oil twice over, propane three times. The rate is a
saving on paper that the fuel undoes, and with propane it undoes it twice.

**Propane is a poor backup on cost alone**, before any question of the equipment
to burn it in. If a replacement design proposes a propane stage, the case for it
has to be made on capacity or resilience, not on running cost.

**Natural gas is not available at this address** — the network here is propane.
It stays in the table only as a reference point, and as a reminder that a
*transmission* pipeline crossing a municipality is not a *distribution* service
at a street address.

## Using it

```bash
python3 tools/geopilot_report.py --database geopilot.sqlite3 \
    --sensor sensor_heat_pump_energy --cost
```

```text
consumed: 3,738.8 kWh  (a cumulative counter, max minus min)
at the Tarif D second tier, 11.142 c/kWh:
  416.58 $
```

It refuses anything but kWh. A sensor in watts is a **rate**, not an amount,
and converting one to the other needs a duration this function does not have.
It also refuses a counter that went backwards, which is a meter reset rather
than negative consumption.

## Rates go stale on a known date

Hydro-Québec revises on 1 April every year. A rate compiled into software goes
wrong silently, so each schedule carries its effective date and `stale_after`
reports when it has been superseded — the report prints a warning rather than
quietly costing this winter at last year's prices.

**Re-read the document each April.** Nothing here fetches rates at runtime, and
that is deliberate: a number that changes under you without a commit is worse
than one that is visibly old.

## What it does not do

**It does not model the whole bill.** No credits, no taxes, no bi-monthly
billing periods, no Flex D, no winter credit options. `bill` is a two-tier
arithmetic for reconciliation, not an invoice.

**It does not know what your house consumes.** The blended figures above use
`SITE.md`'s recorded totals; the marginal calculation needs no such assumption,
which is one more reason to prefer it.

**It gives no financial advice.** It converts kilowatt-hours to dollars at a
published price. What that means for a purchase is between you and your
engineer.

## Testing

`tests/test_tariff.py`.

Covered: the published prices carried exactly; the threshold scaling with days
rather than per bill; the tiers splitting correctly; a blended average provably
understating the marginal cost by more than 15 % at this installation's
consumption; the access charge growing with a longer period even as energy gets
cheaper, so that "longer is cheaper" is not mistaken for a rule; negative
consumption, zero-day periods and empty blends all refused; and the April
staleness boundary.
