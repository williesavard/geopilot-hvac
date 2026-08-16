"""Declarative installation configuration.

An installation is described in a TOML file rather than in Python source, as
decided in ``docs/CONTINUOUS_ACQUISITION_ADR.md``. This module parses and
validates that file into immutable objects. It performs no I/O beyond reading
the file, opens no serial port, and touches no database.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from geopilot.control import ControlPolicy, ControlTarget
from geopilot.domain import (
    Equipment,
    EquipmentType,
    HVACSystem,
    MeasurementKind,
    Residence,
    Sensor,
    SensorMeasurementKind,
    SystemType,
)
from geopilot.modbus_transport import ModbusBitKind, ModbusRegisterKind
from geopilot.onewire import DEFAULT_SYSFS_ROOT
from geopilot.register_decoder import RegisterDataType

CONFIGURATION_VERSION = 1

DEFAULT_MINIMUM_INTERVAL_SECONDS = 300.0
"""How long a relay must rest between commands unless a target says otherwise.

Five minutes. A configuration that forgets to state an interval gets the
conservative one, never an unlimited one: relay chatter is how contactors weld
and compressors die. Being too slow is an inconvenience; being too fast is a
repair bill.
"""


class ConfigurationError(ValueError):
    """Raised when an installation configuration is invalid."""


@dataclass(frozen=True, slots=True)
class SerialSourceConfig:
    """A Modbus RTU source reachable through a serial port."""

    source_id: str
    port: str
    baudrate: int
    parity: str
    stopbits: int | float
    bytesize: int
    timeout: float


@dataclass(frozen=True, slots=True)
class OneWireSourceConfig:
    """A 1-Wire bus exposed through the kernel sysfs interface."""

    source_id: str
    root: str


@dataclass(frozen=True, slots=True)
class OneWireReadConfig:
    """One DS18B20 probe, and the sensor its value belongs to."""

    read_id: str
    source_id: str
    sensor_id: str
    device_id: str
    unit: str
    offset_celsius: float
    source_reference: str


@dataclass(frozen=True, slots=True)
class BitReadConfig:
    """One discrete input or coil, and the sensor its state belongs to.

    `inverted` exists because active-low wiring exists. A stored `1` must always
    mean asserted, so an inverted signal is corrected here, before ingestion,
    rather than leaving every consumer to ask whether this particular 1 meant
    yes. See ``docs/DISCRETE_STATE_ADR.md``.
    """

    read_id: str
    source_id: str
    sensor_id: str
    unit_id: int
    bit_kind: ModbusBitKind
    address: int
    inverted: bool
    source_reference: str


@dataclass(frozen=True, slots=True)
class RegisterReadConfig:
    """One register to read, and the sensor its value belongs to."""

    read_id: str
    source_id: str
    sensor_id: str
    unit_id: int
    register_kind: ModbusRegisterKind
    address: int
    quantity: int
    data_type: RegisterDataType
    unit: str
    scale: float
    offset: float
    source_reference: str


@dataclass(frozen=True, slots=True)
class ControlTargetConfig:
    """One relay, and the bus it is reached on.

    `ControlTarget` describes the relay; this adds the source, because the guard
    deliberately knows nothing about ports and something has to.
    """

    target: ControlTarget
    source_id: str


@dataclass(frozen=True, slots=True)
class InstallationConfig:
    """A complete, validated installation description."""

    version: int
    database: Path
    residence: Residence
    systems: tuple[HVACSystem, ...]
    equipment: tuple[Equipment, ...]
    sensors: tuple[Sensor, ...]
    sources: tuple[SerialSourceConfig, ...]
    reads: tuple[RegisterReadConfig, ...]
    onewire_sources: tuple[OneWireSourceConfig, ...] = ()
    onewire_reads: tuple[OneWireReadConfig, ...] = ()
    bit_reads: tuple[BitReadConfig, ...] = ()
    control: ControlPolicy = field(default_factory=ControlPolicy)
    control_sources: tuple[ControlTargetConfig, ...] = ()

    def control_source(self, target_id: str) -> str:
        """Return the source a control target is reached on."""

        for candidate in self.control_sources:
            if candidate.target.target_id == target_id:
                return candidate.source_id
        raise ConfigurationError(f"unknown control target: {target_id}")

    def source(self, source_id: str) -> SerialSourceConfig:
        """Return one source by id."""

        for candidate in self.sources:
            if candidate.source_id == source_id:
                return candidate
        raise ConfigurationError(f"unknown source: {source_id}")


def load_configuration(
    path: str | Path,
    *,
    created_at: datetime | None = None,
) -> InstallationConfig:
    """Read and validate an installation configuration from a TOML file."""

    location = Path(path)
    try:
        with location.open("rb") as handle:
            document = tomllib.load(handle)
    except FileNotFoundError as error:
        raise ConfigurationError(f"configuration file not found: {location}") from error
    except tomllib.TOMLDecodeError as error:
        raise ConfigurationError(f"configuration is not valid TOML: {error}") from error

    return parse_configuration(document, created_at=created_at)


def parse_configuration(
    document: dict[str, Any],
    *,
    created_at: datetime | None = None,
) -> InstallationConfig:
    """Validate an already-parsed configuration document."""

    stamp = created_at or datetime.now(UTC)

    version = _require_int(document, "version", minimum=1)
    if version != CONFIGURATION_VERSION:
        raise ConfigurationError(
            f"unsupported configuration version {version}; "
            f"this build expects {CONFIGURATION_VERSION}"
        )

    storage = _require_table(document, "storage")
    database = Path(_require_text(storage, "database"))

    residence_table = _require_table(document, "residence")
    residence = Residence(
        id=_require_text(residence_table, "id"),
        name=_require_text(residence_table, "name"),
        timezone=_require_text(residence_table, "timezone"),
        created_at=stamp,
    )

    systems = tuple(
        HVACSystem(
            id=_require_text(entry, "id"),
            residence_id=residence.id,
            name=_require_text(entry, "name"),
            system_type=_require_enum(entry, "system_type", SystemType),
            created_at=stamp,
        )
        for entry in _require_array(document, "system")
    )
    _require_unique(tuple(item.id for item in systems), "system id")

    equipment = tuple(
        Equipment(
            id=_require_text(entry, "id"),
            hvac_system_id=_require_text(entry, "system_id"),
            name=_require_text(entry, "name"),
            equipment_type=_require_enum(entry, "equipment_type", EquipmentType),
            created_at=stamp,
        )
        for entry in _require_array(document, "equipment")
    )
    _require_unique(tuple(item.id for item in equipment), "equipment id")

    sensors = tuple(
        Sensor(
            id=_require_text(entry, "id"),
            equipment_id=_require_text(entry, "equipment_id"),
            name=_require_text(entry, "name"),
            measurement_kind=_require_enum(entry, "measurement_kind", MeasurementKind),
            unit=_require_text(entry, "unit"),
            source_id=_require_text(entry, "source_id"),
            created_at=stamp,
            sensor_kind=_optional_enum(entry, "sensor_kind", SensorMeasurementKind),
        )
        for entry in _require_array(document, "sensor")
    )
    _require_unique(tuple(item.id for item in sensors), "sensor id")

    sources = tuple(
        SerialSourceConfig(
            source_id=_require_text(entry, "id"),
            port=_require_text(entry, "port"),
            baudrate=_optional_int(entry, "baudrate", 9600),
            parity=_optional_text(entry, "parity", "N"),
            stopbits=_optional_number(entry, "stopbits", 1),
            bytesize=_optional_int(entry, "bytesize", 8),
            timeout=_optional_number(entry, "timeout", 1.0),
        )
        for entry in _require_array(document, "source")
    )
    _require_unique(tuple(item.source_id for item in sources), "source id")

    reads = tuple(
        RegisterReadConfig(
            read_id=_require_text(entry, "id"),
            source_id=_require_text(entry, "source_id"),
            sensor_id=_require_text(entry, "sensor_id"),
            unit_id=_require_int(entry, "unit_id", minimum=0),
            register_kind=_require_enum(entry, "register", ModbusRegisterKind),
            address=_require_int(entry, "address", minimum=0),
            quantity=_optional_int(entry, "quantity", 1),
            data_type=_require_enum(entry, "data_type", RegisterDataType),
            unit=_require_text(entry, "unit"),
            scale=_optional_number(entry, "scale", 1.0),
            offset=_optional_number(entry, "offset", 0.0),
            source_reference=_require_text(entry, "source_reference"),
        )
        for entry in _require_array(document, "read")
    )
    _require_unique(tuple(item.read_id for item in reads), "read id")

    onewire_sources = tuple(
        OneWireSourceConfig(
            source_id=_require_text(entry, "id"),
            root=_optional_text(entry, "root", str(DEFAULT_SYSFS_ROOT)),
        )
        for entry in _require_array(document, "onewire_source")
    )
    _require_unique(tuple(item.source_id for item in onewire_sources), "onewire source id")

    onewire_reads = tuple(
        OneWireReadConfig(
            read_id=_require_text(entry, "id"),
            source_id=_require_text(entry, "source_id"),
            sensor_id=_require_text(entry, "sensor_id"),
            device_id=_require_text(entry, "device_id"),
            unit=_optional_text(entry, "unit", "degC"),
            offset_celsius=_optional_number(entry, "offset_celsius", 0.0),
            source_reference=_require_text(entry, "source_reference"),
        )
        for entry in _require_array(document, "onewire_read")
    )
    _require_unique(tuple(item.read_id for item in onewire_reads), "onewire read id")

    bit_reads = tuple(
        BitReadConfig(
            read_id=_require_text(entry, "id"),
            source_id=_require_text(entry, "source_id"),
            sensor_id=_require_text(entry, "sensor_id"),
            unit_id=_require_int(entry, "unit_id", minimum=0),
            bit_kind=_require_enum(entry, "bit", ModbusBitKind),
            address=_require_int(entry, "address", minimum=0),
            inverted=_optional_bool(entry, "inverted", False),
            source_reference=_require_text(entry, "source_reference"),
        )
        for entry in _require_array(document, "bit_read")
    )
    _require_unique(tuple(item.read_id for item in bit_reads), "bit read id")

    control_sources = tuple(
        ControlTargetConfig(
            target=ControlTarget(
                target_id=_require_text(entry, "id"),
                unit_id=_require_int(entry, "unit_id", minimum=0),
                address=_require_int(entry, "address", minimum=0),
                minimum_interval_seconds=_optional_number(
                    entry, "minimum_interval_seconds", DEFAULT_MINIMUM_INTERVAL_SECONDS
                ),
                description=_optional_text(entry, "description", ""),
            ),
            source_id=_require_text(entry, "source_id"),
        )
        for entry in _require_array(document, "control_target")
    )
    _require_unique(
        tuple(item.target.target_id for item in control_sources), "control target id"
    )

    control_table = document.get("control")
    if control_table is not None and not isinstance(control_table, dict):
        raise ConfigurationError("control must be a table")
    control = ControlPolicy(
        enabled=_optional_bool(control_table or {}, "enabled", False),
        targets=tuple(item.target for item in control_sources),
    )

    _validate_control_references(control_sources, sources)

    _validate_references(
        systems,
        equipment,
        sensors,
        sources,
        reads,
        residence,
        extra_source_ids=frozenset(item.source_id for item in onewire_sources),
    )
    _validate_onewire_references(sensors, sources, onewire_sources, onewire_reads)
    _validate_bit_references(sensors, sources, bit_reads)

    return InstallationConfig(
        version=version,
        database=database,
        residence=residence,
        systems=systems,
        equipment=equipment,
        sensors=sensors,
        sources=sources,
        reads=reads,
        onewire_sources=onewire_sources,
        onewire_reads=onewire_reads,
        bit_reads=bit_reads,
        control=control,
        control_sources=control_sources,
    )


def _validate_control_references(
    control_sources: tuple[ControlTargetConfig, ...],
    sources: tuple[SerialSourceConfig, ...],
) -> None:
    """Refuse a relay on a bus that does not exist.

    A control target pointing at a missing source would only be discovered when
    somebody pressed the button, which is the worst possible moment.
    """

    serial_ids = {item.source_id for item in sources}
    for entry in control_sources:
        if entry.source_id not in serial_ids:
            raise ConfigurationError(
                f"control target {entry.target.target_id} names unknown source: {entry.source_id}"
            )


def _validate_bit_references(
    sensors: tuple[Sensor, ...],
    sources: tuple[SerialSourceConfig, ...],
    bit_reads: tuple[BitReadConfig, ...],
) -> None:
    sensor_ids = {item.id for item in sensors}
    serial_ids = {item.source_id for item in sources}

    for read in bit_reads:
        if read.source_id not in serial_ids:
            raise ConfigurationError(
                f"bit read {read.read_id} references unknown source: {read.source_id}"
            )
        if read.sensor_id not in sensor_ids:
            raise ConfigurationError(
                f"bit read {read.read_id} references unknown sensor: {read.sensor_id}"
            )


def _validate_onewire_references(
    sensors: tuple[Sensor, ...],
    sources: tuple[SerialSourceConfig, ...],
    onewire_sources: tuple[OneWireSourceConfig, ...],
    onewire_reads: tuple[OneWireReadConfig, ...],
) -> None:
    sensor_ids = {item.id for item in sensors}
    onewire_ids = {item.source_id for item in onewire_sources}
    serial_ids = {item.source_id for item in sources}

    for shared in onewire_ids & serial_ids:
        raise ConfigurationError(
            f"source id used by both a serial and a 1-Wire source: {shared}"
        )

    for read in onewire_reads:
        if read.source_id not in onewire_ids:
            raise ConfigurationError(
                f"onewire read {read.read_id} references unknown source: {read.source_id}"
            )
        if read.sensor_id not in sensor_ids:
            raise ConfigurationError(
                f"onewire read {read.read_id} references unknown sensor: {read.sensor_id}"
            )


def _validate_references(
    systems: tuple[HVACSystem, ...],
    equipment: tuple[Equipment, ...],
    sensors: tuple[Sensor, ...],
    sources: tuple[SerialSourceConfig, ...],
    reads: tuple[RegisterReadConfig, ...],
    residence: Residence,
    *,
    extra_source_ids: frozenset[str] = frozenset(),
) -> None:
    system_ids = {item.id for item in systems}
    equipment_ids = {item.id for item in equipment}
    sensor_ids = {item.id for item in sensors}
    source_ids = {item.source_id for item in sources} | set(extra_source_ids)

    if not systems:
        raise ConfigurationError("at least one [[system]] is required")

    for item in equipment:
        if item.hvac_system_id not in system_ids:
            raise ConfigurationError(
                f"equipment {item.id} references unknown system: {item.hvac_system_id}"
            )

    for sensor in sensors:
        if sensor.equipment_id not in equipment_ids:
            raise ConfigurationError(
                f"sensor {sensor.id} references unknown equipment: {sensor.equipment_id}"
            )
        if sensor.source_id not in source_ids:
            raise ConfigurationError(
                f"sensor {sensor.id} references unknown source: {sensor.source_id}"
            )

    serial_source_ids = {item.source_id for item in sources}
    for read in reads:
        if read.source_id not in serial_source_ids:
            raise ConfigurationError(
                f"read {read.read_id} references unknown source: {read.source_id}"
            )
        if read.sensor_id not in sensor_ids:
            raise ConfigurationError(
                f"read {read.read_id} references unknown sensor: {read.sensor_id}"
            )

    if residence.id.strip() == "":
        raise ConfigurationError("residence id must be non-empty")


def _require_table(document: dict[str, Any], key: str) -> dict[str, Any]:
    value = document.get(key)
    if not isinstance(value, dict):
        raise ConfigurationError(f"[{key}] table is required")
    return value


def _require_array(document: dict[str, Any], key: str) -> tuple[dict[str, Any], ...]:
    value = document.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ConfigurationError(f"[[{key}]] must be an array of tables")
    return tuple(value)


def _require_text(table: dict[str, Any], key: str) -> str:
    value = table.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(f"{key} must be a non-empty string")
    return value


def _optional_text(table: dict[str, Any], key: str, default: str) -> str:
    if key not in table:
        return default
    return _require_text(table, key)


def _require_int(table: dict[str, Any], key: str, *, minimum: int) -> int:
    value = table.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigurationError(f"{key} must be an integer")
    if value < minimum:
        raise ConfigurationError(f"{key} must be at least {minimum}")
    return value


def _optional_int(table: dict[str, Any], key: str, default: int) -> int:
    if key not in table:
        return default
    return _require_int(table, key, minimum=0)


def _optional_number(table: dict[str, Any], key: str, default: float) -> float:
    if key not in table:
        return default
    value = table.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ConfigurationError(f"{key} must be a number")
    return float(value)


def _require_enum(table: dict[str, Any], key: str, enum_type: Any) -> Any:
    raw = _require_text(table, key)
    try:
        return enum_type(raw)
    except ValueError as error:
        allowed = ", ".join(sorted(item.value for item in enum_type))
        raise ConfigurationError(f"{key} must be one of: {allowed}") from error


def _optional_bool(table: dict[str, Any], key: str, default: bool) -> bool:
    if key not in table:
        return default
    value = table.get(key)
    if not isinstance(value, bool):
        raise ConfigurationError(f"{key} must be a boolean")
    return value


def _optional_enum(table: dict[str, Any], key: str, enum_type: Any) -> Any | None:
    if key not in table:
        return None
    return _require_enum(table, key, enum_type)


def _require_unique(values: tuple[str, ...], label: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise ConfigurationError(f"duplicate {label}: {value}")
        seen.add(value)
