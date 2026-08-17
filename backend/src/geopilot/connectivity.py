"""Which sensors are actually talking, and which were never heard from.

Coverage reports what the database holds. That answers "what was recorded" and
it cannot answer the question you have while standing in a mechanical room with
a stripped wire in your hand: **is this thing connected?**

The difference is the roster. Coverage can only list sensors that produced a
reading, so a probe wired to the wrong terminal, or configured with the wrong
device id, produces no row at all — indistinguishable from a sensor nobody
configured. This module starts from the configuration instead, and reports on
every sensor that *should* exist whether or not it ever said anything.

Six verdicts, each with a different thing to go and check:

| Verdict | Means | What to look at |
| --- | --- | --- |
| `never` | configured, never produced a reading | wiring, address, device id |
| `new` | reporting, too few readings to know its cadence | nothing; commissioning works |
| `live` | reporting on schedule | nothing |
| `late` | overdue, but not by much | intermittent connection, loose terminal |
| `silent` | long overdue | it has stopped |
| `unconfigured` | recorded, but absent from the configuration | a rename, or stale data |

Nothing here touches a bus. Every verdict is drawn from the recording and the
configuration, which means it costs nothing and cannot disturb acquisition —
and also means a verdict is only ever as fresh as the last poll.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from statistics import median

from geopilot.reporting import _from_microseconds

LATE_MULTIPLE = 3
SILENT_MULTIPLE = 10
"""How overdue a sensor must be, as a multiple of its own usual interval.

Relative to each sensor rather than absolute, because the same three minutes of
silence is nothing from a sensor read every two minutes and an outage from one
read every ten seconds. Three intervals is a hiccup; ten is a fault.
"""

FUTURE_TOLERANCE = timedelta(minutes=2)
"""How far ahead of the clock a reading may be stamped before it is suspicious.

Two minutes absorbs ordinary drift between a Pi and a laptop. Beyond it, one of
the two clocks is wrong, and saying so beats reporting a sensor as impossibly
fresh — which is what a negative age would otherwise look like.
"""

CADENCE_SAMPLE = 50
MINIMUM_FOR_CADENCE = 3
"""How many readings it takes before a sensor's own rhythm can be judged.

Two readings give one gap, and one gap is not a cadence. Below this the verdict
is `new`, which is the honest answer and also the normal state of a sensor that
was wired ninety seconds ago.
"""


class Presence(StrEnum):
    """What a sensor is currently doing, or failing to do."""

    LIVE = "live"
    NEW = "new"
    LATE = "late"
    SILENT = "silent"
    NEVER = "never"
    UNCONFIGURED = "unconfigured"


HEALTHY = frozenset({Presence.LIVE, Presence.NEW})
"""Verdicts that need no action."""


@dataclass(frozen=True, slots=True)
class ConfiguredSensor:
    """One sensor the installation says should exist."""

    sensor_id: str
    name: str
    source_id: str
    unit: str


@dataclass(frozen=True, slots=True)
class SensorPresence:
    """One sensor's verdict, with everything needed to act on it."""

    sensor_id: str
    name: str
    source_id: str
    unit: str
    presence: Presence
    count: int
    last_seen: datetime | None
    since_last: timedelta | None
    cadence: timedelta | None
    detail: str

    @property
    def healthy(self) -> bool:
        return self.presence in HEALTHY


@dataclass(frozen=True, slots=True)
class SourcePresence:
    """A whole bus, judged by whether anything on it is still talking.

    This is the verdict that saves an evening. Six red sensors on one adapter is
    not six faults; it is one unplugged cable, and reading six rows one at a time
    is a slow way to work that out.
    """

    source_id: str
    total: int
    healthy: int
    presence: Presence
    detail: str


def roster_from(config: object) -> tuple[ConfiguredSensor, ...]:
    """Build the roster from a loaded installation configuration.

    Takes the sensors, not the reads. A sensor with no read wired to it is still
    a sensor somebody expected to see, and leaving it out would hide exactly the
    mistake this module exists to surface.
    """

    sensors = getattr(config, "sensors", ())
    return tuple(
        ConfiguredSensor(
            sensor_id=sensor.id,
            name=sensor.name,
            source_id=sensor.source_id,
            unit=sensor.unit,
        )
        for sensor in sensors
    )


def presence(
    connection: sqlite3.Connection,
    roster: tuple[ConfiguredSensor, ...],
    *,
    now: datetime,
) -> tuple[SensorPresence, ...]:
    """Judge every configured sensor, and name anything recorded but unexpected."""

    recorded = _recorded(connection)
    verdicts = [_judge(sensor, recorded.get(sensor.sensor_id), now) for sensor in roster]

    configured = {sensor.sensor_id for sensor in roster}
    for sensor_id, facts in sorted(recorded.items()):
        if sensor_id in configured:
            continue
        verdicts.append(
            SensorPresence(
                sensor_id=sensor_id,
                name="",
                source_id="",
                unit=facts.unit,
                presence=Presence.UNCONFIGURED,
                count=facts.count,
                last_seen=facts.last_seen,
                since_last=now - facts.last_seen,
                cadence=facts.cadence,
                detail="recorded but not in the configuration; renamed, or left over",
            )
        )

    return tuple(verdicts)


