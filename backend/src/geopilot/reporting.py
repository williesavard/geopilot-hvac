"""Read-only reporting over a recorded database.

This answers the questions a year of recording exists to answer, without a
dashboard and without loading a million rows into Python.

Two deliberate departures from the rest of the project:

- **it queries SQL directly instead of going through `MeasurementHistorian`.**
  An average over ten million rows cannot travel through a protocol that
  returns tuples of objects. Aggregation belongs in the database;
- **it opens its own read-only connection from a path**, rather than borrowing
  the recorder's. WAL journalling allows concurrent readers, so a report can be
  produced while the system is still recording, and a read-only connection
  cannot damage the file it is examining.

It writes nothing, decides nothing and interprets nothing. A duty cycle is a
ratio of samples, not a diagnosis.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from geopilot.domain import epoch_microseconds

# The canonical spelling of the state unit lives with the normalizer that
# enforces it. Repeating the literal here would give it two definitions.
from geopilot.ingestion import STATE_UNIT

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_MICROSECOND = timedelta(microseconds=1)
_DAY_MICROSECONDS = 86_400_000_000

PRE_EPOCH_MESSAGE = (
    "that window contains observations stamped before 1970, which cannot be "
    "bucketed; the recording host's clock was almost certainly unset"
)

DEFAULT_PAIRING_TOLERANCE = timedelta(seconds=30)
"""How far apart two readings may be and still describe the same moment.

Thirty seconds is under half the one-minute polling interval the deployment
documents, so a reading can only ever pair within its own cycle. Poll faster
than once a minute and this must come down with it, or a sample will reach
across into the neighbouring cycle.
"""

DEFAULT_RUN_BREAK = timedelta(minutes=5)
"""How long a hole in a state series may be before it ends the run.

Five missed cycles at the documented one-minute poll. Below that a stretch is
treated as continuous; above it, what happened is unknown and the run is closed
rather than assumed to have held. Poll more slowly and this must go up, or every
ordinary interval will read as an outage.
"""

DEFAULT_APPROACH = timedelta(minutes=15)
"""How far back an approach window reaches by default.

Fifteen minutes because that is the short end of the range the installation's
lockouts were observed in. It is a starting point for looking, not a claim that
fifteen minutes is the interval that matters.
"""


class ReportingError(RuntimeError):
    """Raised when a database cannot be read for reporting."""


@dataclass(frozen=True, slots=True)
class SensorCoverage:
    """How much of a sensor's history exists, and where the holes are."""

    sensor_id: str
    unit: str
    count: int
    first_observed_at: datetime
    last_observed_at: datetime
    largest_gap: timedelta

    @property
    def span(self) -> timedelta:
        return self.last_observed_at - self.first_observed_at


@dataclass(frozen=True, slots=True)
class Bucket:
    """One interval of aggregated history.

    `starts_at` is the beginning of the interval, not the first sample in it. A
    bucket that holds a single reading taken at 14:47 still starts at 14:00.
    """

    starts_at: datetime
    count: int
    minimum: float
    maximum: float
    mean: float


@dataclass(frozen=True, slots=True)
class Run:
    """One unbroken stretch during which a state sensor held a single value.

    `duration` is the span between the **first and last observations** of the
    run. The real transitions happened somewhere in the sampling gaps on either
    side, so a run is short by up to one sampling interval at each end, and a run
    seen only once has a duration of zero. Nothing is extrapolated to make those
    look better.

    `truncated` marks a run whose edge was not an observed transition — the first
    and last runs in a window, and any run cut by a recording gap. Their
    durations are lower bounds and should be left out of duration statistics
    rather than averaged in.

    `starts_at` and `ends_at` carry the UTC offset that was in effect where the
    readings were taken, so they read as the clock on the wall did.
    """

    starts_at: datetime
    ends_at: datetime
    duration: timedelta
    samples: int
    asserted: bool
    truncated: bool
    started_microseconds: int
    started_offset_seconds: int


@dataclass(frozen=True, slots=True)
class RunSummary:
    """How long and how often a signal held one sense."""

    sensor_id: str
    asserted: bool
    count: int
    shortest: timedelta
    longest: timedelta
    mean: timedelta
    total: timedelta
    truncated: int


@dataclass(frozen=True, slots=True)
class Approach:
    """What a subject was doing in a window around one event.

    `event_at` is the moment itself, not the start of the window. The statistics
    describe the window.
    """

    event_at: datetime
    count: int
    minimum: float
    maximum: float
    mean: float


