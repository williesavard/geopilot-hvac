"""Reporting tests.

Every test writes a real database through the historian rather than inserting
SQL directly, so the reports are proven against the schema the recorder
actually produces.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from geopilot.domain import DataQuality, Measurement
from geopilot.reporting import (
    ReportingError,
    coverage,
    duty_cycle,
    open_readonly,
    summarize,
)
from geopilot.sqlite_historian import SqliteMeasurementHistorian

START = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)


def measurement(
    *,
    index: int,
    sensor_id: str = "sensor_loop_in",
    value: int | float = 20.0,
    unit: str = "degC",
    observed_at: datetime | None = None,
) -> Measurement:
    moment = observed_at if observed_at is not None else START + timedelta(minutes=index)
    return Measurement(
        id=f"source_bus:{sensor_id}:{index}",
        sensor_id=sensor_id,
        observed_at=moment,
        received_at=moment,
        value=value,
        unit=unit,
        quality=DataQuality.GOOD,
        source_id="source_bus",
    )


def recorded(tmp_path: Path, measurements: list[Measurement]) -> sqlite3.Connection:
    database = tmp_path / "geopilot.sqlite3"
    with SqliteMeasurementHistorian(database) as historian:
        for item in measurements:
            historian.append(item)
    return open_readonly(database)


def test_a_missing_database_is_refused_rather_than_created(tmp_path: Path) -> None:
    """Reporting on a path that does not exist must not create an empty one."""

    absent = tmp_path / "nothing.sqlite3"

    with pytest.raises(ReportingError, match="not found"):
        open_readonly(absent)

    assert not absent.exists()


def test_the_connection_cannot_write(tmp_path: Path) -> None:
    connection = recorded(tmp_path, [measurement(index=0)])

    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        connection.execute("DELETE FROM measurements")


def test_coverage_reports_one_row_per_sensor(tmp_path: Path) -> None:
    connection = recorded(
        tmp_path,
        [
            measurement(index=0, sensor_id="sensor_loop_in"),
            measurement(index=1, sensor_id="sensor_loop_in"),
            measurement(index=2, sensor_id="sensor_loop_out"),
        ],
    )

    reports = coverage(connection)

    assert [report.sensor_id for report in reports] == [
        "sensor_loop_in",
        "sensor_loop_out",
    ]
    assert reports[0].count == 2
    assert reports[1].count == 1


def test_coverage_reports_the_recorded_span(tmp_path: Path) -> None:
    connection = recorded(
        tmp_path,
        [measurement(index=0), measurement(index=60)],
    )

    report = coverage(connection)[0]

    assert report.first_observed_at == START
    assert report.last_observed_at == START + timedelta(minutes=60)
    assert report.span == timedelta(hours=1)


def test_coverage_finds_the_gap_a_total_count_hides(tmp_path: Path) -> None:
    """Three days of silence leaves a healthy-looking count. The gap is the tell."""

    connection = recorded(
        tmp_path,
        [
            measurement(index=0),
            measurement(index=1),
            measurement(index=2, observed_at=START + timedelta(days=3)),
            measurement(index=3, observed_at=START + timedelta(days=3, minutes=1)),
        ],
    )

    report = coverage(connection)[0]

    assert report.count == 4
    assert report.largest_gap == timedelta(days=3) - timedelta(minutes=1)


def test_a_single_observation_has_no_gap(tmp_path: Path) -> None:
    connection = recorded(tmp_path, [measurement(index=0)])

    assert coverage(connection)[0].largest_gap == timedelta(0)


def test_coverage_of_an_empty_database_is_empty(tmp_path: Path) -> None:
    connection = recorded(tmp_path, [])

    assert coverage(connection) == ()


def test_summary_reports_the_statistics(tmp_path: Path) -> None:
    connection = recorded(
        tmp_path,
        [
            measurement(index=0, value=10.0),
            measurement(index=1, value=20.0),
            measurement(index=2, value=30.0),
        ],
    )

    summary = summarize(connection, "sensor_loop_in")

    assert summary is not None
    assert (summary.count, summary.minimum, summary.maximum, summary.mean) == (
        3,
        10.0,
        30.0,
        20.0,
    )
    assert summary.unit == "degC"


def test_the_window_start_is_inclusive_and_the_end_exclusive(tmp_path: Path) -> None:
    """A half-open window lets consecutive days tile without double counting."""

    connection = recorded(
        tmp_path,
        [
            measurement(index=0, value=1.0),
            measurement(index=1, value=2.0),
            measurement(index=2, value=3.0),
        ],
    )

    summary = summarize(
        connection,
        "sensor_loop_in",
        start=START + timedelta(minutes=1),
        end=START + timedelta(minutes=2),
    )

    assert summary is not None
    assert summary.count == 1
    assert summary.mean == 2.0


def test_an_empty_window_reports_nothing_rather_than_zero(tmp_path: Path) -> None:
    """Zero samples and a mean of zero are different facts."""

    connection = recorded(tmp_path, [measurement(index=0)])

    assert summarize(connection, "sensor_loop_in", start=START + timedelta(days=1)) is None


def test_an_unknown_sensor_reports_nothing(tmp_path: Path) -> None:
    connection = recorded(tmp_path, [measurement(index=0)])

    assert summarize(connection, "sensor_absent") is None


def test_a_summary_covers_only_the_named_sensor(tmp_path: Path) -> None:
    connection = recorded(
        tmp_path,
        [
            measurement(index=0, sensor_id="sensor_loop_in", value=10.0),
            measurement(index=1, sensor_id="sensor_loop_out", value=1000.0),
        ],
    )

    summary = summarize(connection, "sensor_loop_in")

    assert summary is not None
    assert summary.maximum == 10.0


def test_mixed_units_are_refused_rather_than_averaged(tmp_path: Path) -> None:
    """An average of Celsius and Fahrenheit is a number with no meaning."""

    connection = recorded(
        tmp_path,
        [
            measurement(index=0, value=20.0, unit="degC"),
            measurement(index=1, value=68.0, unit="degF"),
        ],
    )

    with pytest.raises(ReportingError, match="different units"):
        summarize(connection, "sensor_loop_in")


def test_a_narrower_window_can_avoid_the_unit_change(tmp_path: Path) -> None:
    connection = recorded(
        tmp_path,
        [
            measurement(index=0, value=20.0, unit="degC"),
            measurement(index=1, value=68.0, unit="degF"),
        ],
    )

    summary = summarize(connection, "sensor_loop_in", end=START + timedelta(minutes=1))

    assert summary is not None
    assert summary.unit == "degC"


def test_duty_cycle_is_the_asserted_fraction(tmp_path: Path) -> None:
    connection = recorded(
        tmp_path,
        [
            measurement(index=0, sensor_id="sensor_zone_1", value=1, unit="state"),
            measurement(index=1, sensor_id="sensor_zone_1", value=0, unit="state"),
            measurement(index=2, sensor_id="sensor_zone_1", value=1, unit="state"),
            measurement(index=3, sensor_id="sensor_zone_1", value=0, unit="state"),
        ],
    )

    assert duty_cycle(connection, "sensor_zone_1") == 0.5


def test_a_state_never_asserted_has_a_duty_cycle_of_zero(tmp_path: Path) -> None:
    """Zero is a result. It is not the same as no samples."""

    connection = recorded(
        tmp_path,
        [measurement(index=0, sensor_id="sensor_zone_4", value=0, unit="state")],
    )

    assert duty_cycle(connection, "sensor_zone_4") == 0.0


def test_duty_cycle_without_samples_is_none(tmp_path: Path) -> None:
    connection = recorded(tmp_path, [measurement(index=0)])

    assert duty_cycle(connection, "sensor_zone_1") is None


def test_duty_cycle_honours_the_window(tmp_path: Path) -> None:
    connection = recorded(
        tmp_path,
        [
            measurement(index=0, sensor_id="sensor_zone_1", value=1, unit="state"),
            measurement(index=1, sensor_id="sensor_zone_1", value=0, unit="state"),
            measurement(index=2, sensor_id="sensor_zone_1", value=0, unit="state"),
        ],
    )

    assert duty_cycle(connection, "sensor_zone_1", start=START + timedelta(minutes=1)) == 0.0


def test_a_report_can_be_produced_while_recording_continues(tmp_path: Path) -> None:
    """WAL permits concurrent readers, which is what makes a live check possible."""

    database = tmp_path / "geopilot.sqlite3"

    with SqliteMeasurementHistorian(database) as historian:
        historian.append(measurement(index=0))

        with closing(open_readonly(database)) as reader:
            assert coverage(reader)[0].count == 1

        historian.append(measurement(index=1))

        with closing(open_readonly(database)) as reader:
            assert coverage(reader)[0].count == 2
