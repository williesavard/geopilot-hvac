# Reporting

**Status:** Implemented
**Scope:** reading a recorded database, read-only

Recording without reading is a hard drive with a hobby. This is the part that
answers the question the recording exists to answer.

The first question is not "how warm was the loop". It is **"is it still
recording"**, and [Deployment](DEPLOYMENT.md) already said why:

> A count that stops rising is the failure that matters, and no alert will tell
> you. Check it deliberately during the first week.

This is that check.

## Running it

```bash
# is it still recording, and where are the holes?
python3 tools/geopilot_report.py --database /var/lib/geopilot/geopilot.sqlite3
```

```text
sensor                           unit       count         span  largest gap
sensor_loop_in                   degC     129,600      90d 0h        1m 0s
sensor_loop_out                  degC     129,600      90d 0h        1m 0s
sensor_zone_1                    state    129,341      90d 0h       3d 04h
```

That third row is the whole point. The count looks healthy. The gap says the
zone panel was unreachable for three days in February, and nothing else in the
system would have told you.

```bash
# what did one sensor do over a window?
python3 tools/geopilot_report.py --database geopilot.sqlite3 \
    --sensor sensor_loop_in --since 2026-01-01 --until 2026-02-01
```

A `state` sensor also reports its duty cycle.

```bash
# the curve: daily averages, aligned to the local wall clock
python3 tools/geopilot_report.py --database geopilot.sqlite3 \
    --sensor sensor_loop_in --bucket 1d
```

```text
starts at                    count        min        max       mean
2026-01-12T00:00:00-05:00      288      0.221       3.51       1.91
2026-01-13T00:00:00-05:00      288      0.041       3.33       1.73
2026-01-14T00:00:00-05:00      168     -0.139       3.15       1.74
2026-01-15T00:00:00-05:00      288     -0.319       2.97       1.37
```

Add `--csv` to redirect that into a file and plot it. Intervals take a unit —
`15m`, `1h`, `6h`, `1d`, `7d`. A bare `--bucket 60` is refused, because it could
mean a minute or an hour and guessing wrong would silently produce a chart at
the wrong resolution.

For a `state` sensor the mean **is** the duty cycle over that interval, since
the values are 0 and 1. `--bucket 1d` on a zone call is a day-by-day picture of
how hard that zone was working.

## The loop delta

```bash
python3 tools/geopilot_report.py --database geopilot.sqlite3 \
    --sensor sensor_loop_in --minus sensor_loop_out --bucket 1d
```

```text
starts at                    count        min        max       mean
2026-01-12T00:00:00-05:00      288       0.15      3.325      1.416
2026-01-13T00:00:00-05:00      288       0.15      2.965      1.266
2026-01-14T00:00:00-05:00      288       0.15      2.605      1.116
2026-01-15T00:00:00-05:00      288       0.15      2.245     0.9657
```

Without `--bucket` it prints one summary over the whole window.

### Two readings are never taken at the same instant

Each Modbus read is its own transaction on a half-duplex segment, so loop-in and
loop-out arrive seconds apart. An exact-timestamp join would find nothing at all.

So readings are **paired**: each observation of one sensor is matched with the
nearest observation of the other, if one falls within `--tolerance` (30 seconds
by default). The pairing is **one to one** — once a reading is used it is
consumed. If one sensor is sampled five times as often as the other, the extras
go unpaired rather than reusing a stale partner five times over, and the unpaired
counts are printed:

```text
unpaired: 41 of sensor_loop_in, 2 of sensor_loop_out
```

That line is part of the result, not a diagnostic. A delta computed from 40
pairs out of 1,440 readings is a different claim from one computed from 1,438.

**Keep the tolerance under half the polling interval.** The pairing walks both
series forward once and never backtracks, which is safe exactly when no two
readings of one sensor can reach the same partner. The narrow default is what
guarantees a pair comes from a single acquisition cycle.

### The delta is computed per pair, then aggregated

Never as one sensor's bucket mean minus the other's. Those agree for the mean
and **do not agree for the extremes**: the smallest difference is not the
difference of the smallest readings. A bucket built the cheap way would report a
minimum that never occurred, and it would look entirely plausible.

Both sensors must carry the same unit. Comparing a temperature against a zone
call is refused rather than subtracted.

