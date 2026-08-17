"""Render a recorded database as one self-contained HTML page.

The command line answers a question at a time. This answers "show me" — and it
produces a **single file**, with the CSS, the script and the data inlined, so it
survives being copied to a USB stick or attached to an email to an engineer.
That constraint is the whole design: no server, no network, no libraries.

It reads through `reporting`, so every refusal and every caveat established
there holds here too. Nothing is computed twice and nothing is computed
differently:

- an interval with no data is **absent**, and the chart breaks rather than
  drawing a line across it;
- a gated view names its gate;
- the counts are shown beside every mean, because a mean over four readings and
  a mean over four hundred are different claims.

The page states what it cannot tell you as plainly as what it can.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from importlib import resources
from typing import Any

from geopilot.connectivity import (
    ConfiguredSensor,
    Presence,
    by_source,
    presence,
)
from geopilot.ingestion import STATE_UNIT
from geopilot.reporting import (
    Bucket,
    ReportingError,
    bucketed,
    bucketed_delta,
    bucketed_runs,
    coverage,
    duty_cycle,
    summarize_runs,
)

VIEWS: tuple[tuple[str, timedelta], ...] = (
    ("hour", timedelta(hours=1)),
    ("6 hours", timedelta(hours=6)),
    ("day", timedelta(days=1)),
)
"""The bucket sizes offered on every chart.

Three is enough to move between "what happened last night" and "what happened
this winter", and every one of them is precomputed and embedded. A fourth would
grow the file for a view nobody asked for.
"""

DEFAULT_VIEW = "day"


@dataclass(frozen=True, slots=True)
class DeltaPair:
    """One pair of sensors to chart the difference of."""

    sensor_id: str
    minus: str


def render(
    connection: sqlite3.Connection,
    *,
    title: str = "GeoPilot",
    deltas: tuple[DeltaPair, ...] = (),
    while_asserted: str | None = None,
    generated_at: datetime | None = None,
    control_token: str | None = None,
    roster: tuple[ConfiguredSensor, ...] = (),
) -> str:
    """Build the page. Returns HTML; writes nothing.

    `control_token` turns the page into a control surface. Without it — the
    static file written by `tools/geopilot_dashboard.py` — the controls are not
    merely hidden, they are **not rendered at all**, because a file has no back
    channel and a button that cannot work is worse than no button.

    `roster` is what the configuration says should exist. Without it the page can
    only report sensors that produced a reading, and a probe wired to the wrong
    terminal is invisible rather than red.
    """

    sensors = coverage(connection)
    if not sensors:
        raise ReportingError("that database holds no measurements, so there is nothing to show")

    panels: dict[str, dict[str, Any]] = {}
    sections: list[str] = []

    if control_token is not None:
        sections.append(_control_section())

    if roster:
        sections.append(
            _connection_section(connection, roster, generated_at or _now())
        )

    sections.append(_health_section(sensors))

    numeric = [report for report in sensors if report.unit != STATE_UNIT]
    states = [report for report in sensors if report.unit == STATE_UNIT]

    units = {report.sensor_id: report.unit for report in sensors}

    if deltas:
        sections.append(
            _chart_section(
                "Loop deltas",
                [
                    _delta_panel(connection, pair, while_asserted, panels, units)
                    for pair in deltas
                ],
                intro=(
                    "The difference between two sensors, computed per paired reading and "
                    "then averaged — never one sensor's average minus the other's."
                ),
                gate=while_asserted,
            )
        )

    if numeric:
        sections.append(
            _chart_section(
                "Sensors",
                [
                    _sensor_panel(connection, report.sensor_id, report.unit, panels)
                    for report in numeric
                ],
                intro="Mean per interval, with the shaded band spanning the minimum and maximum.",
                gate=None,
            )
        )

    if states:
        sections.append(_cycles_section(connection, states, panels))

    return _page(
        title=title,
        subtitle=_subtitle(sensors, generated_at),
        sections=sections,
        payload={"panels": panels, "controlToken": control_token},
        control=control_token is not None,
    )


def _control_section() -> str:
    """The control surface, filled in by the browser from /api/state.

    Deliberately empty in the markup. The state of a relay is read back from the
    bus when the page asks, never baked into a document that starts going stale
    the moment it is written.
    """

    return """
<h2>Control</h2>
<p class="subtitle">What GeoPilot is permitted to operate, and what the bus says
those relays are actually doing right now.</p>
<div class="card" id="control">
  <p class="note">reading the bus…</p>
