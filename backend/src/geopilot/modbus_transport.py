"""Hardware-free Modbus transport boundary.

This module defines request, response and error types for future Modbus RTU
transport adapters. It does not open serial ports, import pyserial, perform
hardware I/O, retry, schedule work, emit alerts, or control HVAC equipment.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol


class ModbusTransportBoundaryError(ValueError):
    """Raised when a transport boundary object is invalid."""


class ModbusRegisterKind(StrEnum):
    """Read-only Modbus register families supported by the boundary."""

    HOLDING = "holding"
    INPUT = "input"


class ModbusTransportErrorCode(StrEnum):
    """Structured transport error categories."""

    TIMEOUT = "timeout"
    CONNECTION_FAILED = "connection_failed"
    INVALID_RESPONSE = "invalid_response"
    ILLEGAL_FUNCTION = "illegal_function"
    ILLEGAL_ADDRESS = "illegal_address"
    DEVICE_FAILURE = "device_failure"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ModbusReadRequest:
    """One read-only Modbus register request."""

    request_id: str
    source_id: str
    unit_id: int
    register_kind: ModbusRegisterKind
    address: int
    quantity: int

    def __post_init__(self) -> None:
        _require_identifier(self.request_id, "request_id")
        _require_identifier(self.source_id, "source_id")
        _require_uint8(self.unit_id, "unit_id")
        _require_uint16(self.address, "address")
        if self.quantity < 1 or self.quantity > 125:
            raise ModbusTransportBoundaryError(
                "quantity must be between 1 and 125 registers"
            )


@dataclass(frozen=True, slots=True)
class ModbusReadResponse:
    """Raw register words returned by a Modbus transport."""

    request_id: str
    words: tuple[int, ...]
    observed_at: datetime

    def __post_init__(self) -> None:
        _require_identifier(self.request_id, "request_id")
        _require_aware_datetime(self.observed_at, "observed_at")
        if not self.words:
            raise ModbusTransportBoundaryError("words must contain at least one register")
        for word in self.words:
            _require_uint16(word, "word")


@dataclass(slots=True)
class ModbusTransportError(Exception):
    """Structured Modbus transport failure."""

    code: ModbusTransportErrorCode
    message: str
    request_id: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.message, "message")
        if self.request_id is not None:
            _require_identifier(self.request_id, "request_id")

    def __str__(self) -> str:
        if self.request_id is None:
            return f"{self.code.value}: {self.message}"
        return f"{self.code.value} for {self.request_id}: {self.message}"


class ModbusTransport(Protocol):
    """Read-only transport protocol for future Modbus RTU adapters."""

    def read_registers(self, request: ModbusReadRequest) -> ModbusReadResponse:
        """Return raw register words for one read request."""


class FakeModbusTransport:
    """In-memory transport implementation for tests and examples."""

    def __init__(
        self,
        responses: tuple[ModbusReadResponse, ...] = (),
        errors: tuple[ModbusTransportError, ...] = (),
    ) -> None:
        self._responses: dict[str, ModbusReadResponse] = {}
        self._errors: dict[str, ModbusTransportError] = {}
        self._read_request_ids: list[str] = []

        for response in responses:
            if response.request_id in self._responses:
                raise ModbusTransportBoundaryError(
                    f"Duplicate fake response: {response.request_id}"
                )
            self._responses[response.request_id] = response

        for error in errors:
            if error.request_id is None:
                raise ModbusTransportBoundaryError(
                    "fake transport errors must include request_id"
                )
            if error.request_id in self._errors:
                raise ModbusTransportBoundaryError(
                    f"Duplicate fake error: {error.request_id}"
                )
            self._errors[error.request_id] = error

    def read_registers(self, request: ModbusReadRequest) -> ModbusReadResponse:
        self._read_request_ids.append(request.request_id)

        if request.request_id in self._errors:
            raise self._errors[request.request_id]

        try:
            response = self._responses[request.request_id]
        except KeyError as exc:
            raise ModbusTransportError(
                code=ModbusTransportErrorCode.ILLEGAL_ADDRESS,
                message=f"Missing fake response for request: {request.request_id}",
                request_id=request.request_id,
            ) from exc

        if len(response.words) != request.quantity:
            raise ModbusTransportError(
                code=ModbusTransportErrorCode.INVALID_RESPONSE,
                message=(
                    f"Expected {request.quantity} register word(s), "
                    f"received {len(response.words)}"
                ),
                request_id=request.request_id,
            )

        return response

    def read_request_ids(self) -> tuple[str, ...]:
        """Return request ids read so far, in read order."""

        return tuple(self._read_request_ids)


def _require_identifier(value: str, field_name: str) -> None:
    if not value.strip():
        raise ModbusTransportBoundaryError(
            f"{field_name} must be a non-empty identifier"
        )


def _require_text(value: str, field_name: str) -> None:
    if not value.strip():
        raise ModbusTransportBoundaryError(f"{field_name} must be non-empty")


def _require_aware_datetime(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ModbusTransportBoundaryError(f"{field_name} must be timezone-aware")


def _require_uint8(value: int, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ModbusTransportBoundaryError(f"{field_name} must be an integer")
    if value < 0 or value > 0xFF:
        raise ModbusTransportBoundaryError(f"{field_name} must be an unsigned 8-bit value")


def _require_uint16(value: int, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ModbusTransportBoundaryError(f"{field_name} must be an integer")
    if value < 0 or value > 0xFFFF:
        raise ModbusTransportBoundaryError(
            f"{field_name} must be an unsigned 16-bit value"
        )


class ModbusBitKind(StrEnum):
    """Read-only bit-oriented Modbus tables."""

    DISCRETE_INPUT = "discrete_input"
    COIL = "coil"


@dataclass(frozen=True, slots=True)
class ModbusBitReadRequest:
    """One read-only request for a run of bits.

    Discrete inputs carry signals a device only reports, such as a thermostat
    call. Coils carry states a device can also be told to adopt, so reading them
    is how a controller learns where a relay actually is instead of assuming it
    is where it was last commanded.
    """

    request_id: str
    source_id: str
    unit_id: int
    bit_kind: ModbusBitKind
    address: int
    quantity: int

    def __post_init__(self) -> None:
        _require_identifier(self.request_id, "request_id")
        _require_identifier(self.source_id, "source_id")
        _require_uint8(self.unit_id, "unit_id")
        _require_uint16(self.address, "address")
        if self.quantity < 1 or self.quantity > 2000:
            raise ModbusTransportBoundaryError("quantity must be between 1 and 2000 bits")


@dataclass(frozen=True, slots=True)
class ModbusBitReadResponse:
    """Bits returned by a Modbus transport, already unpacked."""

    request_id: str
    bits: tuple[bool, ...]
    observed_at: datetime

    def __post_init__(self) -> None:
        _require_identifier(self.request_id, "request_id")
        _require_aware_datetime(self.observed_at, "observed_at")
        if not self.bits:
            raise ModbusTransportBoundaryError("bits must contain at least one value")
        for bit in self.bits:
            if not isinstance(bit, bool):
                raise ModbusTransportBoundaryError("bits must be booleans")


class ModbusBitTransport(Protocol):
    """Read-only bit-oriented Modbus transport."""

    def read_bits(self, request: ModbusBitReadRequest) -> ModbusBitReadResponse:
        """Return unpacked bits for one discrete input or coil request."""


class FakeModbusBitTransport:
    """In-memory bit transport for tests and examples."""

    def __init__(
        self,
        responses: tuple[ModbusBitReadResponse, ...] = (),
        errors: tuple[ModbusTransportError, ...] = (),
    ) -> None:
        self._responses: dict[str, ModbusBitReadResponse] = {}
        self._errors: dict[str, ModbusTransportError] = {}
        self._read_request_ids: list[str] = []

        for response in responses:
            if response.request_id in self._responses:
                raise ModbusTransportBoundaryError(
                    f"Duplicate fake response: {response.request_id}"
                )
            self._responses[response.request_id] = response

        for error in errors:
            if error.request_id is None:
                raise ModbusTransportBoundaryError(
                    "fake transport errors must include request_id"
                )
            self._errors[error.request_id] = error

    def read_bits(self, request: ModbusBitReadRequest) -> ModbusBitReadResponse:
        self._read_request_ids.append(request.request_id)

        if request.request_id in self._errors:
            raise self._errors[request.request_id]

        try:
            return self._responses[request.request_id]
        except KeyError as exc:
            raise ModbusTransportError(
                code=ModbusTransportErrorCode.INVALID_RESPONSE,
                message=f"No fake response for request: {request.request_id}",
                request_id=request.request_id,
            ) from exc

    def read_request_ids(self) -> tuple[str, ...]:
        """Return request ids read so far, in read order."""

        return tuple(self._read_request_ids)


def unpack_bits(payload: bytes, quantity: int) -> tuple[bool, ...]:
    """Unpack a Modbus bit payload, least significant bit first.

    Modbus packs eight bits per byte starting at the least significant bit of
    the first byte, and pads the final byte with zeros. The padding is not data,
    so it is discarded rather than reported as inputs that are off.
    """

    bits: list[bool] = []
    for index in range(quantity):
        byte = payload[index // 8]
        bits.append(bool(byte >> (index % 8) & 0x01))
    return tuple(bits)
