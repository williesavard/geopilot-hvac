"""Optional pyserial-backed Modbus RTU transport.

This module keeps real serial I/O behind ``ModbusTransport``. Importing it does
not require pyserial and does not open a serial port. A port is opened only when
``PySerialModbusTransport`` is instantiated without an injected serial factory.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, cast

from geopilot.modbus_transport import (
    ModbusReadRequest,
    ModbusReadResponse,
    ModbusRegisterKind,
    ModbusTransportBoundaryError,
    ModbusTransportError,
    ModbusTransportErrorCode,
)


class SerialPort(Protocol):
    """Minimal serial object surface used by the transport."""

    def write(self, data: bytes) -> int | None:
        """Write a Modbus RTU frame."""

    def read(self, size: int) -> bytes:
        """Read up to ``size`` bytes."""


SerialFactory = Callable[..., SerialPort]
TransportClock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class PySerialModbusConfig:
    """Explicit serial configuration for a Modbus RTU transport."""

    port: str
    baudrate: int = 9600
    parity: str = "N"
    stopbits: int | float = 1
    bytesize: int = 8
    timeout: float = 1.0

    def __post_init__(self) -> None:
        _require_text(self.port, "port")
        _require_positive_int(self.baudrate, "baudrate")
        if self.parity not in {"N", "E", "O", "M", "S"}:
            raise ModbusTransportBoundaryError("parity must be one of N, E, O, M or S")
        if self.stopbits not in {1, 1.5, 2}:
            raise ModbusTransportBoundaryError("stopbits must be 1, 1.5 or 2")
        if self.bytesize not in {5, 6, 7, 8}:
            raise ModbusTransportBoundaryError("bytesize must be 5, 6, 7 or 8")
        if self.timeout <= 0:
            raise ModbusTransportBoundaryError("timeout must be positive")


class PySerialModbusTransport:
    """Read-only Modbus RTU transport backed by pyserial or an injected fake."""

    def __init__(
        self,
        config: PySerialModbusConfig,
        *,
        serial_factory: SerialFactory | None = None,
        clock: TransportClock = _utc_now,
    ) -> None:
        self._config = config
        self._clock = clock
        self._serial = open_serial_port(config, serial_factory=serial_factory)

    def read_registers(self, request: ModbusReadRequest) -> ModbusReadResponse:
        """Read raw register words for one holding or input register request."""

        function_code = _function_code(request.register_kind)
        frame = _append_crc(
            bytes(
                (
                    request.unit_id,
                    function_code,
                    (request.address >> 8) & 0xFF,
                    request.address & 0xFF,
                    (request.quantity >> 8) & 0xFF,
                    request.quantity & 0xFF,
                )
            )
        )

        try:
            written = self._serial.write(frame)
        except Exception as exc:
            raise _transport_error(
                ModbusTransportErrorCode.CONNECTION_FAILED,
                "serial write failed",
                request,
            ) from exc

        if written is not None and written != len(frame):
            raise _transport_error(
                ModbusTransportErrorCode.CONNECTION_FAILED,
                f"serial write was incomplete: {written} of {len(frame)} bytes",
                request,
            )

        header = self._read_exact(3, request)
        response_unit = header[0]
        response_function = header[1]
        payload_length_or_code = header[2]

        if response_unit != request.unit_id:
            raise _transport_error(
                ModbusTransportErrorCode.INVALID_RESPONSE,
                f"expected unit {request.unit_id}, received {response_unit}",
                request,
            )

        if response_function == function_code | 0x80:
            crc_bytes = self._read_exact(2, request)
            response = header + crc_bytes
            _require_valid_crc(response, request)
            raise _transport_error(
                _error_code_from_exception_code(payload_length_or_code),
                f"Modbus exception response: {payload_length_or_code}",
                request,
            )

        if response_function != function_code:
            raise _transport_error(
                ModbusTransportErrorCode.INVALID_RESPONSE,
                f"expected function {function_code}, received {response_function}",
                request,
            )

        byte_count = payload_length_or_code
        expected_byte_count = request.quantity * 2
        if byte_count != expected_byte_count:
            raise _transport_error(
                ModbusTransportErrorCode.INVALID_RESPONSE,
                f"expected {expected_byte_count} data byte(s), received {byte_count}",
                request,
            )

        payload_and_crc = self._read_exact(byte_count + 2, request)
        response = header + payload_and_crc
        _require_valid_crc(response, request)
        data = payload_and_crc[:byte_count]
        return ModbusReadResponse(
            request_id=request.request_id,
            words=_words_from_bytes(data),
            observed_at=self._clock(),
        )

    def _read_exact(self, size: int, request: ModbusReadRequest) -> bytes:
        try:
            data = self._serial.read(size)
        except Exception as exc:
            raise _transport_error(
                ModbusTransportErrorCode.CONNECTION_FAILED,
                "serial read failed",
                request,
            ) from exc

        if data == b"":
            raise _transport_error(
                ModbusTransportErrorCode.TIMEOUT,
                f"timed out reading {size} byte(s)",
                request,
            )
        if len(data) != size:
            raise _transport_error(
                ModbusTransportErrorCode.INVALID_RESPONSE,
                f"expected {size} byte(s), received {len(data)}",
                request,
            )
        return data


def open_serial_port(
    config: PySerialModbusConfig,
    *,
    serial_factory: SerialFactory | None = None,
) -> SerialPort:
    """Open a serial port, or build one from an injected factory.

    Public so the write transport can share one physical bus rather than
    opening a second port on the same device.
    """

    if serial_factory is not None:
        return serial_factory(
            port=config.port,
            baudrate=config.baudrate,
            parity=config.parity,
            stopbits=config.stopbits,
            bytesize=config.bytesize,
            timeout=config.timeout,
        )

    try:
        serial_module: Any = importlib.import_module("serial")
    except ImportError as exc:
        raise ModbusTransportError(
            code=ModbusTransportErrorCode.CONNECTION_FAILED,
            message="pyserial is not installed; install geopilot[modbus]",
        ) from exc

    try:
        return cast(
            SerialPort,
            serial_module.Serial(
                port=config.port,
                baudrate=config.baudrate,
                parity=config.parity,
                stopbits=config.stopbits,
                bytesize=config.bytesize,
                timeout=config.timeout,
            ),
        )
    except Exception as exc:
        raise ModbusTransportError(
            code=ModbusTransportErrorCode.CONNECTION_FAILED,
            message=f"failed to open serial port: {config.port}",
        ) from exc


def build_read_request_frame(request: ModbusReadRequest) -> bytes:
    """Build a Modbus RTU read request frame for tests and diagnostics."""

    function_code = _function_code(request.register_kind)
    return _append_crc(
        bytes(
            (
                request.unit_id,
                function_code,
                (request.address >> 8) & 0xFF,
                request.address & 0xFF,
                (request.quantity >> 8) & 0xFF,
                request.quantity & 0xFF,
            )
        )
    )


def _function_code(register_kind: ModbusRegisterKind) -> int:
    match register_kind:
        case ModbusRegisterKind.HOLDING:
            return 0x03
        case ModbusRegisterKind.INPUT:
            return 0x04


def _words_from_bytes(data: bytes) -> tuple[int, ...]:
    return tuple(
        int.from_bytes(data[index : index + 2], byteorder="big")
        for index in range(0, len(data), 2)
    )


def _error_code_from_exception_code(exception_code: int) -> ModbusTransportErrorCode:
    match exception_code:
        case 0x01:
            return ModbusTransportErrorCode.ILLEGAL_FUNCTION
        case 0x02:
            return ModbusTransportErrorCode.ILLEGAL_ADDRESS
        case 0x04:
            return ModbusTransportErrorCode.DEVICE_FAILURE
        case _:
            return ModbusTransportErrorCode.UNKNOWN


def _append_crc(frame: bytes) -> bytes:
    crc = calculate_crc(frame)
    return frame + crc.to_bytes(2, byteorder="little")


def _require_valid_crc(frame: bytes, request: ModbusReadRequest) -> None:
    if len(frame) < 3:
        raise _transport_error(
            ModbusTransportErrorCode.INVALID_RESPONSE,
            "response is too short for CRC validation",
            request,
        )
    expected = int.from_bytes(frame[-2:], byteorder="little")
    actual = calculate_crc(frame[:-2])
    if actual != expected:
        raise _transport_error(
            ModbusTransportErrorCode.INVALID_RESPONSE,
            "response CRC mismatch",
            request,
        )


def calculate_crc(frame: bytes) -> int:
    """Return the Modbus RTU CRC-16 for ``frame``."""

    crc = 0xFFFF
    for byte in frame:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc


def _transport_error(
    code: ModbusTransportErrorCode,
    message: str,
    request: ModbusReadRequest,
) -> ModbusTransportError:
    return ModbusTransportError(
        code=code,
        message=message,
        request_id=request.request_id,
    )


def _require_text(value: str, field_name: str) -> None:
    if not value.strip():
        raise ModbusTransportBoundaryError(f"{field_name} must be non-empty")


def _require_positive_int(value: int, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ModbusTransportBoundaryError(f"{field_name} must be an integer")
    if value <= 0:
        raise ModbusTransportBoundaryError(f"{field_name} must be positive")
