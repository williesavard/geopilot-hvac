"""Optional pyserial-backed Modbus RTU coil write transport.

Implements `ModbusWriteTransport` for real hardware, using function code `0x05`.
Importing this module does not require pyserial and does not open a port, the
same contract the read transport follows.

A Modbus write-single-coil response echoes the request byte for byte. This
implementation treats anything else as a failure, so a relay module that
acknowledges a state it did not adopt cannot be mistaken for success.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from geopilot.modbus_pyserial_transport import (
    PySerialModbusConfig,
    SerialFactory,
    SerialPort,
    calculate_crc,
    open_serial_port,
)
from geopilot.modbus_write import (
    WRITE_SINGLE_COIL,
    ModbusCoilWriteRequest,
    ModbusCoilWriteResponse,
    ModbusWriteError,
    ModbusWriteErrorCode,
)
from geopilot.port_lock import PortBusyError, PortLock

TransportClock = Callable[[], datetime]

_RESPONSE_LENGTH = 8


def _utc_now() -> datetime:
    return datetime.now(UTC)


class PySerialModbusWriteTransport:
    """Write single coils over a real serial port.

    Accepts an already-open serial port so a read transport and a write
    transport can share one physical bus. Two objects opening the same port
    would conflict, and an RS485 segment permits one transaction at a time
    regardless.
    """

    def __init__(
        self,
        config: PySerialModbusConfig,
        *,
        serial_port: SerialPort | None = None,
        serial_factory: SerialFactory | None = None,
        clock: TransportClock = _utc_now,
        lock: PortLock | None = None,
    ) -> None:
        self._config = config
        self._clock = clock
        if serial_port is not None:
            self._serial = serial_port
        else:
            self._serial = open_serial_port(config, serial_factory=serial_factory)
        self._lock = lock if lock is not None else PortLock(config.port)

    def write_coil(self, request: ModbusCoilWriteRequest) -> ModbusCoilWriteResponse:
        """Set one coil and verify the device echoed the request exactly.

        This is the exchange the lock matters most for. Reading somebody else's
        answer to a read is a bad number; reading somebody else's answer to a
        write is a relay whose position was never actually confirmed.
        """

        try:
            with self._lock.hold():
                return self._exchange(request)
        except PortBusyError as error:
            raise ModbusWriteError(
                code=ModbusWriteErrorCode.CONNECTION_FAILED,
                message=str(error),
                request_id=request.request_id,
            ) from error

    def _exchange(self, request: ModbusCoilWriteRequest) -> ModbusCoilWriteResponse:

        frame = build_write_coil_frame(request)

        try:
            written = self._serial.write(frame)
        except Exception as exc:
            raise _error(
                ModbusWriteErrorCode.CONNECTION_FAILED,
                "serial write failed",
                request,
            ) from exc

        if written is not None and written != len(frame):
            raise _error(
                ModbusWriteErrorCode.CONNECTION_FAILED,
                f"serial write was incomplete: {written} of {len(frame)} bytes",
                request,
            )

        try:
            response = self._serial.read(_RESPONSE_LENGTH)
        except Exception as exc:
            raise _error(
                ModbusWriteErrorCode.CONNECTION_FAILED,
                "serial read failed",
                request,
            ) from exc

        if response == b"":
            raise _error(
                ModbusWriteErrorCode.TIMEOUT,
                "no response to coil write",
                request,
            )

        if len(response) == 5 and response[1] == WRITE_SINGLE_COIL | 0x80:
            _require_valid_crc(response, request)
            raise _error(
                _error_code_from_exception_code(response[2]),
                f"Modbus exception response: {response[2]}",
                request,
            )

        if len(response) != _RESPONSE_LENGTH:
            raise _error(
                ModbusWriteErrorCode.INVALID_RESPONSE,
                f"expected {_RESPONSE_LENGTH} byte(s), received {len(response)}",
                request,
            )

        _require_valid_crc(response, request)

        # A write-single-coil response echoes the request. Anything else means
        # the device did not adopt the state we asked for.
        if response != frame:
            raise _error(
                ModbusWriteErrorCode.NOT_ACKNOWLEDGED,
                "device response did not echo the requested coil state",
                request,
            )

        return ModbusCoilWriteResponse(
            request_id=request.request_id,
            address=request.address,
            closed=request.closed,
            written_at=self._clock(),
        )


def build_write_coil_frame(request: ModbusCoilWriteRequest) -> bytes:
    """Build a Modbus RTU write-single-coil frame, for tests and diagnostics."""

    value = request.coil_value
    body = bytes(
        (
            request.unit_id,
            WRITE_SINGLE_COIL,
            (request.address >> 8) & 0xFF,
            request.address & 0xFF,
            (value >> 8) & 0xFF,
            value & 0xFF,
        )
    )
    return body + calculate_crc(body).to_bytes(2, byteorder="little")


def _require_valid_crc(frame: bytes, request: ModbusCoilWriteRequest) -> None:
    if len(frame) < 3:
        raise _error(
            ModbusWriteErrorCode.INVALID_RESPONSE,
            "response is too short for CRC validation",
            request,
        )
    expected = int.from_bytes(frame[-2:], byteorder="little")
    if calculate_crc(frame[:-2]) != expected:
        raise _error(
            ModbusWriteErrorCode.INVALID_RESPONSE,
            "response CRC mismatch",
            request,
        )


def _error_code_from_exception_code(exception_code: int) -> ModbusWriteErrorCode:
    match exception_code:
        case 0x01:
            return ModbusWriteErrorCode.ILLEGAL_FUNCTION
        case 0x02:
            return ModbusWriteErrorCode.ILLEGAL_ADDRESS
        case 0x04:
            return ModbusWriteErrorCode.DEVICE_FAILURE
        case _:
            return ModbusWriteErrorCode.UNKNOWN


def _error(
    code: ModbusWriteErrorCode,
    message: str,
    request: ModbusCoilWriteRequest,
) -> ModbusWriteError:
    return ModbusWriteError(code=code, message=message, request_id=request.request_id)