@dataclass(frozen=True, slots=True)
class DeltaSummary:
    """The difference between two sensors, over paired observations.

    `unpaired`, `unpaired_minus` and `excluded` are part of the result, not
    diagnostics. A delta computed from 40 pairs out of 1,440 readings is a
    different claim from one computed from 1,438, and the reader has to be able
    to tell.

    `unpaired` counts readings that found no partner. `excluded` counts pairs
    that were formed and then dropped by a state gate — moments on the wrong
    side of the gate's sense. The two say different things and are kept apart.
    """

    sensor_id: str
    minus: str
    unit: str
    count: int
    minimum: float
    maximum: float
    mean: float
    unpaired: int
    unpaired_minus: int
    excluded: int


@dataclass(frozen=True, slots=True)
class SensorSummary:
    """Descriptive statistics for one sensor over a window.

    `excluded` counts observations a state gate dropped, and is zero when no
    gate was applied.
    """

    sensor_id: str
    unit: str
    count: int
    minimum: float
    maximum: float
    mean: float
    excluded: int


def open_readonly(database: str | Path) -> sqlite3.Connection:
    """Open a database read-only, so reporting cannot alter what it reads."""

    location = Path(database)
    if not location.exists():
        raise ReportingError(f"database not found: {location}")
    return sqlite3.connect(f"file:{location}?mode=ro", uri=True)


def coverage(connection: sqlite3.Connection) -> tuple[SensorCoverage, ...]:
    """Report what has been recorded, per sensor, and the largest gap in each.

    The largest gap is the number worth looking at. A recorder that stopped for
    three days in February leaves a total count that still looks healthy, and
    only the gap reveals it.
    """

    sensors = connection.execute(
        "SELECT sensor_id, unit, COUNT(*), MIN(observed_at_us), MAX(observed_at_us) "
        "FROM measurements GROUP BY sensor_id, unit ORDER BY sensor_id"
    ).fetchall()

    reports: list[SensorCoverage] = []
    for sensor_id, unit, count, first_us, last_us in sensors:
        reports.append(
            SensorCoverage(
                sensor_id=str(sensor_id),
                unit=str(unit),
                count=int(count),
                first_observed_at=_from_microseconds(int(first_us)),
                last_observed_at=_from_microseconds(int(last_us)),
                largest_gap=_largest_gap(connection, str(sensor_id)),
            )
        )
    return tuple(reports)


def summarize(
    connection: sqlite3.Connection,
    sensor_id: str,
    *,
    while_asserted: str | None = None,
    while_not_asserted: str | None = None,
    tolerance: timedelta = DEFAULT_PAIRING_TOLERANCE,
    start: datetime | None = None,
    end: datetime | None = None,
) -> SensorSummary | None:
    """Return count, minimum, maximum and mean for one sensor.

    Returns None when the window holds no samples, rather than inventing zeros.

    Raises `ReportingError` if the window mixes units for one sensor. An average
    of Celsius and Fahrenheit is a number with no meaning, and producing one
    quietly would be worse than refusing.

    `while_asserted` names a `state` sensor and restricts the summary to the
    moments that sensor was reading 1 — the average loop temperature *while the
    compressor was running*, rather than an average diluted by every hour it was
    not. `while_not_asserted` keeps the opposite moments. See `_StateGate` for
    what "at that moment" is allowed to mean.
    """

    clauses = ["sensor_id = ?"]
    parameters: list[object] = [sensor_id]
    _append_window(clauses, parameters, start, end)
    where = " AND ".join(clauses)

    _require_single_unit(connection, sensor_id, where, parameters)

    gate = _gate(connection, while_asserted, while_not_asserted, tolerance, start, end)
    if gate is not None:
        return _summarize_gated(connection, sensor_id, gate, where, parameters, start, end)

    row = connection.execute(
        "SELECT unit, COUNT(*), MIN(value), MAX(value), AVG(value) "
        f"FROM measurements WHERE {where}",
        tuple(parameters),
    ).fetchone()

    unit, count, minimum, maximum, mean = row
    if not count:
        return None

    return SensorSummary(
        sensor_id=sensor_id,
        unit=str(unit),
        count=int(count),
        minimum=float(minimum),
        maximum=float(maximum),
        mean=float(mean),
        excluded=0,
    )


def _summarize_gated(
    connection: sqlite3.Connection,
    sensor_id: str,
    gate: _StateGate,
    where: str,
    parameters: list[object],
    start: datetime | None,
    end: datetime | None,
) -> SensorSummary | None:
    """Summarize only the observations the gate lets through.

    This walks the rows in Python rather than aggregating in SQL, which is the
    price of gating and is paid only when a gate is asked for.
    """

    (unit,) = connection.execute(
        f"SELECT unit FROM measurements WHERE {where} LIMIT 1", tuple(parameters)
    ).fetchone() or (None,)

    values = [
        value
        for microseconds, _, value in _observations(connection, sensor_id, start, end)
        if gate.admits(microseconds)
    ]
    if not values:
        return None

    return SensorSummary(
        sensor_id=sensor_id,
        unit=str(unit),
        count=len(values),
        minimum=min(values),
        maximum=max(values),
        mean=sum(values) / len(values),
        excluded=_sample_count(connection, sensor_id, start, end) - len(values),
    )


