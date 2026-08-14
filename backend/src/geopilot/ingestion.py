"""In-memory measurement ingestion for GeoPilot.

The ingestion layer accepts raw simulated or adapter-produced values,
normalizes only explicitly supported units, validates the result through the
domain model, and writes measurements to a sink.

This module intentionally contains no Modbus, MQTT, BACnet, ESPHome, Home
Assistant, HTTP, database, queue, async, thread, AI, alert, COP, or equipment
control logic.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from math import isfinite
from types import MappingProxyType
from typing import Protocol, TypeAlias

from geopilot.domain import (
    DataQuality,
    Measurement,
    Sensor,
    SensorMeasurementKind,
    epoch_microseconds,
)
from geopilot.registry import AssetRegistry


class IngestionError(ValueError):
    """Raised when raw input cannot be safely normalized."""


class IncompatibleMeasurementUnitError(ValueError):
    """Raised when a unit is unsupported for a sensor capability."""


MetadataValue: TypeAlias = str | int | float | bool | None
Metadata: TypeAlias = MappingProxyType[str, MetadataValue]
Clock: TypeAlias = Callable[[], datetime]


def utc_now() -> datetime:
    """Return the current UTC time."""

    return datetime.now(UTC)


def _require_identifier(value: str, field_name: str) -> None:
    if not value.strip():
        raise IngestionError(f"{field_name} must be a non-empty identifier")


def _require_aware_datetime(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise IngestionError(f"{field_name} must be timezone-aware")


def _require_numeric(value: object, field_name: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise IngestionError(f"{field_name} must be numeric")

    if not isfinite(value):
        raise IngestionError(f"{field_name} must be finite")

    return value


def _freeze_metadata(
    metadata: dict[str, MetadataValue] | None,
) -> Metadata:
    if metadata is None:
        return MappingProxyType({})

    return MappingProxyType(dict(metadata))


@dataclass(frozen=True, slots=True, init=False)
class RawMeasurement:
    """Neutral incoming measurement before normalization."""

    source_id: str
    sensor_id: str
    value: int | float
    unit: str
    timestamp: datetime
    quality: DataQuality = DataQuality.GOOD
    metadata: Metadata = field(default_factory=lambda: MappingProxyType({}))

    def __init__(
        self,
        *,
        source_id: str,
        sensor_id: str,
        value: int | float,
        unit: str,
        timestamp: datetime,
        quality: DataQuality = DataQuality.GOOD,
        metadata: dict[str, MetadataValue] | None = None,
    ) -> None:
        _require_identifier(source_id, "source_id")
        _require_identifier(sensor_id, "sensor_id")
        _require_identifier(unit, "unit")
        _require_aware_datetime(timestamp, "timestamp")
        _require_numeric(value, "value")

        object.__setattr__(self, "source_id", source_id)
        object.__setattr__(self, "sensor_id", sensor_id)
        object.__setattr__(self, "value", value)
        object.__setattr__(self, "unit", unit)
        object.__setattr__(self, "timestamp", timestamp)
        object.__setattr__(self, "quality", quality)
        object.__setattr__(self, "metadata", _freeze_metadata(metadata))


@dataclass(frozen=True, slots=True)
class NormalizedUnit:
    """Result of a supported unit normalization."""

    value: int | float
    unit: str


class MeasurementNormalizer:
    """Convert raw measurements into validated domain measurements."""

    def __init__(self, clock: Clock = utc_now) -> None:
        self._clock = clock

    def normalize(self, raw: RawMeasurement, sensor: Sensor | None = None) -> Measurement:
        normalized = self._normalize_unit(raw.value, raw.unit, sensor)
        received_at = self._clock()

        return Measurement(
            id=self._measurement_id(raw),
            sensor_id=raw.sensor_id,
            observed_at=raw.timestamp,
            received_at=received_at,
            value=normalized.value,
            unit=normalized.unit,
            quality=raw.quality,
            source_id=raw.source_id,
        )

    def _normalize_unit(
        self,
        value: int | float,
        unit: str,
        sensor: Sensor | None,
    ) -> NormalizedUnit:
        if sensor is None:
            return self._normalize_without_sensor(value, unit)

        if sensor.sensor_kind is SensorMeasurementKind.TEMPERATURE:
            return self._normalize_temperature(value, unit)
        if sensor.sensor_kind is SensorMeasurementKind.RELATIVE_HUMIDITY:
            return self._normalize_relative_humidity(value, unit)
        if sensor.sensor_kind is SensorMeasurementKind.POWER:
            return self._normalize_power(value, unit)

        raise IncompatibleMeasurementUnitError(
            f"Sensor {sensor.id} does not declare a supported measurement capability"
        )

    def _normalize_without_sensor(self, value: int | float, unit: str) -> NormalizedUnit:
        if unit in {"degC", "°C", "degF", "°F"}:
            return self._normalize_temperature(value, unit)
        if unit == "%":
            return self._normalize_relative_humidity(value, unit)
        if unit in {"W", "kW"}:
            return self._normalize_power(value, unit)

        raise IngestionError(f"Unsupported unit: {unit}")

    def _normalize_temperature(self, value: int | float, unit: str) -> NormalizedUnit:
        match unit:
            case "degC" | "°C":
                return NormalizedUnit(value=value, unit="degC")
            case "degF" | "°F":
                return NormalizedUnit(value=(value - 32) * 5 / 9, unit="degC")
            case _:
                raise IncompatibleMeasurementUnitError(
                    f"Unit {unit} is incompatible with temperature sensors"
                )

    def _normalize_relative_humidity(self, value: int | float, unit: str) -> NormalizedUnit:
        if unit == "%":
            return NormalizedUnit(value=value, unit="%")

        raise IncompatibleMeasurementUnitError(
            f"Unit {unit} is incompatible with relative humidity sensors"
        )

    def _normalize_power(self, value: int | float, unit: str) -> NormalizedUnit:
        match unit:
            case "W":
                return NormalizedUnit(value=value, unit="W")
            case "kW":
                return NormalizedUnit(value=value * 1000, unit="W")
            case _:
                raise IncompatibleMeasurementUnitError(
                    f"Unit {unit} is incompatible with power sensors"
                )

    def _measurement_id(self, raw: RawMeasurement) -> str:
        """Build the identity of one observation.

        Identity is the coordinates of an observation, not the observation
        itself: one source, one sensor, one instant. The value is deliberately
        absent so that two different values for the same coordinates collide and
        are reported as a conflict instead of being stored as unrelated
        measurements. See `docs/MEASUREMENT_ID_ADR.md`.
        """

        return f"{raw.source_id}:{raw.sensor_id}:{epoch_microseconds(raw.timestamp)}"


class MeasurementSink(Protocol):
    """Storage-independent measurement sink contract."""

    def append(self, measurement: Measurement) -> None:
        """Write a normalized measurement."""


class InMemoryMeasurementSink:
    """Insertion-ordered in-memory measurement sink."""

    def __init__(self) -> None:
        self._measurements: list[Measurement] = []

    def append(self, measurement: Measurement) -> None:
        self._measurements.append(measurement)

    def all(self) -> tuple[Measurement, ...]:
        return tuple(self._measurements)

    def latest_for_sensor(self, sensor_id: str) -> Measurement | None:
        _require_identifier(sensor_id, "sensor_id")

        for measurement in reversed(self._measurements):
            if measurement.sensor_id == sensor_id:
                return measurement

        return None

    def count(self) -> int:
        return len(self._measurements)


class IngestionService:
    """Normalize raw measurements and write them to a sink."""

    def __init__(
        self,
        normalizer: MeasurementNormalizer,
        sink: MeasurementSink,
        registry: AssetRegistry | None = None,
    ) -> None:
        self._normalizer = normalizer
        self._sink = sink
        self._registry = registry

    def ingest(self, raw: RawMeasurement) -> Measurement:
        sensor = (
            self._registry.get_sensor(raw.sensor_id)
            if self._registry is not None
            else None
        )
        measurement = self._normalizer.normalize(raw, sensor)
        self._sink.append(measurement)
        return measurement