</div>
<p class="caveat">Every state shown here was read back from the equipment, never
remembered from what was last commanded — a controller that believes its own
intentions cannot notice a contact that did not move. Commands are refused
unless control is enabled in the configuration, the relay is on the whitelist,
and it has rested long enough. Every attempt is recorded, refusals included.</p>
"""


PRESENCE_COLOURS = {
    Presence.LIVE: "good",
    Presence.NEW: "good",
    Presence.LATE: "warn",
    Presence.SILENT: "bad",
    Presence.NEVER: "bad",
    Presence.UNCONFIGURED: "warn",
}

PRESENCE_WORDS = {
    Presence.LIVE: "connected",
    Presence.NEW: "just started",
    Presence.LATE: "late",
    Presence.SILENT: "stopped",
    Presence.NEVER: "never seen",
    Presence.UNCONFIGURED: "not configured",
}


def _connection_section(
    connection: sqlite3.Connection,
    roster: tuple[ConfiguredSensor, ...],
    now: datetime,
) -> str:
    """What is wired, what is talking, and what was never heard from.

    Ordered worst first. The row you need is the one you did not expect to see,
    and making somebody scan a green list for it is a poor way to spend an
    evening in a basement.
    """

    verdicts = presence(connection, roster, now=now)
    order = {
        Presence.NEVER: 0,
        Presence.SILENT: 1,
        Presence.LATE: 2,
        Presence.UNCONFIGURED: 3,
        Presence.NEW: 4,
        Presence.LIVE: 5,
    }
    verdicts = tuple(sorted(verdicts, key=lambda item: (order[item.presence], item.sensor_id)))

    rows = "".join(
        "<tr>"
        f"<td><span class='status {PRESENCE_COLOURS[item.presence]}'></span>"
        f"<strong>{_escape(item.sensor_id)}</strong>"
        + (f"<br><span class='subtitle'>{_escape(item.name)}</span>" if item.name else "")
        + "</td>"
        f"<td>{_escape(PRESENCE_WORDS[item.presence])}</td>"
        f"<td>{_escape(item.source_id or '—')}</td>"
        f"<td>{item.count:,}</td>"
        f"<td>{_escape(_duration(item.since_last) if item.since_last else '—')}</td>"
        f"<td class='detail'>{_escape(item.detail)}</td>"
        "</tr>"
        for item in verdicts
    )

    buses = "".join(
        "<li>"
        f"<span class='status {PRESENCE_COLOURS[bus.presence]}'></span>"
        f"<strong>{_escape(bus.source_id)}</strong> — "
        f"{bus.healthy} of {bus.total} reporting"
        + (f". {_escape(bus.detail)}" if bus.detail else "")
        + "</li>"
        for bus in by_source(verdicts)
    )

    troubled = sum(1 for item in verdicts if not item.healthy)
    headline = (
        "Everything the configuration lists is reporting."
        if not troubled
        else f"{troubled} of {len(verdicts)} need attention."
    )

    return f"""
<h2>What is connected</h2>
<p class="subtitle">{headline} Every sensor the configuration expects is listed,
including the ones that have never said anything.</p>
<div class="card">
  <ul class="buses">{buses}</ul>
</div>
<div class="card scroll">
  <table>
    <thead><tr>
      <th>sensor</th><th>state</th><th>bus</th><th>readings</th>
      <th>silent for</th><th>what to check</th>
    </tr></thead>
    <tbody>{rows}</tbody>
  </table>
</div>
<p class="caveat">A sensor is judged against <em>its own</em> usual interval:
late past three of them, stopped past ten. <strong>Never seen</strong> means the
configuration expects it and the database has never held a single reading from
it — the wiring, the address or the device id. When every sensor on one bus is
quiet, suspect the bus, not the sensors. None of this touches the equipment: it
is read from the recording, so it is only ever as fresh as the last poll.</p>
"""


def _health_section(sensors: tuple[Any, ...]) -> str:
    rows = []
    for report in sensors:
        state = _gap_state(report.largest_gap, report.span)
        rows.append(
            "<tr>"
            f"<td><span class='status {state}'></span>{_escape(report.sensor_id)}</td>"
            f"<td>{_escape(report.unit)}</td>"
            f"<td>{report.count:,}</td>"
            f"<td>{_escape(_duration(report.span))}</td>"
            f"<td>{_escape(_duration(report.largest_gap))}</td>"
            f"<td>{_escape(report.last_observed_at.isoformat(timespec='minutes'))}</td>"
            "</tr>"
        )

    return f"""
