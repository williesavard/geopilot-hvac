"""Declarative device profiles for simulator-first acquisition work.

Profiles describe possible register mappings without performing any I/O. The
first built-in profiles are simulated only; real device profiles must wait for
source-reviewed register maps.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from geopilot.domain import MeasurementKind, ProtocolName
from geopilot.register_decoder import RegisterDataType, RegisterDefinition

SIMULATED_POWER_METER_V1 = "simulated.power_meter.v1"
SIMULATED_TEMP_HUMIDITY_SENSOR_V1 = "simulated.temp_humidity_sensor.v1"


class DeviceProfileError(ValueError):
    """Raised when a device profile is invalid or missing."""


class DeviceProfileStatus(StrEnum):
    """Validation status for a device profile."""

    SIMULATED = "simulated"
    UNDER_EVALUATION = "under_evaluation"
    VERIFIED = "verified"


@dataclass(frozen=True, slots=True)
class DeviceRegisterProfile:
    """Declarative mapping from one device register to one measurement signal."""

    name: str
    register_id: str
    address: int | None
    quantity: str
    data_type: RegisterDataType
    unit: str
    measurement_kind: MeasurementKind
    scale: float = 1.0
    offset: float = 0.0
    source_reference: str = ""

    def __post_init__(self) -> None:
        _require_identifier(self.name, "name")
        _require_identifier(self.register_id, "register_id")
        _require_identifier(self.quantity, "quantity")
        _require_identifier(self.unit, "unit")
        _require_text(self.source_reference, "source_reference")
        _require_finite(self.scale, "scale")
        _require_finite(self.offset, "offset")
        if self.scale == 0:
            raise DeviceProfileError("scale must not be zero")
        if self.address is not None and self.address < 0:
            raise DeviceProfileError("address must be non-negative when provided")

    def to_register_definition(
        self,
        *,
        source_id: str,
        sensor_id: str,
    ) -> RegisterDefinition:
        """Build a decoder definition for this register and target sensor."""

        _require_identifier(source_id, "source_id")
        _require_identifier(sensor_id, "sensor_id")
        return RegisterDefinition(
            register_id=self.register_id,
            source_id=source_id,
            sensor_id=sensor_id,
            unit=self.unit,
            data_type=self.data_type,
            scale=self.scale,
            offset=self.offset,
            source_reference=self.source_reference,
        )


@dataclass(frozen=True, slots=True)
class DeviceProfile:
    """Declarative profile for a simulated or source-reviewed device class."""

    device_id: str
    manufacturer: str
    model: str
    protocol: ProtocolName
    status: DeviceProfileStatus
    registers: tuple[DeviceRegisterProfile, ...]

    def __post_init__(self) -> None:
        _require_identifier(self.device_id, "device_id")
        _require_text(self.manufacturer, "manufacturer")
        _require_text(self.model, "model")
        if not self.registers:
            raise DeviceProfileError("registers must not be empty")

        register_ids: set[str] = set()
        register_names: set[str] = set()
        for register in self.registers:
            if register.register_id in register_ids:
                raise DeviceProfileError(f"Duplicate register id: {register.register_id}")
            if register.name in register_names:
                raise DeviceProfileError(f"Duplicate register name: {register.name}")
            register_ids.add(register.register_id)
            register_names.add(register.name)

        if self.status is not DeviceProfileStatus.SIMULATED:
            for register in self.registers:
                if register.address is None:
                    raise DeviceProfileError(
                        "non-simulated profiles require confirmed register addresses"
                    )

    def register_by_name(self, name: str) -> DeviceRegisterProfile:
        """Return one register profile by logical name."""

        _require_identifier(name, "name")
        for register in self.registers:
            if register.name == name:
                return register
        raise DeviceProfileError(f"Unknown register profile: {name}")


class DeviceProfileRegistry:
    """In-memory registry for immutable device profiles."""

    def __init__(self, profiles: tuple[DeviceProfile, ...] = ()) -> None:
        self._profiles: dict[str, DeviceProfile] = {}
        for profile in profiles:
            self.add(profile)

    def add(self, profile: DeviceProfile) -> None:
        """Add a device profile."""

        if profile.device_id in self._profiles:
            raise DeviceProfileError(f"Duplicate device profile: {profile.device_id}")
        self._profiles[profile.device_id] = profile

    def get(self, device_id: str) -> DeviceProfile:
        """Return a profile by id."""

        _require_identifier(device_id, "device_id")
        try:
            return self._profiles[device_id]
        except KeyError as exc:
            raise DeviceProfileError(f"Unknown device profile: {device_id}") from exc

    def all(self) -> tuple[DeviceProfile, ...]:
        """Return all profiles in deterministic id order."""

        return tuple(self._profiles[key] for key in sorted(self._profiles))


def built_in_device_profiles() -> DeviceProfileRegistry:
    """Return the current built-in simulated device profiles."""

    return DeviceProfileRegistry(
        (
            _simulated_power_meter_profile(),
            _simulated_temp_humidity_profile(),
        )
    )


def _simulated_power_meter_profile() -> DeviceProfile:
    return DeviceProfile(
        device_id=SIMULATED_POWER_METER_V1,
        manufacturer="GeoPilot",
        model="Simulated Power Meter V1",
        protocol=ProtocolName.MODBUS,
        status=DeviceProfileStatus.SIMULATED,
        registers=(
            DeviceRegisterProfile(
                name="active_power",
                register_id="sim.power_meter.active_power",
                address=None,
                quantity="power",
                data_type=RegisterDataType.UINT16,
                unit="W",
                measurement_kind=MeasurementKind.POWER,
                scale=100.0,
                source_reference="GeoPilot simulated profile",
            ),
        ),
    )


def _simulated_temp_humidity_profile() -> DeviceProfile:
    return DeviceProfile(
        device_id=SIMULATED_TEMP_HUMIDITY_SENSOR_V1,
        manufacturer="GeoPilot",
        model="Simulated Temperature Humidity Sensor V1",
        protocol=ProtocolName.MODBUS,
        status=DeviceProfileStatus.SIMULATED,
        registers=(
            DeviceRegisterProfile(
                name="temperature",
                register_id="sim.temp_humidity.temperature",
                address=None,
                quantity="temperature",
                data_type=RegisterDataType.INT16,
                unit="degC",
                measurement_kind=MeasurementKind.TEMPERATURE,
                scale=0.1,
                source_reference="GeoPilot simulated profile",
            ),
            DeviceRegisterProfile(
                name="relative_humidity",
                register_id="sim.temp_humidity.relative_humidity",
                address=None,
                quantity="humidity",
                data_type=RegisterDataType.UINT16,
                unit="%",
                measurement_kind=MeasurementKind.HUMIDITY,
                scale=0.1,
                source_reference="GeoPilot simulated profile",
            ),
        ),
    )


def _require_identifier(value: str, field_name: str) -> None:
    if not value.strip():
        raise DeviceProfileError(f"{field_name} must be a non-empty identifier")


def _require_text(value: str, field_name: str) -> None:
    if not value.strip():
        raise DeviceProfileError(f"{field_name} must be non-empty")


def _require_finite(value: float, field_name: str) -> None:
    if value != value or value in {float("inf"), float("-inf")}:
        raise DeviceProfileError(f"{field_name} must be finite")
