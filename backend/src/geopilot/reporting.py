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
from datetime import UTC, datetime, timedelta
from pathlib import Path

from geopilot.domain import epoch_microseconds

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


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

    row = connection.execute(
        "SELECT unit, COUNT(*), MIN(value), MAX(value), AVG(value), COUNT(DISTINCT unit) "
        f"FROM measurements WHERE {where}",
        tuple(parameters),
    ).fetchone()

    unit, count, minimum, maximum, mean, distinct_units = row
    if not count:
        return None
    if distinct_units > 1:
        raise ReportingError(
            f"{sensor_id} was recorded in {distinct_units} different units over that "
            "window; summarize a narrower window instead"
        )

    return SensorSummary(
        sensor_id=sensor_id,
        unit=str(unit),
        count=int(count),
        minimum=float(minimum),
        maximum=float(maximum),
        mean=float(mean),
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
