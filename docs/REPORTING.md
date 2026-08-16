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

| Exit code | Meaning |
| --- | --- |
| 0 | a report was produced |
| 1 | bad arguments, missing database, or mixed units |
| 2 | the query succeeded and found nothing |

Exit 2 exists so a cron job can distinguish "the recorder is empty" from "the
command was wrong". They call for different responses.

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
`degF`, `summarize` raises rather than averaging them. A mean of 20 and 68 is a
number with no meaning. Coverage still lists both, as separate rows, which is
how you notice.

**It has no time buckets.** Hourly and daily aggregates — the shape you would
actually plot — are the obvious next step and are not here yet. The largest gap
is computed in Python over the sensor's timestamps rather than in SQL, which is
fine for a year of one-minute samples and would not be for a decade of them.

## Testing

`tests/test_reporting.py` and `tests/test_report_tool.py`.

Every test writes through the real historian rather than inserting SQL, so the
reports are proven against the schema the recorder actually produces. Covered:
the read-only connection genuinely refusing a write, a missing database not
being created, gap detection across a three-day hole, half-open windows, empty
windows reporting nothing rather than zero, mixed-unit refusal, duty cycle
including the zero case, and a report produced against a database that is still
being written.
