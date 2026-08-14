"""1-Wire temperature acquisition for DS18B20 probes.

This module reads DS18B20 probes through the Linux kernel's 1-Wire sysfs
interface, and converts readings into `RawMeasurement`. It is a second
acquisition adapter alongside Modbus, behind the same domain boundary: nothing
here leaks into the domain, the historian or the snapshot.

It performs no scheduling, opens no serial port, and writes to no device.

Why sysfs rather than bit-banging GPIO: the kernel already owns the timing, the
CRC and the bus enumeration. Reimplementing that in Python on a machine that is
also running a database would be slower, less correct, and pointless.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from geopilot.acquisition import AcquisitionErrorCode
from geopilot.ingestion import RawMeasurement

DEFAULT_SYSFS_ROOT = Path("/sys/bus/w1/devices")

# The DS18B20 reports 85.0 C after a power-on reset when no conversion has
# completed. It is a sentinel, not a temperature, and treating it as data is the
# classic way to record a fictional heat wave in a mechanical room.
POWER_ON_RESET_MILLIDEGREES = 85000

_TEMPERATURE_PATTERN = re.compile(r"t=(-?\d+)")


class OneWireErrorCode(StrEnum):
    """Structured 1-Wire failure categories."""

    DEVICE_NOT_FOUND = "device_not_found"
    READ_FAILED = "read_failed"
    CRC_FAILED = "crc_failed"
    INVALID_RESPONSE = "invalid_response"
    POWER_ON_RESET = "power_on_reset"


@dataclass(slots=True)
class OneWireError(Exception):
    """Structured 1-Wire failure."""

    code: OneWireErrorCode
    message: str
    device_id: str | None = None

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"

    @property
    def acquisition_code(self) -> AcquisitionErrorCode:
        """Map a bus failure onto the shared acquisition vocabulary."""

        match self.code:
            case OneWireErrorCode.INVALID_RESPONSE | OneWireErrorCode.CRC_FAILED:
                return AcquisitionErrorCode.DECODE_FAILED
            case _:
                return AcquisitionErrorCode.READ_FAILED


class OneWireBoundaryError(ValueError):
    """Raised when a 1-Wire boundary object is invalid."""


@dataclass(frozen=True, slots=True)
class OneWireReading:
    """One raw probe reading, before any GeoPilot meaning is applied."""

    device_id: str
    millidegrees: int
    observed_at: datetime

    def __post_init__(self) -> None:
        if not self.device_id.strip():
            raise OneWireBoundaryError("device_id must be a non-empty identifier")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise OneWireBoundaryError("observed_at must be timezone-aware")

    @property
    def celsius(self) -> float:
        """Return the reading in degrees Celsius."""

        return self.millidegrees / 1000


@dataclass(frozen=True, slots=True)
class OneWireSensorDefinition:
    """Mapping from one probe to one GeoPilot sensor.

    `offset_celsius` carries the same-bath calibration correction. Absolute
    accuracy matters little for this project; agreement between two probes
    measuring the two ends of a loop matters enormously, and that is what a
    per-probe offset buys.
    """

    device_id: str
    source_id: str
    sensor_id: str
    unit: str = "degC"
    offset_celsius: float = 0.0
    source_reference: str = ""

    def __post_init__(self) -> None:
        for value, name in (
            (self.device_id, "device_id"),
            (self.source_id, "source_id"),
            (self.sensor_id, "sensor_id"),
            (self.unit, "unit"),
        ):
            if not value.strip():
                raise OneWireBoundaryError(f"{name} must be a non-empty identifier")
        if not self.source_reference.strip():
            raise OneWireBoundaryError("source_reference must be non-empty")


class OneWireBus(Protocol):
    """Read-only 1-Wire temperature bus."""

    def read_temperature(self, device_id: str) -> OneWireReading:
        """Return one probe reading."""


class SysfsOneWireBus:
    """Reads DS18B20 probes through the Linux 1-Wire sysfs interface.

    The root directory is injectable so tests can point at a fixture tree. No
    test needs a Raspberry Pi, a probe, or Linux.
    """

    def __init__(
        self,
        root: str | Path = DEFAULT_SYSFS_ROOT,
        *,
        clock: object = None,
    ) -> None:
        self._root = Path(root)
        self._clock = clock if callable(clock) else _utc_now

    def read_temperature(self, device_id: str) -> OneWireReading:
        """Read one probe, validating the kernel's CRC and the reset sentinel."""

        slave = self._root / device_id / "w1_slave"
        if not slave.exists():
            raise OneWireError(
                code=OneWireErrorCode.DEVICE_NOT_FOUND,
                message=f"no 1-Wire device at {slave}",
                device_id=device_id,
            )

        try:
            content = slave.read_text()
        except OSError as error:
            raise OneWireError(
                code=OneWireErrorCode.READ_FAILED,
                message=f"could not read {slave}: {error}",
                device_id=device_id,
            ) from error

        return parse_w1_slave(device_id, content, observed_at=self._clock())

    def available_devices(self, family: str = "28") -> tuple[str, ...]:
        """List probe ids present on the bus, for bench discovery."""

        if not self._root.exists():
            return ()
        return tuple(
            sorted(
                item.name
                for item in self._root.iterdir()
                if item.is_dir() and item.name.startswith(f"{family}-")
            )
        )