### Filtering by a state sensor

An unfiltered mean delta **mixes running and idle time**, and that is not a
detail. Here are four days of the same loop, first unfiltered:

```text
starts at                    count        min        max       mean
2026-01-12T00:00:00-05:00      288       0.12      3.295      1.412
2026-01-13T00:00:00-05:00      288       0.12       2.95       1.49
2026-01-14T00:00:00-05:00      288       0.12      2.605      1.509
2026-01-15T00:00:00-05:00      288       0.12       2.26      1.467
```

Flat. Nothing to say. Now the same four days, restricted to the moments the
compressor was actually running:

```bash
python3 tools/geopilot_report.py --database geopilot.sqlite3 \
    --sensor sensor_loop_in --minus sensor_loop_out \
    --while sensor_compressor --bucket 1d
```

```text
starts at                    count        min        max       mean
2026-01-12T00:00:00-05:00      120      3.146      3.295      3.221
2026-01-13T00:00:00-05:00      144      2.772       2.95      2.861
2026-01-14T00:00:00-05:00      168      2.396      2.605      2.501
2026-01-15T00:00:00-05:00      192      2.021       2.26      2.141
```

A clean decline, and the `count` column shows what was hiding it: the equipment
ran longer each day, so the unfiltered mean was pulled up by more running hours
at the same time as it was pulled down by a weaker delta. The two cancelled.

`--while` works on plain summaries and single-sensor buckets too — the average
loop temperature *while the compressor was running*, rather than an average
diluted by every hour it was not.

### What the gate is allowed to assume

The state sensor is sampled on the same cycle as everything else, so its
readings do not line up exactly with the temperatures either. Each observation
is matched to the nearest state reading within `--tolerance`, and:

- **a state reading is reused, not consumed.** A state is a level, and the same
  observation legitimately describes every moment near it. Reuse cannot inflate
  anything, because the gate contributes no value — it only answers yes or no.
  This is the opposite of the delta pairing, deliberately;
- **it will not reach past the tolerance.** Beyond that the signal is
  unobserved, and an unobserved state is not an asserted one.

Only a sensor recorded in the `state` unit can be a gate. Naming a temperature
is refused, and so is naming a sensor with no observations at all — a typo must
not read as an installation that never ran.

### What the gate costs, and what it still hides

Gating walks the rows in Python instead of aggregating in SQL. Plain ungated
buckets stay in SQL, so the cost is paid only when a gate is asked for.

**A gated bucket that is absent is ambiguous.** The equipment being off all
afternoon and the recorder being off all afternoon produce the same missing
bucket. The neighbouring `count` values and an ungated `coverage` run are what
tell them apart.

**A gate says the signal was asserted, not that the machine was healthy.** If
the compressor call is closed while the compressor is locked out, the gate lets
those moments through. Nothing here can tell the difference.

| Exit code | Meaning |
| --- | --- |
| 0 | a report was produced |
| 1 | bad arguments, missing database, or mixed units |
| 2 | the query succeeded and found nothing |

Exit 2 exists so a cron job can distinguish "the recorder is empty" from "the
command was wrong". They call for different responses.

## Buckets are aligned to the local wall clock

By default a bucket boundary falls where the clock says it does *at the place
the readings were taken*, using the UTC offset stored with every measurement.

This is not cosmetic. In Quebec, a "day" aligned to UTC runs from 19:00 to 19:00
and splits every evening in half — so a daily heating average would mix the cold
end of one night with the warm end of the next. The same eight readings, taken
between 22:00 and 05:00 local, land in two days locally and in one day under
UTC. The local answer is the true one.

Because each measurement carries the offset that was in effect *when it was
taken*, this stays right across a daylight-saving change: a spring day simply
holds 23 hours of samples and a fall day 25. The one blemish is the label. A
bucket that spans the transition is labelled with the standard-time offset,
which is an hour off for two buckets a year. Pass `--utc` to align to UTC
instead.

An interval must divide evenly into a day or be a whole number of days. Fifteen
minutes, six hours and a week all qualify; seven hours does not, and is refused
rather than producing buckets that creep further from midnight every day.

