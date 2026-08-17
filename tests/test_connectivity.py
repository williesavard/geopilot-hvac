"""Connectivity tests.

The case that matters most is the one coverage cannot express: a sensor the
configuration expects that has never produced a single reading.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from geopilot.connectivity import (
    ConfiguredSensor,
    Presence,
    SensorPresence,
    by_source,
    presence,
    roster_from,
)
from geopilot.domain import DataQuality, Measurement
from geopilot.reporting import open_readonly
from geopilot.sqlite_historian import SqliteMeasurementHistorian

NOW = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)


def configured(sensor_id: str, source_id: str = "source_bus") -> ConfiguredSensor:
    return ConfiguredSensor(
        sensor_id=sensor_id, name=sensor_id.title(), source_id=source_id, unit="degC"
    )


def recorded(
    tmp_path: Path,
    readings: dict[str, tuple[int, timedelta]],
    *,
    every: timedelta = timedelta(minutes=1),
) -> sqlite3.Connection:
    """Record each sensor as `count` readings ending `ago` before NOW."""

    tmp_path.mkdir(parents=True, exist_ok=True)
    database = tmp_path / "geopilot.sqlite3"
    with SqliteMeasurementHistorian(database) as historian:
        for sensor_id, (count, ago) in readings.items():
            for index in range(count):
                moment = NOW - ago - every * index
                historian.append(
                    Measurement(
                        id=f"source_bus:{sensor_id}:{index}",
                        sensor_id=sensor_id,
                        observed_at=moment,
                        received_at=moment,
                        value=2.0,
                        unit="degC",
                        quality=DataQuality.GOOD,
                        source_id="source_bus",
                    )
                )
    return open_readonly(database)


def verdict_for(
    verdicts: tuple[SensorPresence, ...], sensor_id: str
) -> SensorPresence:
    return next(item for item in verdicts if item.sensor_id == sensor_id)


def test_a_sensor_that_never_reported_is_named(tmp_path: Path) -> None:
    """Coverage cannot express this at all: no readings means no row."""

    connection = recorded(tmp_path, {"sensor_loop_in": (10, timedelta(0))})

    verdicts = presence(
        connection, (configured("sensor_loop_in"), configured("sensor_lockout")), now=NOW
    )

    absent = verdict_for(verdicts, "sensor_lockout")
    assert absent.presence is Presence.NEVER
    assert absent.count == 0
    assert absent.last_seen is None
    assert "wiring" in absent.detail


def test_a_reporting_sensor_is_live(tmp_path: Path) -> None:
    connection = recorded(tmp_path, {"sensor_loop_in": (10, timedelta(0))})

    verdicts = presence(connection, (configured("sensor_loop_in"),), now=NOW)

    assert verdicts[0].presence is Presence.LIVE
    assert verdicts[0].cadence == timedelta(minutes=1)
    assert verdicts[0].healthy


def test_lateness_is_judged_against_the_sensors_own_cadence(tmp_path: Path) -> None:
    """The same silence is nothing from a slow sensor and a fault from a fast one."""

    fast = recorded(
        tmp_path / "fast", {"sensor_a": (10, timedelta(minutes=5))}, every=timedelta(seconds=10)
    )
    slow = recorded(
        tmp_path / "slow", {"sensor_a": (10, timedelta(minutes=5))}, every=timedelta(minutes=10)
    )

    assert presence(fast, (configured("sensor_a"),), now=NOW)[0].presence is Presence.SILENT
    assert presence(slow, (configured("sensor_a"),), now=NOW)[0].presence is Presence.LIVE


def test_the_three_thresholds(tmp_path: Path) -> None:
    for ago, expected in (
        (timedelta(minutes=1), Presence.LIVE),
        (timedelta(minutes=4), Presence.LATE),
        (timedelta(minutes=20), Presence.SILENT),
    ):
        connection = recorded(tmp_path / str(ago.seconds), {"sensor_a": (10, ago)})
        assert presence(connection, (configured("sensor_a"),), now=NOW)[0].presence is expected


def test_too_few_readings_to_judge_reads_as_new(tmp_path: Path) -> None:
    """The normal state of a sensor wired ninety seconds ago."""

    connection = recorded(tmp_path, {"sensor_a": (2, timedelta(0))})

    verdict = presence(connection, (configured("sensor_a"),), now=NOW)[0]

    assert verdict.presence is Presence.NEW
    assert verdict.cadence is None
    assert verdict.healthy


def test_a_reading_stamped_in_the_future_is_flagged(tmp_path: Path) -> None:
    """A negative age would otherwise read as impossibly fresh."""

    connection = recorded(tmp_path, {"sensor_a": (10, -timedelta(hours=2))})

    verdict = presence(connection, (configured("sensor_a"),), now=NOW)[0]

    assert verdict.presence is Presence.LATE
    assert "in the future" in verdict.detail
    assert "clock" in verdict.detail


def test_small_clock_drift_is_tolerated(tmp_path: Path) -> None:
    connection = recorded(tmp_path, {"sensor_a": (10, -timedelta(seconds=30))})

    assert presence(connection, (configured("sensor_a"),), now=NOW)[0].presence is Presence.LIVE


def test_data_without_a_configuration_entry_is_named(tmp_path: Path) -> None:
    connection = recorded(tmp_path, {"sensor_orphan": (10, timedelta(0))})

    verdicts = presence(connection, (configured("sensor_loop_in"),), now=NOW)

    orphan = verdict_for(verdicts, "sensor_orphan")
    assert orphan.presence is Presence.UNCONFIGURED
    assert not orphan.healthy


def test_a_whole_dead_bus_reads_as_one_fault(tmp_path: Path) -> None:
    """Six red rows on one adapter is one unplugged cable, not six faults."""

    connection = recorded(
        tmp_path,
        {"sensor_a": (10, timedelta(hours=3)), "sensor_b": (10, timedelta(hours=3))},
    )

    verdicts = presence(
        connection,
        (configured("sensor_a", "source_relay"), configured("sensor_b", "source_relay")),
        now=NOW,
    )
    buses = by_source(verdicts)

    assert len(buses) == 1
    assert buses[0].presence is Presence.SILENT
    assert buses[0].healthy == 0
    assert "suspect the bus" in buses[0].detail


def test_one_quiet_sensor_among_several_is_not_a_dead_bus(tmp_path: Path) -> None:
    connection = recorded(
        tmp_path,
        {"sensor_a": (10, timedelta(0)), "sensor_b": (10, timedelta(hours=3))},
    )

    buses = by_source(
        presence(
            connection,
            (configured("sensor_a", "source_bus"), configured("sensor_b", "source_bus")),
            now=NOW,
        )
    )

    assert buses[0].presence is Presence.LATE
    assert buses[0].healthy == 1
    assert "1 of 2 quiet" in buses[0].detail


def test_a_bus_that_never_worked_says_so(tmp_path: Path) -> None:
    """Never having worked and having stopped call for different checks."""

    connection = recorded(tmp_path, {"sensor_other": (10, timedelta(0))})

    buses = by_source(
        presence(
            connection,
            (configured("sensor_a", "source_new"), configured("sensor_b", "source_new")),
            now=NOW,
        )
    )

    dead = next(bus for bus in buses if bus.source_id == "source_new")
    assert dead.presence is Presence.NEVER
    assert "ever reported" in dead.detail


def test_an_unconfigured_sensor_does_not_drag_a_bus_down(tmp_path: Path) -> None:
    """It belongs to no configured bus, so it cannot be evidence about one."""

    connection = recorded(
        tmp_path,
        {"sensor_a": (10, timedelta(0)), "sensor_orphan": (10, timedelta(hours=5))},
    )

    buses = by_source(presence(connection, (configured("sensor_a"),), now=NOW))

    assert len(buses) == 1
    assert buses[0].presence is Presence.LIVE


def test_the_roster_comes_from_the_configured_sensors() -> None:
    class Fake:
        sensors = (
            type(
                "S",
                (),
                {"id": "sensor_a", "name": "A", "source_id": "source_bus", "unit": "degC"},
            )(),
        )

    roster = roster_from(Fake())

    assert roster == (
        ConfiguredSensor(sensor_id="sensor_a", name="A", source_id="source_bus", unit="degC"),
    )


def test_an_empty_roster_still_names_orphans(tmp_path: Path) -> None:
    connection = recorded(tmp_path, {"sensor_a": (10, timedelta(0))})

    verdicts = presence(connection, (), now=NOW)

    assert len(verdicts) == 1
    assert verdicts[0].presence is Presence.UNCONFIGURED
