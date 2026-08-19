# The Dossier

**Status:** Implemented
**Scope:** the package an engineer receives
**Tool:** [`tools/geopilot_dossier.py`](../tools/geopilot_dossier.py)

Everything else in GeoPilot serves the person operating it. This serves the
person who has to **stamp a recommendation**, and that is a different job with a
different requirement: not "show me the numbers" but "show me what the numbers
are worth".

```bash
python3 tools/geopilot_dossier.py \
    --database /var/lib/geopilot/geopilot.sqlite3 \
    --into ~/dossier-2027-05 \
    --since 2026-10-01 --until 2027-05-01 \
    --delta sensor_loop_in:sensor_loop_out \
    --prepared-for "Hubert Langevin, ing."
```

```text
dossier-2027-05/
├── README.md          the method statement
├── coverage.csv       per sensor: count, span, largest gap
├── provenance.csv     every correction ever in effect, and from when
├── series/
│   ├── sensor_loop_in.csv
│   └── sensor_loop_out.csv
└── deltas/
    └── sensor_loop_in-minus-sensor_loop_out.csv
```

## The README is the deliverable

The CSVs are the easy part. The centrepiece is the generated `README.md`, and
in particular its **Limits** section, which the first page links to before any
figure appears. A dossier that omits its own limits is worse than no dossier: it
invites a conclusion it cannot support.

Four limits are stated every time, because all four are true every time:

| Limit | Why it is on the page |
| --- | --- |
| **absolute ±0.5 °C, differences much better** | The probes are calibrated to agree *with each other*, which is the right target for a loop delta and is not the same as being absolutely right. An entering-water temperature quoted from this data carries the full ±0.5 °C; a delta does not |
| **no flow, so no heat transfer** | A temperature difference is not a rate of heat. Nothing here converts to kW or to a coefficient of performance, and an engineer expecting one has to be told before they look |
| **it records the configuration, not the truth** | A probe clamped to the return but configured as the supply reads faithfully as the supply. Provenance proves nothing changed unnoticed; it cannot prove the file matched the plumbing |
| **gaps are absences, not zeros** | Statistics are computed over what exists. A mean spanning a three-day hole is a mean of what was seen |

Two more appear conditionally, and are the reason the tool exists rather than a
shell script:

- **corrections that changed mid-recording** are named and dated on the page,
  with the before-and-after value. This is the one thing that would silently
  invalidate a comparison across a season;
- **no calibration history at all** — for a recording that predates the
  provenance journal — is stated as plainly: treat every figure as
  uncalibrated, comparisons within one sensor remain valid, comparisons between
  two do not.

## What it deliberately does not contain

It reads the **measurement database only**, never the configuration. So the
package carries sensor ids, readings and calibration history, and no address, no
equipment serial numbers, no occupancy data and nothing from
`docs/hardware/SITE.md`.

That is a decision, not an oversight: a deliverable is a thing that gets
forwarded. Anything more is added by hand, by somebody who has decided to add
it. A test asserts the exclusion rather than trusting it.

## Details that matter

- **raw readings are not exported.** Every series is bucketed — hourly by
  default — with the count, minimum, maximum and mean of what fell inside. A
  year of one-minute data is millions of rows and nobody opens it; the README
  says the raw database can be supplied on request, because it can;
- **`count` travels with every bucket**, so a bucket that held two readings is
  visibly different from one that held sixty;
- **the pair count travels with every delta.** A delta computed from 40 pairs
  out of 1,440 readings is a different claim from one computed from 1,438;
- **values are rounded to six decimals on the way out.** Subtracting two floats
  produces `2.8000000000000003`, and writing that claims sixteen significant
  digits from a probe with 0.0625 °C resolution. The stored measurements are
  untouched;
- **it refuses to write into an occupied directory** without `--force`. A
  dossier is dated evidence, and silently mixing two of them is how a reader
  ends up with January's README beside March's CSVs.

## Limits of the tool itself

- **it cannot describe equipment it does not measure.** The heat pump's own
  model, age and service history belong in the covering note, not here;
- **it has no opinion.** It states coverage and corrections; it does not
  conclude that the field is undersized or that the coax is fouled. That is the
  engineer's job and the whole reason the package exists;
- **it has never been run against a full season.** Everything above is exercised
  against synthetic recordings in CI, and the first real one will be in
  May 2027.
