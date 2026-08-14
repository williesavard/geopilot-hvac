"""1-Wire DS18B20 adapter tests.

The sysfs root is injectable, so these run on any operating system with no
Raspberry Pi, no probe and no kernel module.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from geopilot.acquisition import AcquisitionErrorCode
from geopilot.onewire import (
    POWER_ON_RESET_MILLIDEGREES,
    FakeOneWireBus,
    OneWireAcquisitionService,
    OneWireBoundaryError,
    OneWireError,
    OneWireErrorCode,
    OneWireReading,
    OneWireSensorDefinition,
    SysfsOneWireBus,
    parse_w1_slave,
)

STAMP = datetime(2026, 8, 11, 12, 0, 0, tzinfo=UTC)
DEVICE = "28-0000075b2c3f"

GOOD_PAYLOAD = (
    "5b 01 4b 46 7f ff 0c 10 4f : crc=4f YES\n"
    "5b 01 4b 46 7f ff 0c 10 4f t=21687\n"
)


def write_probe(root: Path, device_id: str, payload: str) -> None:
    directory = root / device_id
    directory.mkdir(parents=True)
    (directory / "w1_slave").write_text(payload)


def definition(offset: float = 0.0) -> OneWireSensorDefinition:
    return OneWireSensorDefinition(
        device_id=DEVICE,
        source_id="source_onewire",
        sensor_id="sensor_loop_in",
        offset_celsius=offset,
        source_reference="same-bath calibration 2026-08-11",
    )


def test_parses_a_normal_reading() -> None:
    reading = parse_w1_slave(DEVICE, GOOD_PAYLOAD, observed_at=STAMP)

    assert reading.millidegrees == 21687
    assert reading.celsius == pytest.approx(21.687)
    assert reading.observed_at == STAMP


def test_parses_a_negative_reading() -> None:
    payload = GOOD_PAYLOAD.replace("t=21687", "t=-4250")

    reading = parse_w1_slave(DEVICE, payload, observed_at=STAMP)

    assert reading.celsius == pytest.approx(-4.25)


def test_crc_failure_is_reported() -> None:
    payload = GOOD_PAYLOAD.replace("YES", "NO")

    with pytest.raises(OneWireError) as error:
        parse_w1_slave(DEVICE, payload, observed_at=STAMP)

    assert error.value.code is OneWireErrorCode.CRC_FAILED
    assert error.value.acquisition_code is AcquisitionErrorCode.DECODE_FAILED


def test_power_on_reset_sentinel_is_rejected() -> None:
    """85 C is what a DS18B20 reports when no conversion completed."""

    payload = GOOD_PAYLOAD.replace("t=21687", f"t={POWER_ON_RESET_MILLIDEGREES}")

    with pytest.raises(OneWireError) as error:
        parse_w1_slave(DEVICE, payload, observed_at=STAMP)

    assert error.value.code is OneWireErrorCode.POWER_ON_RESET
    assert "not a temperature" in error.value.message


def test_a_genuine_reading_near_the_sentinel_is_accepted() -> None:
    """Only the exact sentinel is rejected, not everything warm."""

    payload = GOOD_PAYLOAD.replace("t=21687", "t=84999")

    reading = parse_w1_slave(DEVICE, payload, observed_at=STAMP)

    assert reading.celsius == pytest.approx(84.999)


def test_missing_temperature_field_is_reported() -> None:
    payload = "5b 01 : crc=4f YES\nno temperature here\n"

    with pytest.raises(OneWireError) as error:
        parse_w1_slave(DEVICE, payload, observed_at=STAMP)

    assert error.value.code is OneWireErrorCode.INVALID_RESPONSE


def test_truncated_payload_is_reported() -> None:
    with pytest.raises(OneWireError) as error:
        parse_w1_slave(DEVICE, "only one line\n", observed_at=STAMP)

    assert error.value.code is OneWireErrorCode.INVALID_RESPONSE


def test_sysfs_bus_reads_a_probe(tmp_path: Path) -> None:
    write_probe(tmp_path, DEVICE, GOOD_PAYLOAD)
    bus = SysfsOneWireBus(tmp_path, clock=lambda: STAMP)

    reading = bus.read_temperature(DEVICE)

    assert reading.celsius == pytest.approx(21.687)
    assert reading.device_id == DEVICE


def test_absent_probe_is_reported(tmp_path: Path) -> None:
    bus = SysfsOneWireBus(tmp_path, clock=lambda: STAMP)

    with pytest.raises(OneWireError) as error:
        bus.read_temperature(DEVICE)

    assert error.value.code is OneWireErrorCode.DEVICE_NOT_FOUND
    assert error.value.acquisition_code is AcquisitionErrorCode.READ_FAILED


def test_available_devices_lists_probes(tmp_path: Path) -> None:
    write_probe(tmp_path, DEVICE, GOOD_PAYLOAD)
    write_probe(tmp_path, "28-0000075b9999", GOOD_PAYLOAD)
    (tmp_path / "w1_bus_master1").mkdir()
    bus = SysfsOneWireBus(tmp_path)

    assert bus.available_devices() == ("28-0000075b2c3f", "28-0000075b9999")


def test_available_devices_is_empty_without_a_bus(tmp_path: Path) -> None:
    assert SysfsOneWireBus(tmp_path / "absent").available_devices() == ()


def test_acquisition_applies_the_calibration_offset() -> None:
    bus = FakeOneWireBus(
        {DEVICE: OneWireReading(device_id=DEVICE, millidegrees=21687, observed_at=STAMP)}
    )
    service = OneWireAcquisitionService(bus)

    raw = service.read_raw_measurement(definition(offset=-0.12))

    assert raw.value == pytest.approx(21.567)
    assert raw.unit == "degC"
    assert raw.sensor_id == "sensor_loop_in"
    assert raw.timestamp == STAMP


def test_acquisition_without_offset_is_the_raw_reading() -> None:
    bus = FakeOneWireBus(
        {DEVICE: OneWireReading(device_id=DEVICE, millidegrees=21687, observed_at=STAMP)}
    )

    raw = OneWireAcquisitionService(bus).read_raw_measurement(definition())

    assert raw.value == pytest.approx(21.687)


def test_bus_errors_propagate_from_the_service() -> None:
    bus = FakeOneWireBus(
        errors={
            DEVICE: OneWireError(
                code=OneWireErrorCode.CRC_FAILED,
                message="bad crc",
                device_id=DEVICE,
            )
        }
    )

    with pytest.raises(OneWireError) as error:
        OneWireAcquisitionService(bus).read_raw_measurement(definition())

    assert error.value.code is OneWireErrorCode.CRC_FAILED


def test_definition_requires_a_source_reference() -> None:
    with pytest.raises(OneWireBoundaryError, match="source_reference"):
        OneWireSensorDefinition(
            device_id=DEVICE,
            source_id="source_onewire",
            sensor_id="sensor_loop_in",
        )


def test_definition_rejects_blank_identifiers() -> None:
    with pytest.raises(OneWireBoundaryError, match="sensor_id"):
        OneWireSensorDefinition(
            device_id=DEVICE,
            source_id="source_onewire",
            sensor_id="   ",
            source_reference="bench",
        )


def test_reading_requires_an_aware_timestamp() -> None:
    with pytest.raises(OneWireBoundaryError, match="timezone-aware"):
        OneWireReading(
            device_id=DEVICE,
            millidegrees=21687,
            observed_at=datetime(2026, 8, 11, 12, 0, 0),
        )


def test_module_does_not_import_storage_or_read_models() -> None:
    """The adapter must not reach past its boundary.

    Checked on the import graph rather than on the text, so prose describing the
    boundary does not trip the test that enforces it.
    """

    import ast

    source = Path("backend/src/geopilot/onewire.py").read_text()
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    forbidden = {
        "geopilot.historian",
        "geopilot.sqlite_historian",
        "geopilot.snapshot",
        "geopilot.export",
        "geopilot.registry",
        "geopilot.runtime",
    }

    assert not (imported & forbidden)
    assert "geopilot.ingestion" in imported