def bucketed(
    connection: sqlite3.Connection,
    sensor_id: str,
    *,
    interval: timedelta,
    while_asserted: str | None = None,
    while_not_asserted: str | None = None,
    tolerance: timedelta = DEFAULT_PAIRING_TOLERANCE,
    start: datetime | None = None,
    end: datetime | None = None,
    local: bool = True,
) -> tuple[Bucket, ...]:
    """Aggregate one sensor into fixed intervals, oldest first.

    This is the shape a curve is plotted from: an hourly loop temperature over a
    winter, or a daily one over a year.

    **A bucket with no samples does not appear.** Nothing is synthesized to fill
    it, for the same reason the timer does not fire missed cycles on boot: a gap
    in the data is honest, and an invented point is not. An absent bucket is the
    outage, and a plot that leaves a hole is telling the truth.

    For a `state` sensor the mean **is** the duty cycle over that interval, since
    the values are 0 and 1.

    `local` aligns buckets to the wall clock at the place the readings were
    taken, using the UTC offset stored with each measurement. A daily bucket is
    then a local calendar day rather than a day running from 19:00 to 19:00,
    which is the difference between a heating day and two half-evenings. Pass
    `local=False` for UTC alignment.

    `while_asserted` names a `state` sensor and keeps only the observations taken
    while it read 1; `while_not_asserted` keeps those taken while it read 0. A
    bucket that holds no such moment does not appear, exactly as an unrecorded
    interval does not: the equipment being off all afternoon and the recorder
    being off all afternoon look the same here, and the `count` column beside the
    neighbouring buckets is what tells them apart.
    """

    bucket_microseconds = _bucket_microseconds(interval)

    clauses = ["sensor_id = ?"]
    parameters: list[object] = [sensor_id]
    _append_window(clauses, parameters, start, end)
    where = " AND ".join(clauses)

    _require_single_unit(connection, sensor_id, where, parameters)

    gate = _gate(connection, while_asserted, while_not_asserted, tolerance, start, end)
    if gate is not None:
        return _aggregate_buckets(
            (
                (microseconds, offset_seconds, value)
                for microseconds, offset_seconds, value in _observations(
                    connection, sensor_id, start, end
                )
                if gate.admits(microseconds)
            ),
            bucket_microseconds,
            local=local,
        )

    instant = (
        "(observed_at_us + observed_at_offset_s * 1000000)" if local else "observed_at_us"
    )
    _require_post_epoch(connection, where, parameters, instant)

    rows = connection.execute(
        f"SELECT {instant} / {bucket_microseconds} AS bucket_index, "
        "COUNT(*), MIN(value), MAX(value), AVG(value), MIN(observed_at_offset_s) "
        f"FROM measurements WHERE {where} "
        "GROUP BY bucket_index ORDER BY bucket_index",
        tuple(parameters),
    ).fetchall()

    return tuple(
        Bucket(
            starts_at=_bucket_start(
                int(index) * bucket_microseconds,
                offset_seconds=int(offset_seconds) if local else 0,
            ),
            count=int(count),
            minimum=float(minimum),
            maximum=float(maximum),
            mean=float(mean),
        )
        for index, count, minimum, maximum, mean, offset_seconds in rows
    )


def delta(
    connection: sqlite3.Connection,
    sensor_id: str,
    *,
    minus: str,
    while_asserted: str | None = None,
    while_not_asserted: str | None = None,
    tolerance: timedelta = DEFAULT_PAIRING_TOLERANCE,
    start: datetime | None = None,
    end: datetime | None = None,
) -> DeltaSummary | None:
    """Summarize `sensor_id` minus `minus`, over paired observations.

    For a ground loop this is the question the whole installation turns on: how
    much heat is actually crossing the heat exchanger. It is a difference in the
    sensors' shared unit, not an absolute reading, and both sensors must carry
    the same unit or the call is refused.

    `while_asserted` names a `state` sensor and keeps only the pairs taken while
    it read 1. Without it, a mean delta over a day is diluted by every hour the
    equipment sat idle, and falls when the equipment merely ran less.

    `while_not_asserted` keeps the opposite moments — the loop sitting still
    rather than working. What that delta does over an idle stretch is a different
    question from what it does under load, and both are worth asking.

    Returns None when no pair could be formed, or when the gate let none through.
    """

    unit = _shared_unit(connection, sensor_id, minus, start, end)
    gate = _gate(connection, while_asserted, while_not_asserted, tolerance, start, end)

    pairs = _pairs(connection, sensor_id, minus, tolerance, start, end)
    paired = 0
    values: list[float] = []
    for microseconds, _, value in pairs:
        paired += 1
        if gate is None or gate.admits(microseconds):
            values.append(value)

    if not values:
        return None

    return DeltaSummary(
        sensor_id=sensor_id,
        minus=minus,
        unit=unit,
        count=len(values),
        minimum=min(values),
        maximum=max(values),
        mean=sum(values) / len(values),
        unpaired=_sample_count(connection, sensor_id, start, end) - paired,
        unpaired_minus=_sample_count(connection, minus, start, end) - paired,
        excluded=paired - len(values),
    )


