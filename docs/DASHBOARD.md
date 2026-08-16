# Dashboard

**Status:** Implemented
**Scope:** rendering a recorded database as one HTML page, read-only

The command line answers a question at a time. This answers "show me".

```bash
python3 tools/geopilot_dashboard.py \
    --database /var/lib/geopilot/geopilot.sqlite3 \
    --output ~/geopilot.html \
    --delta sensor_loop_in:sensor_loop_out
```

Open the result in any browser.

## One file, and why that is the whole design

The page carries its own styles, its own script and its own data. It makes **no
network requests at all** — a test asserts that the only URL in the file is the
SVG namespace, which names a dialect and is never fetched.

That is not minimalism for its own sake. It buys three things that matter here:

- **it works in a mechanical room** with a laptop and no signal;
- **it can be emailed to an engineer**, who opens one attachment and sees
  everything, with no server to run and no account to make;
- **it cannot rot.** A page that loads a charting library from a CDN is a page
  that breaks in 2029. This one will render in a decade.

There is no server, so there is nothing to secure, nothing to keep running, and
no second thing that can be down when you need the data.

## What is on it

**Is it still recording?** — every sensor, its reading count, its span, its
largest gap and when it was last seen, with a dot: green, amber past an hour of
missing history, red past a day or a tenth of everything recorded. Both tests
are needed. Fourteen hours missing from a fortnight is only four percent, and a
purely proportional rule would call that healthy while it is still most of a day
with no idea what the heating did.

**Loop deltas** — one chart per `--delta`, optionally restricted with `--while`.
The difference is computed per paired reading and then averaged, never as one
sensor's average minus the other's.

**Sensors** — one chart per numeric sensor: the mean per interval, with a shaded
band spanning the minimum and maximum, so a flat average that hides a wild swing
still looks wild.

**Cycles** — for every `state` sensor, the duty cycle beside the cycle count,
the shortest, mean and longest, and a bar per interval counting the cycles that
*started* in it. The bars are counts, not durations, because "it started 96
times today against 16 last week" is the sentence a duty cycle cannot say.

Every chart offers per hour, per 6 hours and per day. All three are precomputed
and embedded, so switching costs no query and no connection.

## What it will not do

**It does not interpret.** Printed in the footer of every page: every number
describes what was recorded; none of them says why it happened.

**It does not fill holes.** An interval with no data is absent from the series,
and the chart breaks rather than drawing a line across it. This is the same rule
the timer follows when it declines to fire missed cycles on boot.

**It does not update.** The page is a snapshot of the moment it was generated.
Regenerate it; it costs a second and it never lies about being live.

**It is not a control surface.** Nothing on it writes anything, and the database
is opened read-only, so a bug in the renderer cannot damage the recording it is
describing.

## Times

Every timestamp on the page — the health table, the chart axes, the tooltips —
is the wall clock that was in effect **where the readings were taken**, taken
from the UTC offset stored beside each measurement. Not the viewer's zone, and
not UTC. A person cross-checking a cold night against their own memory of it
needs the hour their own clock showed.

## Size

Only bucketed data is embedded, never raw samples. A year of one-minute readings
across six sensors is about 3 million rows; at hourly resolution that is roughly
8,760 points per sensor, and the whole page lands in the low hundreds of
kilobytes. Two weeks of five-minute readings across six sensors renders to about
215 kB.

The tool prints the size it wrote, so a page that has grown unreasonable says so.

## Sources

The CSS and the script live in `backend/src/geopilot/assets/` and are edited as
CSS and JavaScript. They are inlined at generation time, because the **output**
has to be one file — the sources do not.

## Testing

`tests/test_dashboard.py` and `tests/test_dashboard_tool.py`.

Covered: the page referencing nothing outside itself, both assets being inlined,
every sensor reaching the health table, a state sensor being charted as cycles
rather than as a temperature, a delta panel appearing only when asked for, all
three intervals being present, a gate being named on the page, an empty database
being refused, the caveats surviving into the markup, times rendering in the
recording's own wall clock, and two escaping cases — a sensor named
`<script>alert(1)</script>` reaching the page inert, and one named
`a</script>b` failing to close the data block early.

The tool's own tests cover writing, refusing to overwrite without `--force`, a
missing database, an empty one, and a half-written `--delta`.
