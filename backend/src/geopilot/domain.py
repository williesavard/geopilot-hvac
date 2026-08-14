"""Core GeoPilot domain model.

This module implements the minimal read-only HVAC data model documented in
``docs/DATA_MODEL.md`` and ``docs/API.md``. It intentionally contains no
hardware access, protocol adapters, storage engine, HTTP API, message broker,
analytics, geothermal calculations, or equipment-control logic.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_MICROSECOND = timedelta(microseconds=1)


class GeoPilotDomainError(ValueError):
    """Raised when a domain object violates the documented model."""


class SystemType(StrEnum):
    """Generic HVAC system types."""

    FORCED_AIR = "forced_air"
    HYDRONIC = "hydronic"
    HYBRID = "hybrid"
    UNKNOWN = "unknown"


class EquipmentType(StrEnum):
    """Generic equipment types."""

    HEAT_PUMP = "heat_pump"
    THERMOSTAT = "thermostat"
    METER = "meter"
    CONTROLLER = "controller"
    SENSOR_HUB = "sensor_hub"
    UNKNOWN = "unknown"


class MeasurementKind(StrEnum):
    """Generic measurement kinds."""

    TEMPERATURE = "temperature"
    POWER = "power"
    ENERGY = "energy"
    FLOW = "flow"
    PRESSURE = "pressure"
    HUMIDITY = "humidity"
    RUNTIME = "runtime"
    MODE = "mode"
    UNKNOWN = "unknown"


class SensorMeasurementKind(StrEnum):
    """MVP sensor capabilities used for unit compatibility checks."""

    TEMPERATURE = "temperature"
    RELATIVE_HUMIDITY = "relative_humidity"
    POWER = "power"


class SourceType(StrEnum):
    """Source types from the minimal model."""

    SIMULATOR = "simulator"
    FIRMWARE = "firmware"
    HOME_ASSISTANT = "home_assistant"
    MANUAL_IMPORT = "manual_import"
    API = "api"
    UNKNOWN = "unknown"


class ProtocolName(StrEnum):
    """Protocol names as source metadata only.

    These enum values do not implement protocol adapters. They identify where
    data originated before normalization.
    """

    MQTT = "mqtt"
    MODBUS = "modbus"
    BACNET = "bacnet"
    ESPHOME = "esphome"
    REST = "rest"
    FILE = "file"
    MANUAL = "manual"
    UNKNOWN = "unknown"


class DataQuality(StrEnum):
    """Initial measurement and state quality values."""

    GOOD = "good"
    ESTIMATED = "estimated"
    MISSING = "missing"
    STALE = "stale"
    INVALID = "invalid"
    UNKNOWN = "unknown"


class EquipmentOperationalState(StrEnum):
    """Initial generic equipment operational states."""

    OFF = "off"
    IDLE = "idle"
    HEATING = "heating"
    COOLING = "cooling"
    FAN_ONLY = "fan_only"
    DEFROST = "defrost"
    UNKNOWN = "unknown"


class Severity(StrEnum):
    """Initial event and alert severity values."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


def _require_identifier(value: str, field_name: str) -> None:
    if not value.strip():
        raise GeoPilotDomainError(f"{field_name} must be a non-empty identifier")


def epoch_microseconds(value: datetime) -> int:
    """Return exact microseconds since the Unix epoch for an aware datetime.

    Uses `timedelta` arithmetic rather than `datetime.timestamp()`, whose float
    result cannot represent microsecond resolution exactly at current epoch
    values.
    """

    _require_aware_datetime(value, "value")
    return (value - _EPOCH) // _MICROSECOND


def _require_text(value: str, field_name: str) -> None:
    if not value.strip():
        raise GeoPilotDomainError(f"{field_name} must be non-empty")