def bucketed_delta(
    connection: sqlite3.Connection,
    sensor_id: str,
    *,
    minus: str,
    interval: timedelta,
    while_asserted: str | None = None,
    while_not_asserted: str | None = None,
    tolerance: timedelta = DEFAULT_PAIRING_TOLERANCE,
    start: datetime | None = None,
    end: datetime | None = None,
    local: bool = True,
) -> tuple[Bucket, ...]:
    """Aggregate the difference between two sensors into fixed intervals.

    The delta is computed **per pair and then aggregated**, never as one
    sensor's bucket mean minus the other's. Those agree for the mean and do not
    agree for the extremes: the smallest difference is not the difference of the
    smallest readings, and a bucket built that way would report a minimum that
    never occurred.

    Each pair falls in the bucket of `sensor_id`'s observation, which is also the
    one whose UTC offset aligns it to a local wall clock.

    `while_asserted` restricts the pairs to the moments a named `state` sensor
    read 1. That is what turns a daily mean delta from a number diluted by every
    idle hour into one describing the loop while it was actually working.
    `while_not_asserted` restricts them to the idle moments instead.
    """

    bucket_microseconds = _bucket_microseconds(interval)
    _shared_unit(connection, sensor_id, minus, start, end)
    gate = _gate(connection, while_asserted, while_not_asserted, tolerance, start, end)

    pairs = _pairs(connection, sensor_id, minus, tolerance, start, end)
    if gate is not None:
        pairs = (triple for triple in pairs if gate.admits(triple[0]))

    return _aggregate_buckets(pairs, bucket_microseconds, local=local)


def _aggregate_buckets(
    observations: Iterator[tuple[int, int, float]],
    bucket_microseconds: int,
    *,
    local: bool,
) -> tuple[Bucket, ...]:
    """Group already-selected observations into intervals, oldest first.

    Used wherever the rows had to be walked in Python anyway — a gated series or
    a paired delta. Plain ungated single-sensor buckets are aggregated in SQL
    instead, because there is no reason to move ten million rows to do it.
    """

    grouped: dict[int, list[float]] = {}
    offsets: dict[int, int] = {}
    for microseconds, offset_seconds, value in observations:
        instant = microseconds + offset_seconds * 1_000_000 if local else microseconds
        if instant < 0:
            raise ReportingError(PRE_EPOCH_MESSAGE)
        index = instant // bucket_microseconds
        grouped.setdefault(index, []).append(value)
        offsets.setdefault(index, offset_seconds)

    return tuple(
        Bucket(
            starts_at=_bucket_start(
                index * bucket_microseconds,
                offset_seconds=offsets[index] if local else 0,
            ),
            count=len(values),
            minimum=min(values),
            maximum=max(values),
            mean=sum(values) / len(values),
        )
        for index, values in sorted(grouped.items())
    )


def runs(
    connection: sqlite3.Connection,
    sensor_id: str,
    *,
    asserted: bool | None = None,
    max_gap: timedelta = DEFAULT_RUN_BREAK,
    start: datetime | None = None,
    end: datetime | None = None,
) -> tuple[Run, ...]:
    """Split a state sensor's history into unbroken stretches, oldest first.

    A duty cycle says a compressor ran 41% of the time. It cannot tell 22 long
    cycles from 38 short ones, and short cycling is a fault while long cycling
    is not. Runs are what separate them.

    `asserted` selects one sense, or both when left as None.

    A gap longer than `max_gap` **ends the run**, even when the value either side
    is the same. Assuming a signal held across an outage is the same mistake as
    reading a missing state reading as "off": the recorder was not there, and
    what happened is unknown.
    """

    _require_state_sensor(connection, sensor_id, start, end)
    break_microseconds = max_gap // _MICROSECOND
    if break_microseconds <= 0:
        raise ReportingError(f"a run cannot be broken by a gap of {max_gap}")

    observations = _observations(connection, sensor_id, start, end)
    return tuple(
        run
        for run in _detect_runs(observations, break_microseconds)
        if asserted is None or run.asserted is asserted
    )


