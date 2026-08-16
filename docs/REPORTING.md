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

For a page you can look at instead of a table you have to read, see
[Dashboard](DASHBOARD.md) — same numbers, same refusals, one HTML file.

## Runs: how long, and how often

A duty cycle says the compressor ran 46.5% of the time. It **cannot tell 22 long
cycles from 96 short ones**, and short cycling is a fault while long cycling is
not. Runs are what separate them.

```bash
python3 tools/geopilot_report.py --database geopilot.sqlite3 \
    --sensor sensor_compressor --runs
```

```text
runs   : sensor_compressor asserted
count  : 182
shortest: 7m 0s
longest : 39m 0s
mean    : 13m 42s
total   : 1d 17h

1 of these were cut by the window edge or a recording gap; their durations are
lower bounds
```

And per day, which is where a trend shows up:

```bash
python3 tools/geopilot_report.py --database geopilot.sqlite3 \
    --sensor sensor_compressor --runs --sense on --bucket 1d
```

```text
starts at                    count        min        max       mean
2026-01-12T00:00:00-05:00       16       2340       2340       2340
2026-01-13T00:00:00-05:00       26       1440       1680       1449
2026-01-14T00:00:00-05:00       44        780        780        780
2026-01-15T00:00:00-05:00       96        420        420        420

count is how many runs started; min, max and mean are seconds
```

Sixteen starts a day becoming ninety-six, with the mean cycle falling from 39
minutes to 7. Over those same four days the duty cycle sat at 46.5% and never
moved. **That is what a duty cycle cannot see.**

`--sense on`, `--sense off` or `--sense both` (the default). A bucketed run
report needs a single sense, because one table cannot hold two series. Each run
falls in the interval it **started** in, so a cycle spanning midnight belongs to
the day it began.

`Bucket` carries no unit, so it is said once here: with `--runs`, `count` is how
many runs started in that interval and the min, max and mean are **seconds**.

### What a run's duration actually is

The span between its **first and last observations**. The real transitions
happened somewhere in the sampling gaps on either side, so a run is short by up
to one sampling interval at each end, and a run seen only once has a duration of
zero. Nothing is extrapolated to make those look tidier.

**A hole longer than `--max-gap` ends the run**, even when the value either side
is the same. Assuming a signal held across an outage is the same mistake as
reading a missing state reading as "off" — the recorder was not there, and what
happened is unknown. The default is five minutes, five missed cycles at the
documented one-minute poll; raise it if you poll more slowly, or every ordinary
interval will read as an outage.

Runs at the edge of the window, and runs cut by a gap, are counted as
**truncated** and reported as such. Their durations are lower bounds and belong
out of any average, not silently inside one.

## What was happening before an event

Runs say the compressor cycled. They do not say what the loop was doing when it
stopped. `--events` takes the runs of one signal as **moments** and reports what
another sensor — or a delta — was doing in a window around each one.

```bash
python3 tools/geopilot_report.py --database geopilot.sqlite3 \
    --sensor sensor_loop_out --minus sensor_loop_in \
    --events sensor_lockout --sense on --before 20m
```

```text
subject: sensor_loop_out minus sensor_loop_in
events : asserted runs of sensor_lockout, at their start
window : 20m 0s before to 0s after

event at                     count        min        max       mean
2026-07-15T07:10:06-04:00       20       0.15        3.1      2.098
2026-07-15T15:00:06-04:00       20       0.15        3.1      2.098
2026-07-15T21:50:06-04:00       20       0.15        3.1      2.098

pooled mean around these events: 2.098
mean over the whole window:       2.938
(the baseline includes these windows, so any contrast is understated)

this describes what happened around the events; it does not say why
```

Event moments carry the **local wall clock**, so they can be checked against
your own memory of the evening rather than against Greenwich.

### If you have no lockout contact

You need a signal that marks the event. A fault relay, or the equipment's own
lockout output, wired as a discrete input. Without one there is nothing to
anchor to, because **GeoPilot will not infer a fault** — a cycle that ended is
just a cycle that ended, and deciding otherwise is interpretation.

Until that contact exists, the usable proxy is the end of every cycle:

```bash
python3 tools/geopilot_report.py --database geopilot.sqlite3 \
    --sensor sensor_loop_out --minus sensor_loop_in \
    --events sensor_compressor --sense on --edge end --before 20m
```

Every cycle end, lockouts included. If the ones that were lockouts sit apart
from the rest in that table, you have found something without needing the
contact — and a reason to install it.

### Details that decide what the numbers mean

**The window is half open**, `[event − before, event + after)`. With the default
`--after 0s` the event's own moment is excluded, so "before" means before.
`--after` reaches past it when what happened next is the question.