<h2>How much history</h2>
<p class="subtitle">What is in the recording, and where the holes are. Whether a
sensor is talking <em>now</em> is the section above.</p>
<div class="card scroll">
  <table>
    <thead><tr>
      <th>sensor</th><th>unit</th><th>readings</th><th>span</th>
      <th>largest gap</th><th>last seen</th>
    </tr></thead>
    <tbody>{"".join(rows)}</tbody>
  </table>
</div>
<p class="caveat">A total that keeps rising can still hide a three-day hole in
February. The gap column is the one that shows it. Amber means the worst hole
passed an hour; red means it passed a day, or a tenth of everything recorded.</p>
"""


def _sensor_panel(
    connection: sqlite3.Connection,
    sensor_id: str,
    unit: str,
    panels: dict[str, dict[str, Any]],
) -> str:
    key = f"sensor:{sensor_id}"
    panels[key] = {
        "kind": "line",
        "unit": unit,
        "initial": DEFAULT_VIEW,
        "views": {
            name: _series(bucketed(connection, sensor_id, interval=interval))
            for name, interval in VIEWS
        },
    }
    return _panel(key, sensor_id, unit)


def _delta_panel(
    connection: sqlite3.Connection,
    pair: DeltaPair,
    while_asserted: str | None,
    panels: dict[str, dict[str, Any]],
    units: dict[str, str],
) -> str:
    key = f"delta:{pair.sensor_id}:{pair.minus}"
    unit = units.get(pair.sensor_id, "")
    panels[key] = {
        "kind": "line",
        "unit": unit,
        "initial": DEFAULT_VIEW,
        "views": {
            name: _series(
                bucketed_delta(
                    connection,
                    pair.sensor_id,
                    minus=pair.minus,
                    interval=interval,
                    while_asserted=while_asserted,
                )
            )
            for name, interval in VIEWS
        },
    }
    return _panel(key, f"{pair.sensor_id} − {pair.minus}", unit)


def _cycles_section(
    connection: sqlite3.Connection,
    states: list[Any],
    panels: dict[str, dict[str, Any]],
) -> str:
    figures = []
    rows = []

    for report in states:
        key = f"runs:{report.sensor_id}"
        panels[key] = {
            "kind": "bars",
            "unit": "cycles",
            "initial": DEFAULT_VIEW,
            "views": {
                name: _series(
                    bucketed_runs(
                        connection, report.sensor_id, asserted=True, interval=interval
                    )
                )
                for name, interval in VIEWS
            },
        }
        figures.append(
            _panel(key, f"{report.sensor_id} — cycles started", "cycles started per interval")
        )

        summary = summarize_runs(connection, report.sensor_id, asserted=True)
        ratio = duty_cycle(connection, report.sensor_id)
        rows.append(
            "<tr>"
            f"<td>{_escape(report.sensor_id)}</td>"
            f"<td>{'—' if ratio is None else f'{ratio * 100:.1f}%'}</td>"
            f"<td>{'—' if summary is None else f'{summary.count:,}'}</td>"
            f"<td>{'—' if summary is None else _escape(_duration(summary.shortest))}</td>"
            f"<td>{'—' if summary is None else _escape(_duration(summary.mean))}</td>"
            f"<td>{'—' if summary is None else _escape(_duration(summary.longest))}</td>"
            f"<td>{'—' if summary is None else f'{summary.truncated:,}'}</td>"
            "</tr>"
        )

    return f"""
<h2>Cycles</h2>
<p class="subtitle">A duty cycle cannot tell 16 long cycles from 96 short ones.
Cycle counts can.</p>
<div class="card scroll">
  <table>
    <thead><tr>
      <th>signal</th><th>duty cycle</th><th>cycles</th>
      <th>shortest</th><th>mean</th><th>longest</th><th>truncated</th>
    </tr></thead>
    <tbody>{"".join(rows)}</tbody>
  </table>
</div>
<div class="grid">{"".join(figures)}</div>
<p class="caveat">Each bar counts the cycles that <em>started</em> in that
interval; hover for their lengths. A cycle spanning midnight belongs to the day
it began, and is measured from its first reading to its last — so it is short by
up to one sampling interval at each end. Truncated cycles were cut by a
recording gap or by the edge of the data, and their lengths are lower bounds.</p>
"""


def _chart_section(heading: str, figures: list[str], *, intro: str, gate: str | None) -> str:
    gated = (
        f"<p class='subtitle'>Restricted to the moments <code>{_escape(gate)}</code> "
        "was asserted.</p>"
        if gate
        else ""
    )
    return f"""
