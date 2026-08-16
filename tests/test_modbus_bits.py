"""Discrete input and coil read tests.

Every test injects a fake serial object. No test opens a real port.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from geopilot.modbus_pyserial_transport import (
    PySerialModbusBitTransport,
    PySerialModbusConfig,
    build_bit_read_frame,
    calculate_crc,
)
from geopilot.modbus_transport import (
    FakeModbusBitTransport,
    ModbusBitKind,
    ModbusBitReadRequest,
    ModbusBitReadResponse,
    ModbusTransportBoundaryError,
    ModbusTransportError,
    ModbusTransportErrorCode,
    unpack_bits,
)

STAMP = datetime(2026, 8, 16, 12, 0, 0, tzinfo=UTC)
CONFIG = PySerialModbusConfig(port="/dev/cu.fake")


def request(
    quantity: int = 4,
    kind: ModbusBitKind = ModbusBitKind.DISCRETE_INPUT,
    address: int = 0,
) -> ModbusBitReadRequest:
    return ModbusBitReadRequest(
        request_id="zones",
        source_id="source_bus",
        unit_id=1,
        bit_kind=kind,
        address=address,
        quantity=quantity,
    )


def response_frame(unit_id: int, function_code: int, payload: bytes) -> bytes:
    frame = bytes((unit_id, function_code, len(payload))) + payload
    return frame + calculate_crc(frame).to_bytes(2, "little")


class FakeSerial:
    def __init__(self, response: bytes = b"") -> None:
        self._response = response
        self.written: list[bytes] = []

    def write(self, data: bytes) -> int:
        self.written.append(data)
        return len(data)

    def read(self, size: int) -> bytes:
        chunk, self._response = self._response[:size], self._response[size:]
        return chunk


def transport(serial: FakeSerial) -> PySerialModbusBitTransport:
    return PySerialModbusBitTransport(CONFIG, serial_port=serial, clock=lambda: STAMP)


def test_unpacks_least_significant_bit_first() -> None:
    # 0b00000101 -> inputs 1 and 3 are on
    assert unpack_bits(b"\x05", 4) == (True, False, True, False)


def test_padding_bits_are_discarded() -> None:
    """A byte carries eight bits; only the requested ones are data."""

    assert len(unpack_bits(b"\xff", 3)) == 3


def test_unpacks_across_byte_boundaries() -> None:
    bits = unpack_bits(b"\x00\x01", 9)

    assert bits[8] is True
    assert not any(bits[:8])


def test_discrete_input_frame_uses_function_two() -> None:
    frame = build_bit_read_frame(request(quantity=4))

    assert frame[1] == 0x02
    assert frame[4:6] == b"\x00\x04"
    assert int.from_bytes(frame[-2:], "little") == calculate_crc(frame[:-2])


def test_coil_frame_uses_function_one() -> None:
    frame = build_bit_read_frame(request(kind=ModbusBitKind.COIL))

    assert frame[1] == 0x01


def test_reads_four_zone_calls() -> None:
    serial = FakeSerial(response_frame(1, 0x02, b"\x05"))

    result = transport(serial).read_bits(request(quantity=4))

    assert result.bits == (True, False, True, False)
    assert result.observed_at == STAMP


def test_reading_coils_back_reports_actual_relay_state() -> None:
    """Reading coils is how a controller avoids assuming where a relay is."""

    serial = FakeSerial(response_frame(1, 0x01, b"\x02"))

    result = transport(serial).read_bits(request(quantity=2, kind=ModbusBitKind.COIL))

    assert result.bits == (False, True)


def test_no_response_is_a_timeout() -> None:
    with pytest.raises(ModbusTransportError) as error:
        transport(FakeSerial()).read_bits(request())

    assert error.value.code is ModbusTransportErrorCode.TIMEOUT


def test_wrong_byte_count_is_invalid() -> None:
    serial = FakeSerial(response_frame(1, 0x02, b"\x05\x00"))

    with pytest.raises(ModbusTransportError) as error:
        transport(serial).read_bits(request(quantity=4))

    assert error.value.code is ModbusTransportErrorCode.INVALID_RESPONSE


def test_wrong_unit_is_invalid() -> None:
    serial = FakeSerial(response_frame(9, 0x02, b"\x05"))

    with pytest.raises(ModbusTransportError) as error:
        transport(serial).read_bits(request(quantity=4))

    assert error.value.code is ModbusTransportErrorCode.INVALID_RESPONSE


def test_wrong_function_is_invalid() -> None:
    serial = FakeSerial(response_frame(1, 0x01, b"\x05"))

    with pytest.raises(ModbusTransportError) as error:
        transport(serial).read_bits(request(quantity=4))

    assert error.value.code is ModbusTransportErrorCode.INVALID_RESPONSE


def test_bad_crc_is_invalid() -> None:
    frame = bytearray(response_frame(1, 0x02, b"\x05"))
    frame[-1] ^= 0xFF

    with pytest.raises(ModbusTransportError) as error:
        transport(FakeSerial(bytes(frame))).read_bits(request(quantity=4))

    assert error.value.code is ModbusTransportErrorCode.INVALID_RESPONSE


def test_modbus_exceptions_are_mapped() -> None:
    for code, expected in (
        (0x01, ModbusTransportErrorCode.ILLEGAL_FUNCTION),
        (0x02, ModbusTransportErrorCode.ILLEGAL_ADDRESS),
        (0x04, ModbusTransportErrorCode.DEVICE_FAILURE),
    ):
        header = bytes((1, 0x02 | 0x80, code))
        frame = header + calculate_crc(header).to_bytes(2, "little")

        with pytest.raises(ModbusTransportError) as error:
            transport(FakeSerial(frame)).read_bits(request())

        assert error.value.code is expected


def test_requests_reject_invalid_quantity() -> None:
    for quantity in (0, 2001):
        with pytest.raises(ModbusTransportBoundaryError, match="quantity"):
            request(quantity=quantity)


def test_responses_reject_non_boolean_bits() -> None:
    with pytest.raises(ModbusTransportBoundaryError, match="booleans"):
        ModbusBitReadResponse(
            request_id="zones",
            bits=(1,),  # type: ignore[arg-type]
            observed_at=STAMP,
        )


def test_fake_bit_transport_replays_and_records() -> None:
    fake = FakeModbusBitTransport(
        responses=(
            ModbusBitReadResponse(
                request_id="zones",
                bits=(True, False),
                observed_at=STAMP,
            ),
        )
    )

    result = fake.read_bits(request(quantity=2))

    assert result.bits == (True, False)
    assert fake.read_request_ids() == ("zones",)


def test_fake_bit_transport_can_script_an_error() -> None:
    fake = FakeModbusBitTransport(
        errors=(
            ModbusTransportError(
                code=ModbusTransportErrorCode.TIMEOUT,
                message="no answer",
                request_id="zones",
            ),
        )
    )

    with pytest.raises(ModbusTransportError):
        fake.read_bits(request())