Observations stamped before 1970 are refused outright. SQLite truncates integer
division toward zero, so a negative instant lands in the wrong bucket and the
interval straddling the epoch comes out double width. This is not a hypothetical
concern: a Raspberry Pi with no real-time clock and no network stamps its first
readings at the epoch, and with a western offset those go negative as soon as
they are aligned to local time. Refusing them says something true; bucketing
them would not.

## What a bucket does not tell you

**An absent bucket is a gap.** Nothing is synthesized to fill it, for the same
reason the timer does not fire missed cycles on boot: a gap in the data is
honest, and an invented point is not. A plot with a hole in it is telling the
truth.

**A present bucket can still be incomplete**, and this one bites. In the table
above, 14 January holds 168 samples where the others hold 288 — a ten-hour
outage. The mean is still printed, and it is a mean over the fourteen hours that
survived, weighted toward whatever time of day those were. **Read the count
column before trusting a mean.** A day missing its coldest hours will look
warmer, and nothing in the number itself says so.

## Two deliberate departures

Every other consumer in this project goes through `MeasurementHistorian`.
Reporting does not, for two reasons stated here so the inconsistency is not
mistaken for an oversight.

**It queries SQL directly.** An average over ten million rows cannot travel
through a protocol that returns tuples of `Measurement` objects. Aggregation
belongs in the database, and the historian protocol has no aggregate on it. It
should not grow one for the sake of uniformity.

**It opens its own connection from a path, read-only.** WAL journalling allows
concurrent readers, so a report can be produced *while the system is recording* —
which is exactly when you want one. `mode=ro` means the report cannot damage the
year of data it is examining, even through a bug.

## What it will not do

**It does not interpret.** A duty cycle of 82% is a number. Whether that means
the heat pump is undersized is a conversation with an engineer, and this tool
takes no position in it.

**It does not correct for uneven sampling.** A duty cycle here is a ratio of
**samples**, not of time. With a one-minute timer the two agree. If sampling
were uneven, they would not, and the difference is left visible rather than
silently smoothed — a corrected number would hide the uneven sampling, which is
itself a fault worth seeing.

**It refuses mixed units.** If a sensor was recorded in `degC` and later in
`degF`, both `summarize` and `bucketed` raise rather than averaging them. A mean
of 20 and 68 is a number with no meaning. Coverage still lists both, as separate
rows, which is how you notice.

**It compares two sensors, not three.** A delta has exactly two ends. A third
sensor can only ever be a `state` gate, never another term.

**It conditions on one gate, and only on assertion.** There is no way to ask for
"while zone 1 called *and* the outdoor temperature was below −10", nor for
"while the compressor was *off*". Both are ordinary extensions; neither is here.

**Its largest gap and its pairing are computed in Python** rather than in SQL.
The pairing streams both series and holds two rows at a time, so it does not
grow with the window; the gap scan reads a sensor's timestamps into memory. Both
are fine for a year of one-minute samples and would not be for a decade of them.

## Testing

`tests/test_reporting.py` and `tests/test_report_tool.py`.

Every test writes through the real historian rather than inserting SQL, so the
reports are proven against the schema the recorder actually produces. Covered:
the read-only connection genuinely refusing a write, a missing database not
being created, gap detection across a three-day hole, half-open windows, empty
windows reporting nothing rather than zero, mixed-unit refusal, duty cycle
including the zero case, and a report produced against a database that is still
being written.

For buckets: aggregation and ordering, a bucket starting at its interval rather
than at its first sample, an empty interval staying absent, a state bucket's
mean equalling its duty cycle, interval validation in both directions, and the
local-versus-UTC pair — the same eight evening readings falling into two local
days and one UTC day, which is the case that justifies the default.

For deltas: pairing readings taken seconds apart, the sign following the order
asked for, the tolerance excluding and including the same pair, a partner being
consumed rather than reused, the nearest of two candidates winning, unpaired
counts, refusing mismatched units and a sensor against itself, and the case that
justifies pairwise aggregation — two pairs whose deltas are 1.0 and 2.0, where
subtracting the bucket minima would have claimed a minimum of 2.0.

For gating: the same four readings giving a mean of 1.55 unfiltered and 3.0
filtered, excluded counts kept separate from unpaired ones, a state reading
being reused where a delta partner would have been consumed, the gate refusing
to reach past its tolerance, and the three refusals — a non-state sensor, an
unknown sensor, and a sensor absent from the window.
