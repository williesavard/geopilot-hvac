"""SQLite-backed measurement historian.

This module implements the ``MeasurementHistorian`` contract on top of the
standard-library ``sqlite3`` module, as decided in ``docs/STORAGE_ADR.md``. It
adds no third-party dependency, requires no server, and stores everything in a
single local file the homeowner can copy.

It does not aggregate, downsample, retain, expire, diagnose, alert, optimize or
control HVAC equipment. It does not know about Modbus, MQTT or any protocol.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from types import TracebackType
from typing import Any, cast

from geopilot.domain import DataQuality, Measurement, epoch_microseconds
from geopilot.historian import (
    DuplicateMeasurementConflictError,
    conflicts_with,
    require_identifier,
    sensor_ids_for_system,
    validate_window,
)
from geopilot.registry import AssetRegistry

SCHEMA_VERSION = 1
"""Schema revision stored in ``PRAGMA user_version``."""

VALID_SYNCHRONOUS_MODES = frozenset({"FULL", "EXTRA", "NORMAL", "OFF"})

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

_COLUMNS = (
    "id, sensor_id, observed_at_us, observed_at_offset_s, "
    "received_at_us, received_at_offset_s, value, unit, quality, source_id"
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS measurements (
    seq                  INTEGER PRIMARY KEY AUTOINCREMENT,
    id                   TEXT    NOT NULL UNIQUE,
    sensor_id            TEXT    NOT NULL,
    observed_at_us       INTEGER NOT NULL,
    observed_at_offset_s INTEGER NOT NULL,
    received_at_us       INTEGER NOT NULL,
    received_at_offset_s INTEGER NOT NULL,
    value                NUMERIC NOT NULL,
    unit                 TEXT    NOT NULL,
    quality              TEXT    NOT NULL,
    source_id            TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_measurements_sensor_observed
    ON measurements (sensor_id, observed_at_us);
"""


class HistorianStorageError(RuntimeError):
    """Raised when a SQLite database cannot be used as GeoPilot storage."""


