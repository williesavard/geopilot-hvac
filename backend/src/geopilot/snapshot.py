"""Current-state projections for GeoPilot measurements.

Snapshots are read models built from existing domain assets and measurements.
They contain observations only: no diagnostics, alerts, COP calculation,
optimization, or equipment control.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol

from geopilot.domain import DataQuality, Measurement, SensorMeasurementKind
from geopilot.ingestion import Clock, MeasurementSink, utc_now
from geopilot.registry import AssetRegistry, InvalidAssetRelationshipError


def _serialize_value(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value

    if isinstance(value, datetime):
        if value.tzinfo is UTC or value.utcoffset() == UTC.utcoffset(value):
            return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
        return value.isoformat()

    if isinstance(value, tuple):
        return [_serialize_value(item) for item in value]

    if hasattr(value, "to_dict"):
        return value.to_dict()

    return value


def _dataclass_to_dict(instance: Any) -> dict[str, Any]:
    return {
        field.name: _serialize_value(getattr(instance, field.name))
        for field in fields(instance)
    }


@dataclass(frozen=True, slots=True)
class SensorSnapshot:
    """Current observation for a sensor."""

    sensor_id: str
    sensor_kind: SensorMeasurementKind
    value: int | float
    unit: str
    observed_at: datetime
    quality: DataQuality
    measurement_id: str

    def to_dict(self) -> dict[str, Any]:
        return _dataclass_to_dict(self)


@dataclass(frozen=True, slots=True)
class EquipmentSnapshot:
    """Current observations grouped by equipment."""

    equipment_id: str
    name: str
    sensors: tuple[SensorSnapshot, ...]

    def to_dict(self) -> dict[str, Any]:
        return _dataclass_to_dict(self)


@dataclass(frozen=True, slots=True)
class GeothermalSnapshot:
    """Read-only current observation snapshot for one simulated geothermal system."""

    residence_id: str
    system_id: str
    generated_at: datetime
    equipment: tuple[EquipmentSnapshot, ...]

    def to_dict(self) -> dict[str, Any]:
        return _dataclass_to_dict(self)


class MeasurementReader(MeasurementSink, Protocol):
    """Measurement sink that also supports read access for projection."""

    def all(self) -> tuple[Measurement, ...]:
        """Return all measurements in insertion order."""


class CurrentStateProjector:
    """Build deterministic current-state snapshots from registry and measurements."""

    def __init__(
        self,
        registry: AssetRegistry,
        measurements: MeasurementReader,
        clock: Clock = utc_now,
    ) -> None:
        self._registry = registry
        self._measurements = measurements
        self._clock = clock

    def project(self, *, residence_id: str, system_id: str) -> GeothermalSnapshot:
        residence = self._registry.get_residence(residence_id)
        system = self._registry.get_hvac_system(system_id)
        if system.residence_id != residence.id:
            raise InvalidAssetRelationshipError(
                f"HVAC system {system.id} does not belong to residence {residence.id}"
            )

        latest_by_sensor = self._latest_measurements_by_sensor()
        equipment_snapshots: list[EquipmentSnapshot] = []

        for equipment in self._registry.list_equipment_for_system(system.id):
            sensor_snapshots: list[SensorSnapshot] = []
            for sensor in self._registry.list_sensors_for_equipment(equipment.id):
                measurement = latest_by_sensor.get(sensor.id)
                if measurement is None:
                    continue
                if sensor.sensor_kind is None:
                    continue
                sensor_snapshots.append(
                    SensorSnapshot(
                        sensor_id=sensor.id,
                        sensor_kind=sensor.sensor_kind,
                        value=measurement.value,
                        unit=measurement.unit,
                        observed_at=measurement.observed_at,
                        quality=measurement.quality,
                        measurement_id=measurement.id,
                    )
                )

            equipment_snapshots.append(
                EquipmentSnapshot(
                    equipment_id=equipment.id,
                    name=equipment.name,
                    sensors=tuple(sensor_snapshots),
                )
            )

        return GeothermalSnapshot(
            residence_id=residence.id,
            system_id=system.id,
            generated_at=self._clock(),
            equipment=tuple(equipment_snapshots),
        )

    def _latest_measurements_by_sensor(self) -> dict[str, Measurement]:
        latest: dict[str, Measurement] = {}

        for measurement in self._measurements.all():
            current = latest.get(measurement.sensor_id)
            if (
                current is None
                or self._measurement_sort_key(measurement)
                > self._measurement_sort_key(current)
            ):
                latest[measurement.sensor_id] = measurement

        return latest

    def _measurement_sort_key(
        self,
        measurement: Measurement,
    ) -> tuple[datetime, datetime, str]:
        return (measurement.observed_at, measurement.received_at, measurement.id)