**`--edge start`** anchors to the beginning of each run — the instant a lockout
latched. **`--edge end`** anchors to its last observation.

**The pooled mean weights every reading equally**, not every event. A mean of
means would give an event with three readings the same say as one with three
hundred.

**The baseline is the same measurement over the whole window**, and that window
*includes* the approach windows. So the contrast is understated, never
overstated. If a difference shows through anyway, it is not an artefact of the
comparison.

**An event whose window holds no reading is left out**, not reported as a zero,
and the count of those is printed.

### What this is not

**It does not explain.** That the delta was low before every lockout is a fact
about the recording. Which of the two caused the other, if either, is not in the
data, and the tool says so on every run.

**Three events are three events.** Nothing here computes significance, and a
pattern across a handful of events is a reason to keep recording, not a finding.

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

### The other side: what happens while it is off

`--while-not` keeps the opposite moments. Same four days, same database:

```bash
python3 tools/geopilot_report.py --database geopilot.sqlite3 \
    --sensor sensor_loop_in --minus sensor_loop_out \
    --while-not sensor_compressor --bucket 1d
```

```text
starts at                    count        min        max       mean
2026-01-12T00:00:00-05:00      168        0.1      0.148     0.1239
2026-01-13T00:00:00-05:00      144      0.148      0.196     0.1719
2026-01-14T00:00:00-05:00      120      0.196      0.244     0.2199
2026-01-15T00:00:00-05:00       96      0.244      0.292     0.2679
```

Two independent series, from one recording. Under load the delta shrinks; at
rest the residual delta grows and the idle `count` falls — less time off, and
less settled when it gets there. Either series alone can be argued with. The
pair is harder to dismiss.

The two senses **partition** the data: every observation the gate can speak for
lands in exactly one of them, and the counts add up to the ungated total.

`--while` and `--while-not` are separate flags rather than one flag with an
invert switch, and they are mutually exclusive. The sense is printed beside
every result, because a bare sensor name next to a number does not say which
side of it you are looking at.

### What the gate is allowed to assume

The state sensor is sampled on the same cycle as everything else, so its
readings do not line up exactly with the temperatures either. Each observation
is matched to the nearest state reading within `--tolerance`, and:

- **a state reading is reused, not consumed.** A state is a level, and the same
  observation legitimately describes every moment near it. Reuse cannot inflate
  anything, because the gate contributes no value — it only answers yes or no.
  This is the opposite of the delta pairing, deliberately;
- **it will not reach past the tolerance.** Beyond that the signal is
  unobserved, and **an unobserved state admits nothing, in either direction.**

That last rule matters most for `--while-not`. It would be easy, and wrong, to
read "no state reading here" as "it was off" — which would silently count every
hole in the state record as idle time, and the holes are exactly where you know
least. So a gap admits nothing to either side, and the counts show it: when the
two senses do not add up to the ungated total, the difference is unobserved
state, not a rounding artefact.

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

**It conditions on one gate.** Either sense of one state sensor, and no more.
There is no way to ask for "while zone 1 called *and* the outdoor temperature
was below −10", nor to combine two state sensors.

**A gated result says nothing about duration.** "The delta while idle" is not
"how long it took to recover"; a gate selects moments, it does not measure the
stretch they belong to. For durations, use `--runs`, which answers a different
question and is not combined with `--while` or `--minus`.

**Runs describe one signal.** `--events` lines a second sensor up against a
signal's run boundaries, but there is still no way to ask how the delta behaved
*within* a run, nor to compare runs of one sensor against runs of another.

**`--events` does not compare against a matched baseline.** The contrast is
against the whole window, not against windows of the same length picked from
comparable conditions. That is a weaker comparison than a proper control, and
it is the one available without inventing criteria.

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

For the inverse sense: both gates over one dataset giving 3.0 and 0.1, the two
senses partitioning the pairs so their counts add to the ungated total, an
unobserved state admitting nothing to *either* side, both senses at once being
refused, and the same three validations applying to the inverse gate.

For runs: splitting at every transition, a run spanning first to last
observation, a single-sample run having no duration, the first and last runs
being truncated, a long hole ending a run while a short one does not, an
adjustable threshold, starts counted per interval, a run belonging to the
interval it started in, and the case that motivates the whole feature — two
series with an identical duty cycle, one of which is a single run and the other
twenty.

For events: one approach per event, the event's own moment excluded by the
half-open window, `--after` reaching past it, anchoring to either edge, an event
with no reading in range being left out rather than zeroed, the idle sense
supplying events, an event moment carrying the local wall clock, pooling
weighted by readings rather than by event, and the three refusals — an unknown
edge, a zero-length window and a backwards one.
