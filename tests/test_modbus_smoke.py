"""Tests for the manual Modbus smoke tool.

Every test injects a fake serial object. No test opens `/dev/*`, `COM*` or any
other real port, and no test calls the tool's port-opening path.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from geopilot.modbus_pyserial_transport import calculate_crc
from geopilot.modbus_transport import ModbusRegisterKind

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from modbus_smoke import (  # noqa: E402
    EXIT_OK,
    EXIT_TRANSPORT_ERROR,
    EXIT_USAGE,
    build_parser,
    main,
)

BASE_ARGS = [
    "--port",
    "/dev/cu.fake",
    "--unit-id",
    "1",
    "--register",
    "input",
    "--address",
    "0",
]


def response_frame(unit_id: int, function_code: int, words: tuple[int, ...]) -> bytes:
    payload = b"".join(word.to_bytes(2, "big") for word in words)
    frame = bytes((unit_id, function_code, len(payload))) + payload
    return frame + calculate_crc(frame).to_bytes(2, "little")


class FakeSerial:
    """Serial stand-in that replays a scripted response, or nothing at all."""

    def __init__(self, *, response: bytes = b"") -> None:
        self._buffer = response
        self.written: list[bytes] = []

    def write(self, data: bytes) -> int:
        self.written.append(data)
        return len(data)

    def read(self, size: int) -> bytes:
        chunk, self._buffer = self._buffer[:size], self._buffer[size:]
        return chunk


def factory_for(serial: FakeSerial) -> Any:
    def build(**_kwargs: Any) -> FakeSerial:
        return serial

    return build


def test_successful_read_prints_raw_words(capsys: pytest.CaptureFixture[str]) -> None:
    serial = FakeSerial(response=response_frame(1, 0x04, (0x00D2, 0x0141)))

    exit_code = main(
        [*BASE_ARGS, "--quantity", "2"],
        serial_factory=factory_for(serial),
    )

    captured = capsys.readouterr()
    assert exit_code == EXIT_OK
    assert "raw hex [0x00d2 0x0141]" in captured.out
    assert "raw decimal [210 321]" in captured.out
    assert "1 succeeded, 0 failed" in captured.out


def test_safety_banner_goes_to_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    serial = FakeSerial(response=response_frame(1, 0x04, (0x0001,)))

    main(BASE_ARGS, serial_factory=factory_for(serial))

    captured = capsys.readouterr()
    assert "qualified electrician" in captured.err
    assert "HARDWARE_BENCH_RUNBOOK" in captured.err


def test_request_frame_is_reported(capsys: pytest.CaptureFixture[str]) -> None:
    serial = FakeSerial(response=response_frame(1, 0x04, (0x0001,)))

    main(BASE_ARGS, serial_factory=factory_for(serial))

    assert "request frame :" in capsys.readouterr().out


def test_empty_bus_reports_timeout_and_fails(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(BASE_ARGS, serial_factory=factory_for(FakeSerial()))

    captured = capsys.readouterr()
    assert exit_code == EXIT_TRANSPORT_ERROR
    assert "FAILED timeout" in captured.out
    assert "0 succeeded, 1 failed" in captured.out


def test_modbus_exception_response_is_reported(capsys: pytest.CaptureFixture[str]) -> None:
    header = bytes((1, 0x04 | 0x80, 0x02))
    frame = header + calculate_crc(header).to_bytes(2, "little")

    exit_code = main(BASE_ARGS, serial_factory=factory_for(FakeSerial(response=frame)))

    captured = capsys.readouterr()
    assert exit_code == EXIT_TRANSPORT_ERROR
    assert "FAILED illegal_address" in captured.out


def test_repeat_runs_every_attempt_despite_failures(
    capsys: pytest.CaptureFixture[str],
) -> None:
    one_good_read = response_frame(1, 0x04, (0x0007,))
    serial = FakeSerial(response=one_good_read)

    exit_code = main(
        [*BASE_ARGS, "--repeat", "3"],
        serial_factory=factory_for(serial),
    )

    captured = capsys.readouterr()
    assert exit_code == EXIT_TRANSPORT_ERROR
    assert "1 succeeded, 2 failed, 3 attempted" in captured.out
    assert len(serial.written) == 3


def test_invalid_configuration_is_a_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(
        [*BASE_ARGS, "--baudrate", "0"],
        serial_factory=factory_for(FakeSerial()),
    )

    assert exit_code == EXIT_USAGE
    assert "baudrate" in capsys.readouterr().err


def test_repeat_below_one_is_a_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(
        [*BASE_ARGS, "--repeat", "0"],
        serial_factory=factory_for(FakeSerial()),
    )

    assert exit_code == EXIT_USAGE
    assert "--repeat" in capsys.readouterr().err


def test_every_bus_coordinate_is_required() -> None:
    parser = build_parser()
    for omitted in ("--port", "--unit-id", "--register", "--address"):
        arguments = list(BASE_ARGS)
        position = arguments.index(omitted)
        del arguments[position : position + 2]
        with pytest.raises(SystemExit):
            parser.parse_args(arguments)


def test_register_families_are_limited_to_read_only_kinds() -> None:
    parser = build_parser()

    for kind in ModbusRegisterKind:
        parsed = parser.parse_args(
            ["--port", "p", "--unit-id", "1", "--register", kind.value, "--address", "0"]
        )
        assert parsed.register == kind.value

    with pytest.raises(SystemExit):
        parser.parse_args(
            ["--port", "p", "--unit-id", "1", "--register", "coil", "--address", "0"]
        )
