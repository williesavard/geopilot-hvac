"""In-memory measurement history for GeoPilot.

The historian keeps normalized domain ``Measurement`` objects in memory and
offers deterministic time-window queries. It is not persistent storage and it
does not calculate aggregates, diagnostics, COP, alerts, optimization, or
equipment control.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import fields
from datetime import datetime
from typing import Protocol

from geopilot.domain import Measurement
from geopilot.registry import AssetRegistry

UNCOMPARED_IDENTITY_FIELDS = frozenset({"received_at"})
"""Measurement fields excluded when deciding whether two rows conflict."""


class HistorianQueryError(ValueError):
    """Raised when a historian query is invalid."""


class DuplicateMeasurementConflictError(ValueError):
    """Raised when a measurement id is reused with different content."""


class MeasurementHistorian(Protocol):
    """Storage-independent historian contract for normalized measurements."""

    def append(self, measurement: Measurement) -> None:
        """Add a measurement to history."""

    def all(self) -> tuple[Measurement, ...]:
        """Return measurements in insertion order."""

    def count(self) -> int:
        """Return the number of unique measurements stored."""

    def latest_for_sensor(self, sensor_id: str) -> Measurement | None:
        """Return the latest measurement for a sensor, if any."""

    def query_sensor(
        self,
        sensor_id: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> tuple[Measurement, ...]:
        """Return measurements for one sensor within an observed_at window."""

    def query_system(
        self,
        system_id: str,
        registry: AssetRegistry,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> tuple[Measurement, ...]:
        """Return measurements for all sensors in a system."""


class InMemoryMeasurementHistorian:
    """Insertion-preserving in-memory measurement historian."""

    def __init__(self) -> None:
        self._measurements: list[Measurement] = []
        self._by_id: dict[str, Measurement] = {}

    def append(self, measurement: Measurement) -> None:
        existing = self._by_id.get(measurement.id)
        if existing is not None:
            if conflicts_with(existing, measurement):
                raise DuplicateMeasurementConflictError(
                    f"Measurement id already exists with different content: {measurement.id}"
                )
            return

        self._measurements.append(measurement)
        self._by_id[measurement.id] = measurement

    def all(self) -> tuple[Measurement, ...]:
        return tuple(self._measurements)

    def count(self) -> int:
        return len(self._measurements)

    def latest_for_sensor(self, sensor_id: str) -> Measurement | None:
        require_identifier(sensor_id, "sensor_id")
        matches = (item for item in self._measurements if item.sensor_id == sensor_id)
        return max(matches, key=measurement_sort_key, default=None)

    def query_sensor(
        self,
        sensor_id: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> tuple[Measurement, ...]:
        require_identifier(sensor_id, "sensor_id")
        validate_window(start, end)
        return _sort_measurements(
            item
            for item in self._measurements
            if item.sensor_id == sensor_id and _in_window(item, start, end)
        )

    def query_system(
        self,
        system_id: str,
        registry: AssetRegistry,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> tuple[Measurement, ...]:
        require_identifier(system_id, "system_id")
        validate_window(start, end)
        sensor_ids = sensor_ids_for_system(system_id, registry)
        return _sort_measurements(
            item
            for item in self._measurements
            if item.sensor_id in sensor_ids and _in_window(item, start, end)
        )


def conflicts_with(existing: Measurement, incoming: Measurement) -> bool:
    """Return True when two measurements sharing an id disagree about the observation.

    `received_at` records when GeoPilot learned of a measurement, not what was
    measured, so it is excluded. Two ingestions of the same observation are the
    same observation arriving twice, which must stay idempotent even when the
    clock has moved. Every other field is compared, including any field added to
    `Measurement` later. See `docs/MEASUREMENT_ID_ADR.md`.
    """

    return any(
        getattr(existing, item.name) != getattr(incoming, item.name)
        for item in fields(Measurement)
        if item.name not in UNCOMPARED_IDENTITY_FIELDS
    )


def sensor_ids_for_system(system_id: str, registry: AssetRegistry) -> frozenset[str]:
    """Return the sensor ids belonging to one HVAC system.

    Shared by every historian implementation so hierarchy resolution stays in
    the registry and out of storage code.
    """

    registry.get_hvac_system(system_id)
    sensor_ids: set[str] = set()
    for equipment in registry.list_equipment_for_system(system_id):
        for sensor in registry.list_sensors_for_equipment(equipment.id):
            sensor_ids.add(sensor.id)
    return frozenset(sensor_ids)


def require_identifier(value: str, field_name: str) -> None:
    """Reject a blank query identifier with `HistorianQueryError`."""

    if not value.strip():
        raise HistorianQueryError(f"{field_name} must be a non-empty identifier")


def _require_aware_datetime(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise HistorianQueryError(f"{field_name} must be timezone-aware")


def validate_window(start: datetime | None, end: datetime | None) -> None:
    """Validate half-open query bounds shared by every historian."""

    if start is not None:
        _require_aware_datetime(start, "start")
    if end is not None:
        _require_aware_datetime(end, "end")
    if start is not None and end is not None and start > end:
        raise HistorianQueryError("start must be before or equal to end")


def _in_window(
    measurement: Measurement,
    start: datetime | None,
    end: datetime | None,
) -> bool:
    if start is not None and measurement.observed_at < start:
        return False
    return not (end is not None and measurement.observed_at >= end)


def measurement_sort_key(measurement: Measurement) -> tuple[datetime, datetime, str]:
    """Return the canonical ordering key: observed, then received, then id."""

    return (measurement.observed_at, measurement.received_at, measurement.id)


def _sort_measurements(measurements: Iterable[Measurement]) -> tuple[Measurement, ...]:
    return tuple(sorted(measurements, key=measurement_sort_key))
