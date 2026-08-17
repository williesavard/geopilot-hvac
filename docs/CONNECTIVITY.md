# Connectivity

**Status:** Implemented
**Scope:** which sensors are talking, and which were never heard from

Coverage reports what the database holds. That answers "what was recorded", and
it cannot answer the question you have with a stripped wire in your hand:
**is this thing connected?**

## The hole this fills

Coverage can only list sensors that produced a reading. So a DS18B20 configured
with the wrong device id, or a Modbus sensor at the wrong address, produces **no
row at all** — indistinguishable from a sensor nobody configured. The one thing
you need while wiring was invisible.

This starts from the configuration instead. Every sensor the installation says
should exist gets a verdict, whether or not it has ever said anything.

```bash
python3 tools/geopilot_dashboard.py \
    --database geopilot.sqlite3 \
    --config /etc/geopilot/installation.toml \
    --output ~/geopilot.html
```

Without `--config` the section is not rendered, because without the roster it
would be the coverage table again under a more confident heading.

## The verdicts

| Verdict | Means | What to check |
| --- | --- | --- |
| **never seen** | configured, never produced a reading | wiring, address, device id |
| **just started** | reporting, too few readings to know its cadence | nothing; commissioning is working |
| **connected** | reporting on schedule | nothing |
| **late** | overdue, but not by much | a loose terminal, an intermittent connection |
| **stopped** | long overdue | it has stopped |
| **not configured** | recorded, absent from the configuration | a rename, or data left over |

Worst first. The row you need is the one you did not expect to see, and making
somebody scan a green list for it is a poor way to spend an evening in a
basement.

## Judged against each sensor's own rhythm

Lateness is relative, never absolute. Three minutes of silence is nothing from a
sensor read every ten minutes and an outage from one read every ten seconds.

Each sensor's usual interval is the **median** of its recent gaps — median
rather than mean, because a single outage would drag a mean far enough to make a
genuinely stopped sensor look punctual. Late past three intervals, stopped past
ten.

Below three readings there is no cadence to speak of: one gap is not a rhythm.
That verdict is **just started**, which is honest and is also the normal state of
a sensor wired ninety seconds ago.

## One dead bus, not six dead sensors

Six red rows on one adapter is not six faults. It is an unplugged cable, and
working that out one row at a time is slow.

Each bus is summarized: *"source_relay — 0 of 3 reporting. Every sensor on this
bus has stopped; suspect the bus, not the sensors."*

A bus is only called dead when **every** sensor on it has stopped. One silent
sensor among five is a sensor. And a bus whose sensors have never reported gets
a different message from one that stopped, because they call for different
checks: a bus that never worked is wiring, a bus that stopped is a cable.

## Readings stamped in the future

A negative age would read as impossibly fresh and slip through the healthy path.
Beyond two minutes of tolerance the sensor is flagged, saying the recording
host's clock disagrees with this one.

This is not hypothetical. A Raspberry Pi with no real-time clock is the machine
this runs on.

## What it does not do

**It does not touch the bus.** Every verdict is drawn from the recording and the
configuration, so it costs nothing and cannot disturb acquisition — and it is
only ever **as fresh as the last poll**. Wire something, wait one cycle, refresh.

For a device asked to answer *right now* rather than inferred from history, use
[Live Probe](PROBE.md) — `tools/geopilot_probe.py`, or the button on the served
page. That shortens the loop from a poll interval to a second, and it discovers
1-Wire probes the configuration does not mention yet.

**It does not check that a reading is correct.** A DS18B20 wired to the wrong
terminal but still on the bus reports 85 °C, which is a power-on-reset value and
not a temperature; this section will call it connected, because it is. Plausible
values are a different question.

## Testing

`tests/test_connectivity.py`.

Covered: a configured sensor that never reported, the three lateness thresholds,
lateness judged against a fast and a slow sensor with identical silence, too few
readings reading as new, a future stamp being flagged and small drift tolerated,
data with no configuration entry, a whole bus dead versus one quiet sensor among
several, a bus that never worked being distinguished from one that stopped, and
an unconfigured sensor not being allowed to drag a bus's verdict down.
