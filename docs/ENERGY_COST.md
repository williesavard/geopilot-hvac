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