def _require_aware_datetime(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise GeoPilotDomainError(f"{field_name} must be timezone-aware")


def _require_numeric(value: object, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise GeoPilotDomainError(f"{field_name} must be numeric")


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
class Unit:
    """Unit metadata for numeric measurements."""

    code: str
    quantity: str
    symbol: str

    def __post_init__(self) -> None:
        _require_identifier(self.code, "code")
        _require_text(self.quantity, "quantity")
        _require_text(self.symbol, "symbol")

    def to_dict(self) -> dict[str, Any]:
        return _dataclass_to_dict(self)


@dataclass(frozen=True, slots=True)
class Residence:
    """Local installation boundary controlled by the homeowner."""

    id: str
    name: str
    timezone: str
    created_at: datetime

    def __post_init__(self) -> None:
        _require_identifier(self.id, "id")
        _require_text(self.name, "name")
        _require_text(self.timezone, "timezone")
        _require_aware_datetime(self.created_at, "created_at")

    def to_dict(self) -> dict[str, Any]:
        return _dataclass_to_dict(self)


@dataclass(frozen=True, slots=True)
class HVACSystem:
    """Group of related HVAC equipment serving a residence."""

    id: str
    residence_id: str
    name: str
    system_type: SystemType
    created_at: datetime

    def __post_init__(self) -> None:
        _require_identifier(self.id, "id")
        _require_identifier(self.residence_id, "residence_id")
        _require_text(self.name, "name")
        _require_aware_datetime(self.created_at, "created_at")

    def to_dict(self) -> dict[str, Any]:
        return _dataclass_to_dict(self)


@dataclass(frozen=True, slots=True)
class Equipment:
    """Physical or logical equipment that produces readings, states, or events."""

    id: str
    hvac_system_id: str
    name: str
    equipment_type: EquipmentType
    created_at: datetime
    manufacturer: str | None = None
    model: str | None = None

    def __post_init__(self) -> None:
        _require_identifier(self.id, "id")
        _require_identifier(self.hvac_system_id, "hvac_system_id")
        _require_text(self.name, "name")
        _require_aware_datetime(self.created_at, "created_at")
        if self.manufacturer is not None:
            _require_text(self.manufacturer, "manufacturer")
        if self.model is not None:
            _require_text(self.model, "model")

    def to_dict(self) -> dict[str, Any]:
        return _dataclass_to_dict(self)


@dataclass(frozen=True, slots=True)
class ProtocolSource:
    """Source metadata for data before normalization."""

    id: str
    name: str
    source_type: SourceType
    created_at: datetime
    protocol: ProtocolName | None = None

    def __post_init__(self) -> None:
        _require_identifier(self.id, "id")
        _require_text(self.name, "name")
        _require_aware_datetime(self.created_at, "created_at")

    def to_dict(self) -> dict[str, Any]:
        return _dataclass_to_dict(self)


@dataclass(frozen=True, slots=True)
class Sensor:
    """Measurement point or logical signal."""

    id: str
    equipment_id: str
    name: str
    measurement_kind: MeasurementKind
    unit: str
    source_id: str
    created_at: datetime
    sensor_kind: SensorMeasurementKind | None = None

    def __post_init__(self) -> None:
        _require_identifier(self.id, "id")
        _require_identifier(self.equipment_id, "equipment_id")
        _require_text(self.name, "name")
        _require_identifier(self.unit, "unit")
        _require_identifier(self.source_id, "source_id")
        _require_aware_datetime(self.created_at, "created_at")
        if self.sensor_kind is None:
            object.__setattr__(
                self,
                "sensor_kind",
                _sensor_kind_from_measurement_kind(self.measurement_kind),
            )

    def to_dict(self) -> dict[str, Any]:
        return _dataclass_to_dict(self)


def _sensor_kind_from_measurement_kind(
    measurement_kind: MeasurementKind,
) -> SensorMeasurementKind | None:
    match measurement_kind:
        case MeasurementKind.TEMPERATURE:
            return SensorMeasurementKind.TEMPERATURE
        case MeasurementKind.HUMIDITY:
            return SensorMeasurementKind.RELATIVE_HUMIDITY
        case MeasurementKind.POWER:
            return SensorMeasurementKind.POWER
        case _:
            return None


@dataclass(frozen=True, slots=True)
class Measurement:
    """Timestamped normalized numeric value produced by a sensor."""

    id: str
    sensor_id: str
    observed_at: datetime
    received_at: datetime
    value: int | float
    unit: str
    quality: DataQuality
    source_id: str

    def __post_init__(self) -> None:
        _require_identifier(self.id, "id")
        _require_identifier(self.sensor_id, "sensor_id")
        _require_aware_datetime(self.observed_at, "observed_at")
        _require_aware_datetime(self.received_at, "received_at")
        _require_numeric(self.value, "value")
        _require_identifier(self.unit, "unit")
        _require_identifier(self.source_id, "source_id")

    def to_dict(self) -> dict[str, Any]:
        return _dataclass_to_dict(self)


@dataclass(frozen=True, slots=True)
class EquipmentState:
    """Plain equipment state at a point in time."""

    id: str
    equipment_id: str
    observed_at: datetime
    state: EquipmentOperationalState
    source_id: str
    quality: DataQuality

    def __post_init__(self) -> None:
        _require_identifier(self.id, "id")
        _require_identifier(self.equipment_id, "equipment_id")
        _require_aware_datetime(self.observed_at, "observed_at")
        _require_identifier(self.source_id, "source_id")

    def to_dict(self) -> dict[str, Any]:
        return _dataclass_to_dict(self)


@dataclass(frozen=True, slots=True)
class Event:
    """Observation that something happened."""

    id: str
    occurred_at: datetime
    event_type: str
    severity: Severity
    message: str
    source_id: str
    equipment_id: str | None = None

    def __post_init__(self) -> None:
        _require_identifier(self.id, "id")
        _require_aware_datetime(self.occurred_at, "occurred_at")
        _require_identifier(self.event_type, "event_type")
        _require_text(self.message, "message")
        _require_identifier(self.source_id, "source_id")
        if self.equipment_id is not None:
            _require_identifier(self.equipment_id, "equipment_id")

    def to_dict(self) -> dict[str, Any]:
        return _dataclass_to_dict(self)


@dataclass(frozen=True, slots=True)
class Alert:
    """Local rule result that may need homeowner attention."""

    id: str
    triggered_at: datetime
    severity: Severity
    summary: str
    source_id: str
    cleared_at: datetime | None = None
    related_measurement_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_identifier(self.id, "id")
        _require_aware_datetime(self.triggered_at, "triggered_at")
        _require_text(self.summary, "summary")
        _require_identifier(self.source_id, "source_id")
        if self.cleared_at is not None:
            _require_aware_datetime(self.cleared_at, "cleared_at")
        for measurement_id in self.related_measurement_ids:
            _require_identifier(measurement_id, "related_measurement_ids")

    def to_dict(self) -> dict[str, Any]:
        return _dataclass_to_dict(self)
