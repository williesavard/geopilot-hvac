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
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from geopilot.domain import epoch_microseconds

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_MICROSECOND = timedelta(microseconds=1)
_DAY_MICROSECONDS = 86_400_000_000


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
class SensorSummary:
    """Descriptive statistics for one sensor over a window."""

    sensor_id: str
    unit: str
    count: int
    minimum: float
    maximum: float
    mean: float


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
    start: datetime | None = None,
    end: datetime | None = None,
) -> SensorSummary | None:
    """Return count, minimum, maximum and mean for one sensor.

    Returns None when the window holds no samples, rather than inventing zeros.

    Raises `ReportingError` if the window mixes units for one sensor. An average
    of Celsius and Fahrenheit is a number with no meaning, and producing one
    quietly would be worse than refusing.
    """


    clauses = ["sensor_id = ?"]
    parameters: list[object] = [sensor_id]
    _append_window(clauses, parameters, start, end)
    where = " AND ".join(clauses)

    _require_single_unit(connection, sensor_id, where, parameters)

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
    )


def bucketed(
    connection: sqlite3.Connection,
    sensor_id: str,
    *,
    interval: timedelta,
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
    """

    bucket_microseconds = _bucket_microseconds(interval)

    clauses = ["sensor_id = ?"]
    parameters: list[object] = [sensor_id]
    _append_window(clauses, parameters, start, end)
    where = " AND ".join(clauses)

    _require_single_unit(connection, sensor_id, where, parameters)

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
        raise ReportingError(
            "that window contains observations stamped before 1970, which cannot be "
            "bucketed; the recording host's clock was almost certainly unset"
        )


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


def _from_microseconds(microseconds: int) -> datetime:
    return _EPOCH + timedelta(microseconds=microseconds)