def parse_w1_slave(device_id: str, content: str, *, observed_at: datetime) -> OneWireReading:
    """Parse the two-line `w1_slave` payload the kernel exposes.

    Expected shape:

    ```text
    5b 01 4b 46 7f ff 0c 10 4f : crc=4f YES
    5b 01 4b 46 7f ff 0c 10 4f t=21687
    ```
    """

    lines = content.strip().splitlines()
    if len(lines) < 2:
        raise OneWireError(
            code=OneWireErrorCode.INVALID_RESPONSE,
            message="w1_slave payload has fewer than two lines",
            device_id=device_id,
        )

    if not lines[0].rstrip().endswith("YES"):
        raise OneWireError(
            code=OneWireErrorCode.CRC_FAILED,
            message="kernel reported a CRC mismatch",
            device_id=device_id,
        )

    match = _TEMPERATURE_PATTERN.search(lines[1])
    if match is None:
        raise OneWireError(
            code=OneWireErrorCode.INVALID_RESPONSE,
            message="no t= value in w1_slave payload",
            device_id=device_id,
        )

    millidegrees = int(match.group(1))
    if millidegrees == POWER_ON_RESET_MILLIDEGREES:
        raise OneWireError(
            code=OneWireErrorCode.POWER_ON_RESET,
            message="probe reported its 85 C power-on reset value, not a temperature",
            device_id=device_id,
        )

    return OneWireReading(
        device_id=device_id,
        millidegrees=millidegrees,
        observed_at=observed_at,
    )


class OneWireAcquisitionService:
    """Convert probe readings into raw measurements."""

    def __init__(self, bus: OneWireBus) -> None:
        self._bus = bus

    def read_raw_measurement(self, definition: OneWireSensorDefinition) -> RawMeasurement:
        """Read one probe and apply its calibration offset."""

        reading = self._bus.read_temperature(definition.device_id)
        return RawMeasurement(
            source_id=definition.source_id,
            sensor_id=definition.sensor_id,
            value=reading.celsius + definition.offset_celsius,
            unit=definition.unit,
            timestamp=reading.observed_at,
        )


class FakeOneWireBus:
    """Scripted bus for tests and for exercising failure paths."""

    def __init__(
        self,
        readings: dict[str, OneWireReading] | None = None,
        errors: dict[str, OneWireError] | None = None,
    ) -> None:
        self._readings = dict(readings or {})
        self._errors = dict(errors or {})
        self.requested: list[str] = []

    def read_temperature(self, device_id: str) -> OneWireReading:
        self.requested.append(device_id)
        if device_id in self._errors:
            raise self._errors[device_id]
        try:
            return self._readings[device_id]
        except KeyError as error:
            raise OneWireError(
                code=OneWireErrorCode.DEVICE_NOT_FOUND,
                message=f"no scripted reading for {device_id}",
                device_id=device_id,
            ) from error


def _utc_now() -> datetime:
    return datetime.now(UTC)