def summarize_runs(
    connection: sqlite3.Connection,
    sensor_id: str,
    *,
    asserted: bool,
    max_gap: timedelta = DEFAULT_RUN_BREAK,
    start: datetime | None = None,
    end: datetime | None = None,
) -> RunSummary | None:
    """Describe how long and how often a signal held one sense."""

    found = runs(
        connection, sensor_id, asserted=asserted, max_gap=max_gap, start=start, end=end
    )
    if not found:
        return None

    durations = [run.duration for run in found]
    return RunSummary(
        sensor_id=sensor_id,
        asserted=asserted,
        count=len(found),
        shortest=min(durations),
        longest=max(durations),
        mean=sum(durations, timedelta()) / len(durations),
        total=sum(durations, timedelta()),
        truncated=sum(1 for run in found if run.truncated),
    )


def bucketed_runs(
    connection: sqlite3.Connection,
    sensor_id: str,
    *,
    asserted: bool,
    interval: timedelta,
    max_gap: timedelta = DEFAULT_RUN_BREAK,
    start: datetime | None = None,
    end: datetime | None = None,
    local: bool = True,
) -> tuple[Bucket, ...]:
    """Group runs into intervals by when each one started.

    The `count` column is the answer to "how many times did it start today", and
    the value aggregated is each run's duration **in seconds**. `Bucket` carries
    no unit, so that is stated here and nowhere else can it be guessed.

    Thirty-eight starts a day against twenty-two is what short cycling looks
    like in a table.
    """

    bucket_microseconds = _bucket_microseconds(interval)
    found = runs(
        connection, sensor_id, asserted=asserted, max_gap=max_gap, start=start, end=end
    )

    return _aggregate_buckets(
        (
            (run.started_microseconds, run.started_offset_seconds, run.duration.total_seconds())
            for run in found
        ),
        bucket_microseconds,
        local=local,
    )


def _detect_runs(
    observations: Iterator[tuple[int, int, float]],
    break_microseconds: int,
) -> Iterator[Run]:
    """Walk one sensor's observations and emit each unbroken stretch."""

    building: _BuildingRun | None = None

    for microseconds, offset_seconds, value in observations:
        if building is None:
            building = _BuildingRun(value, microseconds, offset_seconds, open_start=True)
            continue

        if microseconds - building.last_microseconds > break_microseconds:
            yield building.close(open_end=True)
            building = _BuildingRun(value, microseconds, offset_seconds, open_start=True)
        elif value != building.value:
            yield building.close(open_end=False)
            building = _BuildingRun(value, microseconds, offset_seconds, open_start=False)
        else:
            building.extend(microseconds, offset_seconds)

    if building is not None:
        yield building.close(open_end=True)


class _BuildingRun:
    """A run under construction, closed once its far edge is known."""

    __slots__ = (
        "value",
        "first_microseconds",
        "first_offset_seconds",
        "last_microseconds",
        "last_offset_seconds",
        "samples",
        "open_start",
    )

    def __init__(
        self, value: float, microseconds: int, offset_seconds: int, *, open_start: bool
    ) -> None:
        self.value = value
        self.first_microseconds = microseconds
        self.first_offset_seconds = offset_seconds
        self.last_microseconds = microseconds
        self.last_offset_seconds = offset_seconds
        self.samples = 1
        self.open_start = open_start

    def extend(self, microseconds: int, offset_seconds: int) -> None:
        self.last_microseconds = microseconds
        self.last_offset_seconds = offset_seconds
        self.samples += 1

    def close(self, *, open_end: bool) -> Run:
        return Run(
            starts_at=_at_offset(self.first_microseconds, self.first_offset_seconds),
            ends_at=_at_offset(self.last_microseconds, self.last_offset_seconds),
            duration=timedelta(microseconds=self.last_microseconds - self.first_microseconds),
            samples=self.samples,
            asserted=self.value == 1,
            truncated=self.open_start or open_end,
            started_microseconds=self.first_microseconds,
            started_offset_seconds=self.first_offset_seconds,
        )


