"""Modbus coil write boundary tests.

Every test injects a fake serial object. No test opens a real port and no test
operates real hardware.
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from geopilot.modbus_pyserial_transport import PySerialModbusConfig, calculate_crc
from geopilot.modbus_pyserial_write import (
    PySerialModbusWriteTransport,
    build_write_coil_frame,
)
from geopilot.modbus_write import (
    COIL_OFF,
    COIL_ON,
    WRITE_SINGLE_COIL,
    FakeModbusWriteTransport,
    ModbusCoilWriteRequest,
    ModbusWriteBoundaryError,
    ModbusWriteError,
    ModbusWriteErrorCode,
)

STAMP = datetime(2026, 8, 14, 12, 0, 0, tzinfo=UTC)
CONFIG = PySerialModbusConfig(port="/dev/cu.fake")


def request(closed: bool = True, address: int = 0, unit_id: int = 1) -> ModbusCoilWriteRequest:
    return ModbusCoilWriteRequest(
        request_id="cmd-1",
        target_id="damper_zone_1",
        unit_id=unit_id,
        address=address,
        closed=closed,
    )


class FakeSerial:
    def __init__(self, response: bytes | None = None, echo: bool = False) -> None:
        self._response = response
        self._echo = echo
        self.written: list[bytes] = []

    def write(self, data: bytes) -> int:
        self.written.append(data)
        if self._echo:
            self._response = data
        return len(data)

    def read(self, size: int) -> bytes:
        if self._response is None:
            return b""
        chunk, self._response = self._response[:size], self._response[size:]
        return chunk


def transport(serial: FakeSerial) -> PySerialModbusWriteTransport:
    return PySerialModbusWriteTransport(CONFIG, serial_port=serial, clock=lambda: STAMP)


def test_coil_value_encodes_relay_state() -> None:
    assert request(closed=True).coil_value == COIL_ON
    assert request(closed=False).coil_value == COIL_OFF


def test_frame_is_a_valid_write_single_coil_request() -> None:
    frame = build_write_coil_frame(request(closed=True, address=3, unit_id=2))

    assert frame[0] == 2
    assert frame[1] == WRITE_SINGLE_COIL
    assert frame[2:4] == b"\x00\x03"
    assert frame[4:6] == b"\xff\x00"
    assert int.from_bytes(frame[-2:], "little") == calculate_crc(frame[:-2])


def test_off_frame_uses_the_zero_value() -> None:
    frame = build_write_coil_frame(request(closed=False))

    assert frame[4:6] == b"\x00\x00"


def test_a_correct_echo_confirms_the_write() -> None:
    serial = FakeSerial(echo=True)

    response = transport(serial).write_coil(request(closed=True))

    assert response.closed is True
    assert response.written_at == STAMP
    assert len(serial.written) == 1


def test_no_response_is_a_timeout() -> None:
    with pytest.raises(ModbusWriteError) as error:
        transport(FakeSerial()).write_coil(request())

    assert error.value.code is ModbusWriteErrorCode.TIMEOUT


def test_a_wrong_echo_is_not_acknowledged() -> None:
    """A relay that answers a state it did not adopt must not read as success."""

    wrong = build_write_coil_frame(request(closed=False))
    serial = FakeSerial(response=wrong)

    with pytest.raises(ModbusWriteError) as error:
        transport(serial).write_coil(request(closed=True))

    assert error.value.code is ModbusWriteErrorCode.NOT_ACKNOWLEDGED


def test_a_bad_crc_is_an_invalid_response() -> None:
    frame = bytearray(build_write_coil_frame(request()))
    frame[-1] ^= 0xFF
    serial = FakeSerial(response=bytes(frame))

    with pytest.raises(ModbusWriteError) as error:
        transport(serial).write_coil(request())

    assert error.value.code is ModbusWriteErrorCode.INVALID_RESPONSE


def test_modbus_exception_responses_are_mapped() -> None:
    for code, expected in (
        (0x01, ModbusWriteErrorCode.ILLEGAL_FUNCTION),
        (0x02, ModbusWriteErrorCode.ILLEGAL_ADDRESS),
        (0x04, ModbusWriteErrorCode.DEVICE_FAILURE),
        (0x09, ModbusWriteErrorCode.UNKNOWN),
    ):
        header = bytes((1, WRITE_SINGLE_COIL | 0x80, code))
        frame = header + calculate_crc(header).to_bytes(2, "little")

        with pytest.raises(ModbusWriteError) as error:
            transport(FakeSerial(response=frame)).write_coil(request())

        assert error.value.code is expected


def test_a_short_response_is_invalid() -> None:
    serial = FakeSerial(response=b"\x01\x05\x00")

    with pytest.raises(ModbusWriteError) as error:
        transport(serial).write_coil(request())

    assert error.value.code is ModbusWriteErrorCode.INVALID_RESPONSE


def test_a_failing_port_is_a_connection_failure() -> None:
    class BrokenSerial(FakeSerial):
        def write(self, data: bytes) -> int:
            raise OSError("port gone")

    with pytest.raises(ModbusWriteError) as error:
        transport(BrokenSerial()).write_coil(request())

    assert error.value.code is ModbusWriteErrorCode.CONNECTION_FAILED


def test_requests_reject_invalid_fields() -> None:
    for kwargs, match in (
        ({"request_id": "  "}, "request_id"),
        ({"target_id": ""}, "target_id"),
        ({"unit_id": 999}, "unit_id"),
        ({"address": -1}, "address"),
        ({"closed": 1}, "closed"),
    ):
        payload: dict[str, Any] = {
            "request_id": "cmd-1",
            "target_id": "damper_zone_1",
            "unit_id": 1,
            "address": 0,
            "closed": True,
        }
        payload.update(kwargs)
        with pytest.raises(ModbusWriteBoundaryError, match=match):
            ModbusCoilWriteRequest(**payload)


def test_fake_transport_records_the_sequence_not_only_the_state() -> None:
    fake = FakeModbusWriteTransport(clock=lambda: STAMP)

    fake.write_coil(request(closed=True))
    fake.write_coil(request(closed=False))
    fake.write_coil(request(closed=True))

    assert [write.closed for write in fake.writes] == [True, False, True]
    assert fake.state_of("damper_zone_1") is True
    assert fake.state_of("unknown") is None


def test_fake_transport_can_script_a_failure() -> None:
    fake = FakeModbusWriteTransport(
        errors={
            "damper_zone_1": ModbusWriteError(
                code=ModbusWriteErrorCode.DEVICE_FAILURE,
                message="relay stuck",
            )
        }
    )

    with pytest.raises(ModbusWriteError):
        fake.write_coil(request())

    assert fake.writes == []


def test_read_transport_has_no_write_capability() -> None:
    """The read-only guarantee is structural: the read module never writes."""

    source = Path("backend/src/geopilot/modbus_transport.py").read_text()
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    assert "geopilot.modbus_write" not in imported
    assert "write_coil" not in source


def test_the_write_module_cannot_reach_the_domain_or_storage() -> None:
    source = Path("backend/src/geopilot/modbus_write.py").read_text()
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    assert not (imported & {"geopilot.domain", "geopilot.historian", "geopilot.runtime"})
