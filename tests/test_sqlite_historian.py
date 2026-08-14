"""SQLite-specific historian tests.

Shared behavior is covered by the parametrized contract suite in
`test_historian.py`. This file covers what only the SQLite backend can get
wrong: durability across connections, exact value and timestamp round-trips,
and schema handling.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from geopilot.domain import DataQuality, Measurement
from geopilot.historian import DuplicateMeasurementConflictError
from geopilot.sqlite_historian import (
    SCHEMA_VERSION,
    HistorianStorageError,
    SqliteMeasurementHistorian,
)

NOW = datetime(2026, 7, 21, 12, 0, 0, tzinfo=UTC)
RECEIVED = datetime(2026, 7, 21, 12, 30, 0, tzinfo=UTC)


def measurement(
    *,
    measurement_id: str = "m1",
    value: int | float = 20.0,
    observed_at: datetime = NOW,
    received_at: datetime = RECEIVED,
) -> Measurement:
    return Measurement(
        id=measurement_id,
        sensor_id="sensor_a",
        observed_at=observed_at,
        received_at=received_at,
        value=value,
        unit="degC",
        quality=DataQuality.GOOD,
        source_id="source_simulated",
    )


def test_measurements_survive_reopening_the_database(tmp_path: Path) -> None:
    database = tmp_path / "geopilot.sqlite3"
    item = measurement()

    with SqliteMeasurementHistorian(database) as historian:
        historian.append(item)

    with SqliteMeasurementHistorian(database) as reopened:
        assert reopened.count() == 1
        assert reopened.all() == (item,)
        assert reopened.latest_for_sensor("sensor_a") == item


def test_duplicate_policy_survives_reopening(tmp_path: Path) -> None:
    database = tmp_path / "geopilot.sqlite3"

    with SqliteMeasurementHistorian(database) as historian:
        historian.append(measurement(value=20))

    with SqliteMeasurementHistorian(database) as reopened:
        reopened.append(measurement(value=20))
        assert reopened.count() == 1
        with pytest.raises(DuplicateMeasurementConflictError, match="different content"):
            reopened.append(measurement(value=21))


def test_integer_and_float_values_keep_their_type() -> None:
    with SqliteMeasurementHistorian() as historian:
        historian.append(measurement(measurement_id="int", value=20))
        historian.append(measurement(measurement_id="float", value=20.5))

        stored = {item.id: item.value for item in historian.all()}

    # `20 == 20.0` in Python, so equality alone would not catch a type change.
    assert isinstance(stored["int"], int)
    assert isinstance(stored["float"], float)
    assert stored["float"] == 20.5


def test_non_utc_offset_is_preserved_exactly() -> None:
    montreal_summer = timezone(timedelta(hours=-4))
    observed_at = datetime(2026, 7, 21, 8, 0, 0, tzinfo=montreal_summer)
    item = measurement(observed_at=observed_at)

    with SqliteMeasurementHistorian() as historian:
        historian.append(item)
        stored = historian.all()[0]

    assert stored == item
    assert stored.observed_at.utcoffset() == timedelta(hours=-4)
    assert stored.observed_at.isoformat() == "2026-07-21T08:00:00-04:00"


def test_named_zone_round_trips_to_the_same_instant_and_offset() -> None:
    observed_at = datetime(2026, 7, 21, 8, 0, 0, tzinfo=ZoneInfo("America/Toronto"))
    item = measurement(observed_at=observed_at)

    with SqliteMeasurementHistorian() as historian:
        historian.append(item)
        stored = historian.all()[0]

    # The offset is preserved; the zone name is not. Aware datetimes compare by
    # instant, so the measurement still round-trips equal.
    assert stored == item
    assert stored.observed_at.utcoffset() == observed_at.utcoffset()


def test_microsecond_precision_is_preserved() -> None:
    observed_at = datetime(2026, 7, 21, 12, 0, 0, 123456, tzinfo=UTC)
    item = measurement(observed_at=observed_at)

    with SqliteMeasurementHistorian() as historian:
        historian.append(item)
        stored = historian.all()[0]

    assert stored.observed_at == observed_at
    assert stored.observed_at.microsecond == 123456


def test_schema_version_is_recorded(tmp_path: Path) -> None:
    database = tmp_path / "geopilot.sqlite3"

    with SqliteMeasurementHistorian(database):
        pass

    connection = sqlite3.connect(database)
    try:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
    finally:
        connection.close()

    assert version == SCHEMA_VERSION


def test_unsupported_schema_version_is_rejected(tmp_path: Path) -> None:
    database = tmp_path / "geopilot.sqlite3"
    connection = sqlite3.connect(database)
    try:
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(HistorianStorageError, match="unsupported schema version"):
        SqliteMeasurementHistorian(database)


def test_invalid_synchronous_mode_is_rejected() -> None:
    with pytest.raises(HistorianStorageError, match="synchronous"):
        SqliteMeasurementHistorian(synchronous="SOMETIMES")


def test_file_database_uses_write_ahead_logging(tmp_path: Path) -> None:
    database = tmp_path / "geopilot.sqlite3"

    with SqliteMeasurementHistorian(database):
        pass

    connection = sqlite3.connect(database)
    try:
        mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        connection.close()

    assert mode == "wal"


def test_backup_copies_a_consistent_snapshot_while_in_use(tmp_path: Path) -> None:
    database = tmp_path / "geopilot.sqlite3"
    backup = tmp_path / "backup.sqlite3"

    with SqliteMeasurementHistorian(database) as historian:
        historian.append(measurement(measurement_id="m1"))
        historian.append(measurement(measurement_id="m2", value=21.0))

        historian.backup(backup)

        # The snapshot must not follow later writes.
        historian.append(measurement(measurement_id="m3", value=22.0))
        assert historian.count() == 3

    with SqliteMeasurementHistorian(backup) as restored:
        assert restored.count() == 2
        assert [item.id for item in restored.all()] == ["m1", "m2"]


def test_backup_preserves_integrity_and_schema_version(tmp_path: Path) -> None:
    database = tmp_path / "geopilot.sqlite3"
    backup = tmp_path / "backup.sqlite3"

    with SqliteMeasurementHistorian(database) as historian:
        historian.append(measurement())
        historian.backup(backup)

    connection = sqlite3.connect(backup)
    try:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    finally:
        connection.close()


def test_backup_of_in_memory_database_writes_a_file(tmp_path: Path) -> None:
    backup = tmp_path / "backup.sqlite3"

    with SqliteMeasurementHistorian() as historian:
        historian.append(measurement())
        historian.backup(backup)

    assert backup.exists()
    with SqliteMeasurementHistorian(backup) as restored:
        assert restored.count() == 1


def test_close_releases_the_connection() -> None:
    historian = SqliteMeasurementHistorian()
    historian.append(measurement())
    historian.close()

    with pytest.raises(sqlite3.ProgrammingError):
        historian.count()