def approaches(
    connection: sqlite3.Connection,
    sensor_id: str,
    *,
    events: str,
    event_asserted: bool = True,
    edge: str = "start",
    before: timedelta = DEFAULT_APPROACH,
    after: timedelta = timedelta(0),
    minus: str | None = None,
    tolerance: timedelta = DEFAULT_PAIRING_TOLERANCE,
    max_gap: timedelta = DEFAULT_RUN_BREAK,
    start: datetime | None = None,
    end: datetime | None = None,
) -> tuple[Approach, ...]:
    """Describe what a subject was doing around each run boundary of a signal.

    The runs of `events` supply the moments; `sensor_id`, optionally `minus` a
    second sensor, supplies what is measured. With `edge="start"` the moment is
    the beginning of each run — the instant a lockout latched. With `edge="end"`
    it is the run's last observation, which is what "as each cycle finished"
    means when no fault contact exists to mark the real event.

    The window is half open, `[moment - before, moment + after)`, so the default
    `after=0` reports strictly what came **before** and excludes the moment
    itself.

    An event whose window holds no reading of the subject is left out rather
    than reported as a zero. Compare the length of the result against the number
    of events to see how many that was.

    **This describes; it does not explain.** That the delta was low before every
    lockout is a fact about the recording. Which of the two caused the other, if
    either, is not in the data.
    """

    if edge not in ("start", "end"):
        raise ReportingError(f"an approach is anchored to a run's start or end, not {edge!r}")
    if before < timedelta(0) or after < timedelta(0):
        raise ReportingError("an approach window cannot extend backwards")
    if before + after <= timedelta(0):
        raise ReportingError("an approach window of zero length selects nothing")

    found = []
    for run in runs(
        connection,
        events,
        asserted=event_asserted,
        max_gap=max_gap,
        start=start,
        end=end,
    ):
        moment = run.starts_at if edge == "start" else run.ends_at
        opens_at, closes_at = moment - before, moment + after

        summary: SensorSummary | DeltaSummary | None
        if minus is None:
            summary = summarize(connection, sensor_id, start=opens_at, end=closes_at)
        else:
            summary = delta(
                connection,
                sensor_id,
                minus=minus,
                tolerance=tolerance,
                start=opens_at,
                end=closes_at,
            )

        if summary is None:
            continue

        found.append(
            Approach(
                event_at=moment,
                count=summary.count,
                minimum=summary.minimum,
                maximum=summary.maximum,
                mean=summary.mean,
            )
        )

    return tuple(found)


def pooled_mean(found: Sequence[Approach]) -> float | None:
    """Average every reading behind a set of approaches, not the approach means.

    A mean of means silently gives an event with three readings the same weight
    as one with three hundred. Returns None when there is nothing to pool.
    """

    total = sum(approach.count for approach in found)
    if not total:
        return None
    return sum(approach.mean * approach.count for approach in found) / total


def duty_cycle(
    connection: sqlite3.Connection,
    sensor_id: str,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
) -> float | None:
    """Return the fraction of samples in which a state sensor was asserted.

    This is a ratio of **samples**, not of time. With even sampling the two
    agree; with uneven sampling they do not, and the difference is not corrected
    here because correcting it silently would hide the uneven sampling.
    """

    clauses = ["sensor_id = ?"]
    parameters: list[object] = [sensor_id]
    _append_window(clauses, parameters, start, end)

    row = connection.execute(
        f"SELECT COUNT(*), SUM(value) FROM measurements WHERE {' AND '.join(clauses)}",
        tuple(parameters),
    ).fetchone()

    count, asserted = row
    if not count:
        return None
    return float(asserted) / float(count)


class _StateGate:
    """Answers whether a state signal held an expected value at a given instant.

    Instants must be asked for in ascending order; the gate only walks forward.

    Unlike the delta pairing, a state reading is **not** consumed when used. A
    state is a level, and the same observation legitimately describes every
    moment near it. Reuse cannot inflate any statistic either, because the gate
    contributes no value — it only answers yes or no.

    What it will not do is reach further than the tolerance. Beyond that the
    signal is unobserved, and **an unobserved state admits nothing, in either
    direction.** That matters most for the inverted gate: it would be easy, and
    wrong, to read "no reading here" as "it was off", which would quietly count
    every hole in the state record as idle time.
    """

    def __init__(
        self,
        observations: Iterator[tuple[int, int, float]],
        tolerance: int,
        *,
        expected: float,
    ) -> None:
        self._observations = observations
        self._tolerance = tolerance
        self._expected = expected
        self._current = next(observations, None)
        self._upcoming = next(observations, None)

    def admits(self, microseconds: int) -> bool:
        while self._upcoming is not None and self._current is not None:
            if abs(self._upcoming[0] - microseconds) >= abs(self._current[0] - microseconds):
                break
            self._current, self._upcoming = self._upcoming, next(self._observations, None)

        if self._current is None:
            return False
        if abs(self._current[0] - microseconds) > self._tolerance:
            return False
        return self._current[2] == self._expected


def _gate(
    connection: sqlite3.Connection,
    while_asserted: str | None,
    while_not_asserted: str | None,
    tolerance: timedelta,
    start: datetime | None,
    end: datetime | None,
) -> _StateGate | None:
    """Build a gate from a state sensor, refusing anything that cannot be one.

    `while_asserted` keeps the moments the signal read 1; `while_not_asserted`
    keeps the moments it read 0 — the loop recovering between cycles rather than
    working. They are separate arguments rather than a flag, so a call site says
    which sense it means without anyone having to remember what `True` meant.
    """

    if while_asserted is not None and while_not_asserted is not None:
        raise ReportingError(
            "a report is gated on one sense or the other, not both; asking for the "
            "moments a signal was on and off at once selects nothing"
        )

    sensor_id = while_asserted if while_asserted is not None else while_not_asserted
    if sensor_id is None:
        return None

    _require_state_sensor(connection, sensor_id, start, end)

    return _StateGate(
        _observations(connection, sensor_id, start, end),
        tolerance // _MICROSECOND,
        expected=1 if while_asserted is not None else 0,
    )


