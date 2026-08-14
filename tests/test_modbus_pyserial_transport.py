from __future__ import annotations

import ast
import importlib
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from geopilot.modbus_pyserial_transport import (
    PySerialModbusConfig,
    PySerialModbusTransport,
    build_read_request_frame,
    calculate_crc,
)
from geopilot.modbus_transport import (
    ModbusReadRequest,
    ModbusRegisterKind,
    ModbusTransportBoundaryError,
    ModbusTransportError,
    ModbusTransportErrorCode,
)

OBSERVED_AT = datetime(2026, 7, 21, 12, 5, 0, tzinfo=UTC)


class FakeSerial:
    def __init__(self, chunks: tuple[bytes, ...], *, fail_write: bool = False) -> None:
        self._chunks = list(chunks)
        self._fail_write = fail_write
        self.writes: list[bytes] = []

    def write(self, data: bytes) -> int:
        if self._fail_write:
            raise OSError("write failed")
        self.writes.append(data)
        return len(data)

    def read(self, size: int) -> bytes:
        if not self._chunks:
            return b""
        chunk = self._chunks.pop(0)
        assert len(chunk) <= size
        return chunk


def test_module_imports_without_pyserial_installed() -> None:
    sys.modules.pop("serial", None)

    module = importlib.import_module("geopilot.modbus_pyserial_transport")

    assert module.PySerialModbusTransport is PySerialModbusTransport


def test_pyserial_config_is_explicit_and_validated() -> None:
    config = PySerialModbusConfig(
        port="/dev/ttyUSB0",
        baudrate=19200,
        parity="E",
        stopbits=1,
        bytesize=8,
        timeout=0.5,
    )

    assert config.port == "/dev/ttyUSB0"
    assert config.baudrate == 19200
    assert config.parity == "E"
    assert config.timeout == 0.5


def test_pyserial_config_rejects_missing_port() -> None:
    with pytest.raises(ModbusTransportBoundaryError, match="port"):
        PySerialModbusConfig(port="")


def test_build_read_holding_registers_request_frame() -> None:
    request = read_request(
        register_kind=ModbusRegisterKind.HOLDING,
        address=0x006B,
        quantity=0x0003,
    )

    assert build_read_request_frame(request) == bytes.fromhex("0103006b00037417")


def test_build_read_input_registers_request_frame() -> None:
    request = read_request(
        register_kind=ModbusRegisterKind.INPUT,
        address=0x0001,
        quantity=0x0002,
    )

    assert build_read_request_frame(request) == bytes.fromhex("010400010002200b")


def test_crc_matches_known_modbus_vector() -> None:
    assert calculate_crc(bytes.fromhex("0103006b0003")) == 0x1774


def test_transport_parses_minimal_holding_register_response() -> None:
    serial_port = FakeSerial(
        chunks=(
            bytes.fromhex("010302"),
            _data_with_crc(bytes.fromhex("010302"), bytes.fromhex("00d7")),
        )
    )
    transport = transport_for(serial_port)

    response = transport.read_registers(
        read_request(
            register_kind=ModbusRegisterKind.HOLDING,
            address=0x006B,
            quantity=1,
        )
    )

    assert serial_port.writes == [bytes.fromhex("0103006b0001f5d6")]
    assert response.words == (215,)
    assert response.observed_at == OBSERVED_AT


def test_transport_parses_minimal_input_register_response() -> None:
    serial_port = FakeSerial(
        chunks=(
            bytes.fromhex("010402"),
            _data_with_crc(bytes.fromhex("010402"), bytes.fromhex("01ae")),
        )
    )
    transport = transport_for(serial_port)

    response = transport.read_registers(
        read_request(
            register_kind=ModbusRegisterKind.INPUT,
            address=0x0001,
            quantity=1,
        )
    )

    assert serial_port.writes == [bytes.fromhex("010400010001600a")]
    assert response.words == (430,)


def test_transport_maps_timeout() -> None:
    transport = transport_for(FakeSerial(chunks=()))

    with pytest.raises(ModbusTransportError) as exc_info:
        transport.read_registers(read_request())

    assert exc_info.value.code is ModbusTransportErrorCode.TIMEOUT


def test_transport_maps_serial_write_failure_to_connection_failed() -> None:
    transport = transport_for(FakeSerial(chunks=(), fail_write=True))

    with pytest.raises(ModbusTransportError) as exc_info:
        transport.read_registers(read_request())

    assert exc_info.value.code is ModbusTransportErrorCode.CONNECTION_FAILED


def test_transport_maps_short_response_to_invalid_response() -> None:
    transport = transport_for(FakeSerial(chunks=(bytes.fromhex("0103"),)))

    with pytest.raises(ModbusTransportError) as exc_info:
        transport.read_registers(read_request())

    assert exc_info.value.code is ModbusTransportErrorCode.INVALID_RESPONSE


def test_transport_maps_crc_mismatch_to_invalid_response() -> None:
    transport = transport_for(
        FakeSerial(
            chunks=(
                bytes.fromhex("010302"),
                bytes.fromhex("00d70000"),
            )
        )
    )

    with pytest.raises(ModbusTransportError) as exc_info:
        transport.read_registers(read_request(quantity=1))

    assert exc_info.value.code is ModbusTransportErrorCode.INVALID_RESPONSE


@pytest.mark.parametrize(
    ("exception_code", "error_code"),
    (
        (0x01, ModbusTransportErrorCode.ILLEGAL_FUNCTION),
        (0x02, ModbusTransportErrorCode.ILLEGAL_ADDRESS),
        (0x04, ModbusTransportErrorCode.DEVICE_FAILURE),
        (0x0B, ModbusTransportErrorCode.UNKNOWN),
    ),
)
def test_transport_maps_modbus_exception_response(
    exception_code: int,
    error_code: ModbusTransportErrorCode,
) -> None:
    header = bytes((0x01, 0x83, exception_code))
    transport = transport_for(FakeSerial(chunks=(header, _crc_bytes(header))))

    with pytest.raises(ModbusTransportError) as exc_info:
        transport.read_registers(read_request(register_kind=ModbusRegisterKind.HOLDING))

    assert exc_info.value.code is error_code


def test_transport_does_not_depend_on_domain_modules() -> None:
    source = Path("backend/src/geopilot/modbus_pyserial_transport.py").read_text()
    parsed = ast.parse(source)
    imports: list[str] = []
    for node in ast.walk(parsed):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            imports.append(node.module)

    assert "geopilot.domain" not in imports
    assert "geopilot.ingestion" not in imports
    assert "geopilot.historian" not in imports
    assert "geopilot.snapshot" not in imports
    assert "serial" not in imports


def transport_for(serial_port: FakeSerial) -> PySerialModbusTransport:
    def serial_factory(**_: Any) -> FakeSerial:
        return serial_port

    return PySerialModbusTransport(
        PySerialModbusConfig(port="/dev/fake"),
        serial_factory=serial_factory,
        clock=lambda: OBSERVED_AT,
    )


def read_request(
    *,
    register_kind: ModbusRegisterKind = ModbusRegisterKind.HOLDING,
    address: int = 0x006B,
    quantity: int = 1,
) -> ModbusReadRequest:
    return ModbusReadRequest(
        request_id="temperature",
        source_id="source_simulated_modbus",
        unit_id=1,
        register_kind=register_kind,
        address=address,
        quantity=quantity,
    )


def _data_with_crc(header: bytes, payload: bytes) -> bytes:
    return payload + _crc_bytes(header + payload)


def _crc_bytes(frame: bytes) -> bytes:
    return calculate_crc(frame).to_bytes(2, byteorder="little")
