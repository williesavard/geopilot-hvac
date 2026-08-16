"""Modbus RTU coil write boundary.

This module is deliberately separate from `modbus_transport`, which stays
read-only. Reads and writes are different protocols in the type system, so a
build, a deployment or a test that never constructs a `ModbusWriteTransport`
has no capability to write at all. That is a stronger guarantee than a flag
somebody can turn on, and it is the decision recorded in
``docs/CONTROL_BOUNDARY_ADR.md``.

Scope is one operation: write a single coil, Modbus function code `0x05`. That
is what a DIN-rail relay module needs and nothing more. There is no register
write, no multi-coil write, and no path to a heat pump's own controller.

This module performs no scheduling, enforces no policy and decides nothing. The
guard that decides whether a command may happen lives elsewhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

WRITE_SINGLE_COIL = 0x05

COIL_ON = 0xFF00
COIL_OFF = 0x0000


class ModbusWriteBoundaryError(ValueError):
    """Raised when a write boundary object is invalid."""


class ModbusWriteErrorCode(StrEnum):
    """Structured write failure categories.

    Deliberately mirrors the read transport's vocabulary. A relay that does not
    answer fails the same way a sensor that does not answer fails.
    """

    TIMEOUT = "timeout"
    CONNECTION_FAILED = "connection_failed"
    INVALID_RESPONSE = "invalid_response"
    ILLEGAL_FUNCTION = "illegal_function"
    ILLEGAL_ADDRESS = "illegal_address"
    DEVICE_FAILURE = "device_failure"
    NOT_ACKNOWLEDGED = "not_acknowledged"
    UNKNOWN = "unknown"


@dataclass(slots=True)
class ModbusWriteError(Exception):
    """Structured Modbus write failure."""

    code: ModbusWriteErrorCode
    message: str
    request_id: str | None = None

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


@dataclass(frozen=True, slots=True)
class ModbusCoilWriteRequest:
    """One request to set a single coil.

    `closed` is expressed as a physical relay state rather than as a raw value,
    because the wiring rule in the control ADR is stated in those terms: the
    de-energised state must be the building's existing behaviour.
    """

    request_id: str
    target_id: str
    unit_id: int
    address: int
    closed: bool

    def __post_init__(self) -> None:
        _require_identifier(self.request_id, "request_id")
        _require_identifier(self.target_id, "target_id")
        if isinstance(self.unit_id, bool) or not isinstance(self.unit_id, int):
            raise ModbusWriteBoundaryError("unit_id must be an integer")
        if self.unit_id < 0 or self.unit_id > 0xFF:
            raise ModbusWriteBoundaryError("unit_id must be an unsigned 8-bit value")
        if isinstance(self.address, bool) or not isinstance(self.address, int):
            raise ModbusWriteBoundaryError("address must be an integer")
        if self.address < 0 or self.address > 0xFFFF:
            raise ModbusWriteBoundaryError("address must be an unsigned 16-bit value")
        if not isinstance(self.closed, bool):
            raise ModbusWriteBoundaryError("closed must be a boolean")

    @property
    def coil_value(self) -> int:
        """Return the Modbus wire value for this state."""

        return COIL_ON if self.closed else COIL_OFF


@dataclass(frozen=True, slots=True)
class ModbusCoilWriteResponse:
    """Confirmation that a device echoed the requested coil state."""

    request_id: str
    address: int
    closed: bool
    written_at: datetime

    def __post_init__(self) -> None:
        _require_identifier(self.request_id, "request_id")
        if self.written_at.tzinfo is None or self.written_at.utcoffset() is None:
            raise ModbusWriteBoundaryError("written_at must be timezone-aware")


class ModbusWriteTransport(Protocol):
    """Write-capable Modbus transport.

    Kept separate from `ModbusTransport` on purpose. Absence of this type in a
    build is the read-only guarantee.
    """

    def write_coil(self, request: ModbusCoilWriteRequest) -> ModbusCoilWriteResponse:
        """Set one coil and confirm the device echoed the request."""


class FakeModbusWriteTransport:
    """In-memory write transport for tests.

    Records every accepted write so a test can assert not only the final state
    but the sequence, which is what matters for a relay.
    """

    def __init__(
        self,
        errors: dict[str, ModbusWriteError] | None = None,
        clock: object = None,
    ) -> None:
        self._errors = dict(errors or {})
        self._clock = clock if callable(clock) else _utc_now
        self.writes: list[ModbusCoilWriteRequest] = []

    def write_coil(self, request: ModbusCoilWriteRequest) -> ModbusCoilWriteResponse:
        if request.target_id in self._errors:
            raise self._errors[request.target_id]

        self.writes.append(request)
        return ModbusCoilWriteResponse(
            request_id=request.request_id,
            address=request.address,
            closed=request.closed,
            written_at=self._clock(),
        )

    def state_of(self, target_id: str) -> bool | None:
        """Return the last written state for a target, or None."""

        for write in reversed(self.writes):
            if write.target_id == target_id:
                return write.closed
        return None


def _require_identifier(value: str, field_name: str) -> None:
    if not value.strip():
        raise ModbusWriteBoundaryError(f"{field_name} must be a non-empty identifier")


def _utc_now() -> datetime:
    from datetime import UTC

    return datetime.now(UTC)