def _require_state_sensor(
    connection: sqlite3.Connection,
    sensor_id: str,
    start: datetime | None,
    end: datetime | None,
) -> None:
    """Refuse anything that cannot answer whether something was running."""

    units = connection.execute(
        "SELECT DISTINCT unit FROM measurements WHERE sensor_id = ?",
        (sensor_id,),
    ).fetchall()

    if not units:
        raise ReportingError(f"{sensor_id} has no observations at all; check the name")
    if [str(unit) for (unit,) in units] != [STATE_UNIT]:
        spellings = ", ".join(sorted(str(unit) for (unit,) in units))
        raise ReportingError(
            f"{sensor_id} is recorded in {spellings}, not {STATE_UNIT}; only a state "
            "sensor can say whether something was running"
        )
    if not _sample_count(connection, sensor_id, start, end):
        raise ReportingError(
            f"{sensor_id} has no observations inside that window, so nothing can be "
            "said about what was running during it"
        )


def _pairs(
    connection: sqlite3.Connection,
    sensor_id: str,
    minus: str,
    tolerance: timedelta,
    start: datetime | None,
    end: datetime | None,
) -> Iterator[tuple[int, int, float]]:
    """Pair each observation of one sensor with the nearest of another.

    Two sensors are never read at the same instant. Each Modbus read is its own
    transaction on a half-duplex segment, so loop-in and loop-out arrive seconds
    apart and an exact-timestamp join would find nothing at all.

    The pairing is **one to one**: once a reading is used it is consumed. If one
    sensor is sampled five times as often as the other, the extra readings go
    unpaired rather than reusing a stale partner five times over — which is what
    makes the unpaired counts mean something.

    It walks both series forward once and never backtracks. That is safe as long
    as the tolerance stays under half the polling interval, because then no two
    readings of one sensor can both fall within reach of the same partner. Set
    the tolerance wider than that and a reading can be claimed by the wrong
    neighbour — which is why the default is deliberately narrow.

    Yields `(observed_at_us, observed_at_offset_s, difference)` for each pair,
    taking the timestamp and offset from `sensor_id`.
    """

    if tolerance < timedelta(0):
        raise ReportingError(f"a pairing tolerance cannot be negative, received {tolerance}")
    tolerance_microseconds = tolerance // _MICROSECOND

    left = _observations(connection, sensor_id, start, end)
    right = _observations(connection, minus, start, end)

    partner = next(right, None)
    upcoming = next(right, None)

    for microseconds, offset_seconds, value in left:
        while upcoming is not None and partner is not None:
            if abs(upcoming[0] - microseconds) >= abs(partner[0] - microseconds):
                break
            partner, upcoming = upcoming, next(right, None)

        if partner is None:
            return
        if abs(partner[0] - microseconds) <= tolerance_microseconds:
            yield microseconds, offset_seconds, value - partner[2]
            partner, upcoming = upcoming, next(right, None)


def _observations(
    connection: sqlite3.Connection,
    sensor_id: str,
    start: datetime | None,
    end: datetime | None,
) -> Iterator[tuple[int, int, float]]:
    clauses = ["sensor_id = ?"]
    parameters: list[object] = [sensor_id]
    _append_window(clauses, parameters, start, end)

    cursor = connection.execute(
        "SELECT observed_at_us, observed_at_offset_s, value FROM measurements "
        f"WHERE {' AND '.join(clauses)} ORDER BY observed_at_us",
        tuple(parameters),
    )
    for microseconds, offset_seconds, value in cursor:
        yield int(microseconds), int(offset_seconds), float(value)


def _shared_unit(
    connection: sqlite3.Connection,
    sensor_id: str,
    minus: str,
    start: datetime | None,
    end: datetime | None,
) -> str:
    """Return the unit both sensors share, or refuse the comparison."""

    if sensor_id == minus:
        raise ReportingError("a sensor cannot be compared against itself")

    clauses = ["sensor_id IN (?, ?)"]
    parameters: list[object] = [sensor_id, minus]
    _append_window(clauses, parameters, start, end)

    units = connection.execute(
        f"SELECT DISTINCT unit FROM measurements WHERE {' AND '.join(clauses)}",
        tuple(parameters),
    ).fetchall()

    if len(units) > 1:
        spellings = ", ".join(sorted(str(unit) for (unit,) in units))
        raise ReportingError(
            f"{sensor_id} and {minus} are not recorded in the same unit ({spellings}); "
            "their difference would mean nothing"
        )
    return str(units[0][0]) if units else ""


