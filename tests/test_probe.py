"""Live probe tests.

No test opens a serial port. The 1-Wire tests point at a fixture directory tree
rather than a Raspberry Pi, so none of them needs Linux either.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from geopilot.configuration import BitReadConfig, OneWireReadConfig, RegisterReadConfig
from geopilot.modbus_transport import (
    FakeModbusBitTransport,
    FakeModbusTransport,
    ModbusBitKind,
    ModbusBitReadResponse,
    ModbusReadResponse,
    ModbusRegisterKind,
    ModbusTransportError,
    ModbusTransportErrorCode,
)
from geopilot.onewire import SysfsOneWireBus
from geopilot.probe import (
    ProbeKind,
    probe_bits,
    probe_onewire,
    probe_registers,
)
from geopilot.register_decoder import RegisterDataType

STAMP = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)


def w1_tree(tmp_path: Path, devices: dict[str, float]) -> Path:
    """Build a sysfs-shaped tree, one directory per probe."""

    for device_id, celsius in devices.items():
        folder = tmp_path / device_id
        folder.mkdir(parents=True)
        millidegrees = int(round(celsius * 1000))
        (folder / "w1_slave").write_text(
            "3d 00 4b 46 ff ff 0c 10 fd : crc=fd YES\n"
            f"3d 00 4b 46 ff ff 0c 10 fd t={millidegrees}\n"
        )
    return tmp_path


def onewire_read(device_id: str, sensor_id: str, offset: float = 0.0) -> OneWireReadConfig:
    return OneWireReadConfig(
        read_id=f"read_{sensor_id}",
        source_id="source_onewire",
        sensor_id=sensor_id,
        device_id=device_id,
        unit="degC",
        offset_celsius=offset,
        source_reference="bench, 2026-08-17",
    )


def test_every_probe_on_the_bus_is_listed_configured_or_not(tmp_path: Path) -> None:
    """The id you have not written down yet is the one you need most."""

    root = w1_tree(tmp_path, {"28-aaaa": 21.5, "28-bbbb": 4.25, "28-cccc": -8.0})
    bus = SysfsOneWireBus(root)

    results = probe_onewire(bus, (onewire_read("28-aaaa", "sensor_tank"),))

    assert len(results) == 3
    named = {item.reference: item for item in results}
    assert named["28-aaaa"].sensor_id == "sensor_tank"
    assert named["28-aaaa"].configured
    assert not named["28-bbbb"].configured
    assert "not in the configuration" in named["28-bbbb"].detail


def test_the_reading_comes_back_with_the_id(tmp_path: Path) -> None:
    """This is the hand-warming trick: probe, warm one, probe again."""

    bus = SysfsOneWireBus(w1_tree(tmp_path, {"28-aaaa": 21.5, "28-bbbb": 31.75}))

    readings = {item.reference: item.value for item in probe_onewire(bus, ())}

    assert readings == {"28-aaaa": 21.5, "28-bbbb": 31.75}


def test_the_configured_offset_is_applied(tmp_path: Path) -> None:
    """So a probe and a recorded reading agree about the same probe."""

    bus = SysfsOneWireBus(w1_tree(tmp_path, {"28-aaaa": 21.5}))

    result = probe_onewire(bus, (onewire_read("28-aaaa", "sensor_tank", offset=-0.4),))[0]

    assert result.value == pytest.approx(21.1)


def test_a_configured_probe_that_is_absent_is_reported(tmp_path: Path) -> None:
    bus = SysfsOneWireBus(w1_tree(tmp_path, {"28-aaaa": 21.5}))

    results = probe_onewire(bus, (onewire_read("28-dead", "sensor_gone"),))

    missing = next(item for item in results if item.reference == "28-dead")
    assert not missing.ok
    assert missing.value is None
    assert missing.configured
    assert "device_not_found" in missing.detail


def test_the_reset_value_is_marked_suspect_rather_than_reported_as_a_temperature(
    tmp_path: Path,
) -> None:
    """85 °C exactly is a probe that was read before it finished converting.

    The adapter refuses to call it a temperature, which is right. What a probe
    adds is naming the fault it almost always is.
    """

    bus = SysfsOneWireBus(w1_tree(tmp_path, {"28-aaaa": 85.0}))

    result = probe_onewire(bus, (onewire_read("28-aaaa", "sensor_tank"),))[0]

    assert not result.ok
    assert result.value is None
    assert result.suspect
    assert "pull-up" in result.detail


def test_a_plausible_temperature_is_not_suspect(tmp_path: Path) -> None:
    """84.9 is a temperature. Only 85.000 exactly is the sentinel."""

    bus = SysfsOneWireBus(w1_tree(tmp_path, {"28-aaaa": 84.9}))
    result = probe_onewire(bus, (onewire_read("28-aaaa", "sensor_a"),))[0]

    assert result.ok
    assert not result.suspect


def test_an_absent_probe_is_not_marked_as_a_wiring_fault(tmp_path: Path) -> None:
    """Silence and a not-ready answer point at different things."""

    bus = SysfsOneWireBus(w1_tree(tmp_path, {}))
    result = probe_onewire(bus, (onewire_read("28-dead", "sensor_a"),))[0]

    assert not result.ok
    assert not result.suspect
    assert "pull-up" not in result.detail


def test_an_empty_bus_probes_to_nothing(tmp_path: Path) -> None:
    assert probe_onewire(SysfsOneWireBus(w1_tree(tmp_path, {})), ()) == ()


def register_read(
    quantity: int = 1, data_type: RegisterDataType = RegisterDataType.INT16
) -> RegisterReadConfig:
    return RegisterReadConfig(
        read_id="read_loop_in",
        source_id="source_bus",
        sensor_id="sensor_loop_in",
        unit_id=1,
        register_kind=ModbusRegisterKind.INPUT,
        address=1,
        quantity=quantity,
        data_type=data_type,
        unit="degC",
        scale=0.1,
        offset=0.0,
        source_reference="XY-MD02 manual, 2026-08-17",
    )


def test_a_register_is_read_and_decoded() -> None:
    transport = FakeModbusTransport(
        responses=(
            ModbusReadResponse(request_id="probe-read_loop_in", words=(215,), observed_at=STAMP),
        )
    )

    result = probe_registers(lambda source_id: transport, (register_read(),))[0]

    assert result.kind is ProbeKind.REGISTER
    assert result.value == pytest.approx(21.5)
    assert result.unit == "degC"
    assert "0x00D7" in result.detail


def test_a_negative_register_value_is_decoded_as_signed() -> None:
    """A loop below zero is the normal case here, and would read as 6553 unsigned."""

    transport = FakeModbusTransport(
        responses=(
            ModbusReadResponse(
                request_id="probe-read_loop_in", words=(0xFFCE,), observed_at=STAMP
            ),
        )
    )

    result = probe_registers(lambda source_id: transport, (register_read(),))[0]

    assert result.value == pytest.approx(-5.0)


def test_a_bus_that_does_not_answer_is_reported_not_raised() -> None:
    """A probe reports what happened; it is never the thing that crashes."""

    transport = FakeModbusTransport(
        errors=(
            ModbusTransportError(
                code=ModbusTransportErrorCode.TIMEOUT,
                message="no answer",
                request_id="probe-read_loop_in",
            ),
        )
    )

    result = probe_registers(lambda source_id: transport, (register_read(),))[0]

    assert not result.ok
    assert result.value is None
    assert "no answer" in result.detail


def test_a_busy_port_is_reported_rather_than_retried() -> None:
    def explode(source_id: str) -> FakeModbusTransport:
        raise OSError("[Errno 16] Device or resource busy: '/dev/ttyUSB0'")

    result = probe_registers(explode, (register_read(),))[0]

    assert not result.ok
    assert "busy" in result.detail


def test_a_quantity_the_type_cannot_hold_is_refused_not_guessed() -> None:
    """A wrong quantity in the configuration is what a probe should surface."""

    transport = FakeModbusTransport(
        responses=(
            ModbusReadResponse(
                request_id="probe-read_loop_in", words=(1, 2), observed_at=STAMP
            ),
        )
    )

    result = probe_registers(lambda source_id: transport, (register_read(quantity=2),))[0]

    assert not result.ok
    assert result.value is None
    assert "cannot be decoded" in result.detail


def bit_read(inverted: bool = False) -> BitReadConfig:
    return BitReadConfig(
        read_id="read_zone_1",
        source_id="source_bus",
        sensor_id="sensor_zone_1",
        unit_id=2,
        bit_kind=ModbusBitKind.DISCRETE_INPUT,
        address=0,
        inverted=inverted,
        source_reference="relay panel, 2026-08-17",
    )


def test_a_discrete_input_is_read_now() -> None:
    transport = FakeModbusBitTransport(
        responses=(
            ModbusBitReadResponse(
                request_id="probe-read_zone_1", bits=(True,), observed_at=STAMP
            ),
        )
    )

    result = probe_bits(lambda source_id: transport, (bit_read(),))[0]

    assert result.kind is ProbeKind.BIT
    assert result.value == 1.0
    assert result.unit == "state"


def test_inversion_is_applied_exactly_as_the_runtime_applies_it() -> None:
    """Otherwise a probe and a recorded reading would disagree about "asserted"."""

    transport = FakeModbusBitTransport(
        responses=(
            ModbusBitReadResponse(
                request_id="probe-read_zone_1", bits=(True,), observed_at=STAMP
            ),
        )
    )

    result = probe_bits(lambda source_id: transport, (bit_read(inverted=True),))[0]

    assert result.value == 0.0
    assert "inverted" in result.detail


def test_a_bit_read_failure_is_reported() -> None:
    transport = FakeModbusBitTransport(
        errors=(
            ModbusTransportError(
                code=ModbusTransportErrorCode.INVALID_RESPONSE,
                message="bad crc",
                request_id="probe-read_zone_1",
            ),
        )
    )

    result = probe_bits(lambda source_id: transport, (bit_read(),))[0]

    assert not result.ok
    assert "bad crc" in result.detail


def test_a_label_falls_back_to_the_bus_reference(tmp_path: Path) -> None:
    """An undiscovered device has no sensor id; it must still be nameable."""

    bus = SysfsOneWireBus(w1_tree(tmp_path, {"28-aaaa": 3.0}))

    assert probe_onewire(bus, ())[0].label == "28-aaaa"