class SqliteMeasurementHistorian:
    """Durable measurement historian backed by a single SQLite database.

    The default database is in-memory, so tests and examples never touch the
    filesystem unless a path is passed explicitly.
    """

    def __init__(
        self,
        database: str | Path = ":memory:",
        *,
        synchronous: str = "FULL",
    ) -> None:
        mode = synchronous.upper()
        if mode not in VALID_SYNCHRONOUS_MODES:
            raise HistorianStorageError(
                f"synchronous must be one of {sorted(VALID_SYNCHRONOUS_MODES)}"
            )

        self._connection = sqlite3.connect(str(database))
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute(f"PRAGMA synchronous={mode}")
        self._initialize_schema()

    def append(self, measurement: Measurement) -> None:
        """Store a measurement, honouring the shared duplicate policy."""

        existing = self._fetch_by_id(measurement.id)
        if existing is not None:
            if conflicts_with(existing, measurement):
                raise DuplicateMeasurementConflictError(
                    f"Measurement id already exists with different content: {measurement.id}"
                )
            return

        observed_us, observed_offset = _to_storage(measurement.observed_at)
        received_us, received_offset = _to_storage(measurement.received_at)
        with self._connection:
            self._connection.execute(
                f"INSERT INTO measurements ({_COLUMNS}) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    measurement.id,
                    measurement.sensor_id,
                    observed_us,
                    observed_offset,
                    received_us,
                    received_offset,
                    measurement.value,
                    measurement.unit,
                    measurement.quality.value,
                    measurement.source_id,
                ),
            )

    def all(self) -> tuple[Measurement, ...]:
        """Return measurements in insertion order."""

        return self._select("SELECT " + _COLUMNS + " FROM measurements ORDER BY seq", ())

    def count(self) -> int:
        """Return the number of unique measurements stored."""

        row = self._connection.execute("SELECT COUNT(*) FROM measurements").fetchone()
        return int(cast(tuple[Any, ...], row)[0])

    def latest_for_sensor(self, sensor_id: str) -> Measurement | None:
        """Return the latest measurement for a sensor, if any."""

        require_identifier(sensor_id, "sensor_id")
        row = self._connection.execute(
            f"SELECT {_COLUMNS} FROM measurements WHERE sensor_id = ? "
            "ORDER BY observed_at_us DESC, received_at_us DESC, id DESC LIMIT 1",
            (sensor_id,),
        ).fetchone()
        if row is None:
            return None
        return _row_to_measurement(cast(tuple[Any, ...], row))

    def query_sensor(
        self,
        sensor_id: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> tuple[Measurement, ...]:
        """Return measurements for one sensor within an observed_at window."""

        require_identifier(sensor_id, "sensor_id")
        validate_window(start, end)
        clauses = ["sensor_id = ?"]
        parameters: list[Any] = [sensor_id]
        _append_window(clauses, parameters, start, end)
        return self._select_where(clauses, parameters)

    def query_system(
        self,
        system_id: str,
        registry: AssetRegistry,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> tuple[Measurement, ...]:
        """Return measurements for all sensors in a system."""

        require_identifier(system_id, "system_id")
        validate_window(start, end)
        sensor_ids = sorted(sensor_ids_for_system(system_id, registry))
        if not sensor_ids:
            return ()

        placeholders = ", ".join("?" for _ in sensor_ids)
        clauses = [f"sensor_id IN ({placeholders})"]
        parameters: list[Any] = list(sensor_ids)
        _append_window(clauses, parameters, start, end)
        return self._select_where(clauses, parameters)

    def backup(self, destination: str | Path) -> None:
        """Write a consistent snapshot of the database to ``destination``.

        Safe while the historian is in use. SQLite's online backup API copies a
        consistent snapshot even with concurrent writers, which a plain file
        copy does not do under WAL journalling.
        """

        target = sqlite3.connect(str(destination))
        try:
            self._connection.backup(target)
        finally:
            target.close()

    def close(self) -> None:
        """Close the underlying SQLite connection."""

        self._connection.close()

    def __enter__(self) -> SqliteMeasurementHistorian:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def _initialize_schema(self) -> None:
        row = self._connection.execute("PRAGMA user_version").fetchone()
        version = int(cast(tuple[Any, ...], row)[0])
        if version == SCHEMA_VERSION:
            return
        if version != 0:
            raise HistorianStorageError(
                f"unsupported schema version {version}; this build expects {SCHEMA_VERSION}"
            )

        self._connection.executescript(_SCHEMA)
        self._connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        self._connection.commit()

    def _fetch_by_id(self, measurement_id: str) -> Measurement | None:
        row = self._connection.execute(
            f"SELECT {_COLUMNS} FROM measurements WHERE id = ?",
            (measurement_id,),
        ).fetchone()
        if row is None:
            return None
        return _row_to_measurement(cast(tuple[Any, ...], row))

    def _select_where(
        self,
        clauses: list[str],
        parameters: list[Any],
    ) -> tuple[Measurement, ...]:
        statement = (
            f"SELECT {_COLUMNS} FROM measurements WHERE {' AND '.join(clauses)} "
            "ORDER BY observed_at_us, received_at_us, id"
        )
        return self._select(statement, tuple(parameters))

    def _select(self, statement: str, parameters: tuple[Any, ...]) -> tuple[Measurement, ...]:
        rows = self._connection.execute(statement, parameters).fetchall()
        return tuple(_row_to_measurement(cast(tuple[Any, ...], row)) for row in rows)


def _append_window(
    clauses: list[str],
    parameters: list[Any],
    start: datetime | None,
    end: datetime | None,
) -> None:
    if start is not None:
        clauses.append("observed_at_us >= ?")
        parameters.append(epoch_microseconds(start))
    if end is not None:
        clauses.append("observed_at_us < ?")
        parameters.append(epoch_microseconds(end))


def _row_to_measurement(row: tuple[Any, ...]) -> Measurement:
    (
        measurement_id,
        sensor_id,
        observed_us,
        observed_offset,
        received_us,
        received_offset,
        value,
        unit,
        quality,
        source_id,
    ) = row
    return Measurement(
        id=cast(str, measurement_id),
        sensor_id=cast(str, sensor_id),
        observed_at=_from_storage(int(observed_us), int(observed_offset)),
        received_at=_from_storage(int(received_us), int(received_offset)),
        value=cast(int | float, value),
        unit=cast(str, unit),
        quality=DataQuality(cast(str, quality)),
        source_id=cast(str, source_id),
    )


def _to_storage(value: datetime) -> tuple[int, int]:
    """Split an aware datetime into an exact instant and its UTC offset.

    The instant is stored so rows sort and filter correctly. The offset is
    stored so the original object can be rebuilt unchanged, which the duplicate
    policy depends on.
    """

    offset = value.utcoffset()
    if offset is None:
        raise HistorianStorageError("measurement timestamps must be timezone-aware")
    return epoch_microseconds(value), int(offset.total_seconds())


def _from_storage(microseconds: int, offset_seconds: int) -> datetime:
    return (_EPOCH + timedelta(microseconds=microseconds)).astimezone(
        timezone(timedelta(seconds=offset_seconds))
    )