def _sample_count(
    connection: sqlite3.Connection,
    sensor_id: str,
    start: datetime | None,
    end: datetime | None,
) -> int:
    clauses = ["sensor_id = ?"]
    parameters: list[object] = [sensor_id]
    _append_window(clauses, parameters, start, end)

    (count,) = connection.execute(
        f"SELECT COUNT(*) FROM measurements WHERE {' AND '.join(clauses)}",
        tuple(parameters),
    ).fetchone()
    return int(count)


def _bucket_microseconds(interval: timedelta) -> int:
    """Validate an interval and return it in microseconds.

    An interval must either divide evenly into a day or be a whole number of
    days. That is what guarantees a bucket boundary lands on a wall-clock
    boundary: 15 minutes, an hour and six hours all do, a week does, and seven
    hours does not. Refusing seven hours costs nothing and prevents a chart whose
    buckets drift a little further from midnight every day.
    """

    microseconds = interval // _MICROSECOND
    if microseconds <= 0:
        raise ReportingError(f"a bucket interval must be positive, received {interval}")
    if _DAY_MICROSECONDS % microseconds and microseconds % _DAY_MICROSECONDS:
        raise ReportingError(
            f"a bucket interval of {interval} neither divides evenly into a day nor is "
            "a whole number of days, so its boundaries would drift away from midnight"
        )
    return microseconds


def _bucket_start(microseconds: int, *, offset_seconds: int) -> datetime:
    """Turn a bucket index back into the aware instant the interval starts at."""

    zone = timezone(timedelta(seconds=offset_seconds))
    return (_EPOCH + timedelta(microseconds=microseconds - offset_seconds * 1_000_000)).astimezone(
        zone
    )


def _require_post_epoch(
    connection: sqlite3.Connection,
    where: str,
    parameters: list[object],
    instant: str,
) -> None:
    """Refuse to bucket observations stamped before 1970.

    SQLite's integer division truncates toward zero, so a negative instant lands
    in the wrong bucket and the interval straddling the epoch comes out double
    width. Rather than carry that arithmetic, this refuses the input.

    It is not hypothetical. A Raspberry Pi with no real-time clock and no network
    boots stamping observations at the epoch, and with a western offset those
    become negative once aligned to local time. A report that refuses is more
    useful than one that quietly misplaces them, and the clock is the real
    problem either way.
    """

    (earliest,) = connection.execute(
        f"SELECT MIN({instant}) FROM measurements WHERE {where}",
        tuple(parameters),
    ).fetchone()

    if earliest is not None and earliest < 0:
        raise ReportingError(PRE_EPOCH_MESSAGE)


def _require_single_unit(
    connection: sqlite3.Connection,
    sensor_id: str,
    where: str,
    parameters: list[object],
) -> None:
    (distinct_units,) = connection.execute(
        f"SELECT COUNT(DISTINCT unit) FROM measurements WHERE {where}",
        tuple(parameters),
    ).fetchone()

    if distinct_units > 1:
        raise ReportingError(
            f"{sensor_id} was recorded in {distinct_units} different units over that "
            "window; report on a narrower window instead"
        )


def _largest_gap(connection: sqlite3.Connection, sensor_id: str) -> timedelta:
    rows = connection.execute(
        "SELECT observed_at_us FROM measurements WHERE sensor_id = ? ORDER BY observed_at_us",
        (sensor_id,),
    ).fetchall()

    largest = 0
    previous: int | None = None
    for (value,) in rows:
        current = int(value)
        if previous is not None:
            largest = max(largest, current - previous)
        previous = current
    return timedelta(microseconds=largest)


def _append_window(
    clauses: list[str],
    parameters: list[object],
    start: datetime | None,
    end: datetime | None,
) -> None:
    if start is not None:
        clauses.append("observed_at_us >= ?")
        parameters.append(epoch_microseconds(start))
    if end is not None:
        clauses.append("observed_at_us < ?")
        parameters.append(epoch_microseconds(end))


def _at_offset(microseconds: int, offset_seconds: int) -> datetime:
    """Render an instant in the wall clock that was in effect where it was taken.

    A homeowner cross-checking a lockout against their own memory of the evening
    needs the hour their clock showed, not the hour in Greenwich.
    """

    return _from_microseconds(microseconds).astimezone(
        timezone(timedelta(seconds=offset_seconds))
    )


def _from_microseconds(microseconds: int) -> datetime:
    return _EPOCH + timedelta(microseconds=microseconds)