<h2>{_escape(heading)}</h2>
<p class="subtitle">{intro}</p>
{gated}
<div class="grid">{"".join(figures)}</div>
"""


def _panel(key: str, heading: str, unit: str) -> str:
    buttons = "".join(
        f"<button type='button' data-view='{_escape(name)}' "
        f"aria-pressed='{str(name == DEFAULT_VIEW).lower()}'>per {_escape(name)}</button>"
        for name, _ in VIEWS
    )
    return f"""
<section class="card" data-panel="{_escape(key)}">
  <h3>{_escape(heading)}</h3>
  <p class="subtitle">{_escape(unit)}</p>
  <div class="controls">{buttons}</div>
  <div class="figure"></div>
</section>
"""


def _series(buckets: tuple[Bucket, ...]) -> list[dict[str, Any]]:
    return [
        {
            "at": bucket.starts_at.isoformat(),
            "count": bucket.count,
            "min": round(bucket.minimum, 4),
            "max": round(bucket.maximum, 4),
            "mean": round(bucket.mean, 4),
        }
        for bucket in buckets
    ]


def _subtitle(sensors: tuple[Any, ...], generated_at: datetime | None) -> str:
    first = min(report.first_observed_at for report in sensors)
    last = max(report.last_observed_at for report in sensors)
    total = sum(report.count for report in sensors)

    stamped = (
        f" · generated {generated_at.isoformat(timespec='minutes')}" if generated_at else ""
    )
    return (
        f"{total:,} readings from {len(sensors)} sensors, "
        f"{first.isoformat(timespec='minutes')} to {last.isoformat(timespec='minutes')}"
        f"{stamped}"
    )


AMBER_GAP = timedelta(hours=1)
RED_GAP = timedelta(days=1)
RED_SHARE = 0.10


def _gap_state(largest_gap: timedelta, span: timedelta) -> str:
    """Colour a sensor by its worst hole, absolutely and proportionally.

    Both tests are needed. Fourteen hours missing from a fortnight is only four
    percent, and a purely proportional rule would call that healthy — but it is
    still most of a day with no idea what the heating did. A purely absolute rule
    has the opposite blind spot: an hour missing from a decade is nothing.

    So: amber past an hour, red past a day **or** past a tenth of the recording,
    whichever comes first.
    """

    if span <= timedelta(0):
        return "warn"
    if largest_gap >= RED_GAP or largest_gap / span >= RED_SHARE:
        return "bad"
    if largest_gap >= AMBER_GAP:
        return "warn"
    return "good"


def _duration(span: timedelta) -> str:
    seconds = int(span.total_seconds())
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h {(seconds % 3600) // 60}m"
    return f"{seconds // 86400}d {(seconds % 86400) // 3600}h"


def _now() -> datetime:
    return datetime.now(UTC).astimezone()


def _asset(name: str) -> str:
    return (resources.files("geopilot.assets") / name).read_text(encoding="utf-8")


def _escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _page(
    *,
    title: str,
    subtitle: str,
    sections: list[str],
    payload: dict[str, Any],
    control: bool = False,
) -> str:
    # `</` is split so a sensor named like a closing tag cannot end the script
    # block early. The data is JSON, but it lands inside HTML.
    embedded = json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")
    control_script = f"<script>\n{_asset('control.js')}\n</script>" if control else ""
    control_note = (
        "<p>The controls read the state of each relay back from the equipment "
        "every few seconds. Nothing on this page acts without being pressed.</p>"
        if control
        else ""
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_escape(title)}</title>
<style>
{_asset("dashboard.css")}
</style>
</head>
<body>
<main>
<h1>{_escape(title)}</h1>
<p class="subtitle">{_escape(subtitle)}</p>
{"".join(sections)}
<footer>
<p>Generated by GeoPilot from a read-only copy of the recording. Every number
here describes what was recorded; none of them says why it happened.</p>
<p>Times are shown in the wall clock that was in effect where the readings were
taken.</p>
{control_note}
</footer>
</main>
<script>window.GEOPILOT={embedded};</script>
<script>
{_asset("dashboard.js")}
</script>
{control_script}
</body>
</html>
"""