def by_source(verdicts: tuple[SensorPresence, ...]) -> tuple[SourcePresence, ...]:
    """Summarize each bus, so one dead adapter reads as one fault.

    A source is only called dead when **every** sensor on it has stopped. One
    silent sensor among five is a sensor; five out of five is the cable.
    """

    sources: dict[str, list[SensorPresence]] = {}
    for verdict in verdicts:
        if verdict.presence is Presence.UNCONFIGURED:
            continue
        sources.setdefault(verdict.source_id, []).append(verdict)

    summaries = []
    for source_id, members in sorted(sources.items()):
        healthy = sum(1 for member in members if member.healthy)
        if healthy == len(members):
            state, detail = Presence.LIVE, ""
        elif healthy:
            state, detail = Presence.LATE, f"{len(members) - healthy} of {len(members)} quiet"
        elif all(member.presence is Presence.NEVER for member in members):
            state, detail = (
                Presence.NEVER,
                "nothing on this bus has ever reported; check the adapter and the wiring",
            )
        else:
            state, detail = (
                Presence.SILENT,
                "every sensor on this bus has stopped; suspect the bus, not the sensors",
            )
        summaries.append(
            SourcePresence(
                source_id=source_id,
                total=len(members),
                healthy=healthy,
                presence=state,
                detail=detail,
            )
        )
    return tuple(summaries)


@dataclass(frozen=True, slots=True)
class _Facts:
    count: int
    unit: str
    last_seen: datetime
    cadence: timedelta | None


def _judge(
    sensor: ConfiguredSensor, facts: _Facts | None, now: datetime
) -> SensorPresence:
    if facts is None:
        return SensorPresence(
            sensor_id=sensor.sensor_id,
            name=sensor.name,
            source_id=sensor.source_id,
            unit=sensor.unit,
            presence=Presence.NEVER,
            count=0,
            last_seen=None,
            since_last=None,
            cadence=None,
            detail="configured but never heard from; check the wiring, address or device id",
        )

    since = now - facts.last_seen

    if since < -FUTURE_TOLERANCE:
        # Negative age reads as impossibly fresh, so the healthy path would
        # swallow it. A Pi with no real-time clock is exactly the machine this
        # runs on, and a clock that disagrees mislabels history permanently.
        return SensorPresence(
            sensor_id=sensor.sensor_id,
            name=sensor.name,
            source_id=sensor.source_id,
            unit=sensor.unit,
            presence=Presence.LATE,
            count=facts.count,
            last_seen=facts.last_seen,
            since_last=since,
            cadence=facts.cadence,
            detail=(
                f"stamped {_duration(-since)} in the future; the recording host's "
                "clock disagrees with this one"
            ),
        )

    if facts.cadence is None:
        state = Presence.NEW
        detail = "reporting, but not yet often enough to know its usual interval"
    elif since >= facts.cadence * SILENT_MULTIPLE:
        state = Presence.SILENT
        detail = (
            f"nothing for {_duration(since)}; "
            f"it usually reports every {_duration(facts.cadence)}"
        )
    elif since >= facts.cadence * LATE_MULTIPLE:
        state = Presence.LATE
        detail = f"overdue by {_duration(since - facts.cadence)}"
    else:
        state = Presence.LIVE
        detail = ""

    return SensorPresence(
        sensor_id=sensor.sensor_id,
        name=sensor.name,
        source_id=sensor.source_id,
        unit=sensor.unit,
        presence=state,
        count=facts.count,
        last_seen=facts.last_seen,
        since_last=since,
        cadence=facts.cadence,
        detail=detail,
    )


def _recorded(connection: sqlite3.Connection) -> dict[str, _Facts]:
    rows = connection.execute(
        "SELECT sensor_id, unit, COUNT(*), MAX(observed_at_us) "
        "FROM measurements GROUP BY sensor_id, unit"
    ).fetchall()

    facts: dict[str, _Facts] = {}
    for sensor_id, unit, count, last_us in rows:
        facts[str(sensor_id)] = _Facts(
            count=int(count),
            unit=str(unit),
            last_seen=_from_microseconds(int(last_us)),
            cadence=_cadence(connection, str(sensor_id)),
        )
    return facts


def _cadence(connection: sqlite3.Connection, sensor_id: str) -> timedelta | None:
    """The sensor's usual interval, from the median of its recent gaps.

    The median rather than the mean, because one outage would drag a mean far
    enough to make a genuinely stopped sensor look punctual.
    """

    rows = connection.execute(
        "SELECT observed_at_us FROM measurements WHERE sensor_id = ? "
        "ORDER BY observed_at_us DESC LIMIT ?",
        (sensor_id, CADENCE_SAMPLE),
    ).fetchall()

    if len(rows) < MINIMUM_FOR_CADENCE:
        return None

    stamps = [int(value) for (value,) in rows]
    gaps = [earlier - later for earlier, later in zip(stamps, stamps[1:], strict=False)]
    middle = median(gaps)
    return timedelta(microseconds=middle) if middle > 0 else None


def _duration(span: timedelta) -> str:
    seconds = int(span.total_seconds())
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h {(seconds % 3600) // 60}m"
    return f"{seconds // 86400}d {(seconds % 86400) // 3600}h"
