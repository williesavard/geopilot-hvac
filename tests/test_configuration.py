"""Configuration loading and validation tests."""

from __future__ import annotations

import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from geopilot.configuration import (
    CONFIGURATION_VERSION,
    ConfigurationError,
    load_configuration,
    parse_configuration,
)
from geopilot.domain import EquipmentType, MeasurementKind, SensorMeasurementKind, SystemType
from geopilot.modbus_transport import ModbusBitKind, ModbusRegisterKind
from geopilot.register_decoder import RegisterDataType

STAMP = datetime(2026, 8, 11, tzinfo=UTC)
EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "installation.example.toml"


def document() -> dict[str, Any]:
    return {
        "version": CONFIGURATION_VERSION,
        "storage": {"database": "geopilot.sqlite3"},
        "residence": {"id": "residence_home", "name": "Home", "timezone": "America/Toronto"},
        "system": [
            {"id": "system_main", "name": "Main", "system_type": "hydronic"},
        ],
        "equipment": [
            {
                "id": "equipment_hp",
                "system_id": "system_main",
                "name": "Heat pump",
                "equipment_type": "heat_pump",
            },
        ],
        "sensor": [
            {
                "id": "sensor_a",
                "equipment_id": "equipment_hp",
                "name": "Loop in",
                "measurement_kind": "temperature",
                "sensor_kind": "temperature",
                "unit": "degC",
                "source_id": "source_bus",
            },
        ],
        "source": [{"id": "source_bus", "port": "/dev/cu.fake"}],
        "read": [
            {
                "id": "read_a",
                "source_id": "source_bus",
                "sensor_id": "sensor_a",
                "unit_id": 1,
                "register": "input",
                "address": 1,
                "data_type": "int16",
                "unit": "degC",
                "scale": 0.1,
                "source_reference": "bench manual page 4",
            },
        ],
    }


def test_parses_a_complete_configuration() -> None:
    config = parse_configuration(document(), created_at=STAMP)

    assert config.version == CONFIGURATION_VERSION
    assert config.database == Path("geopilot.sqlite3")
    assert config.residence.id == "residence_home"
    assert config.systems[0].system_type is SystemType.HYDRONIC
    assert config.equipment[0].equipment_type is EquipmentType.HEAT_PUMP
    assert config.sensors[0].measurement_kind is MeasurementKind.TEMPERATURE
    assert config.sensors[0].sensor_kind is SensorMeasurementKind.TEMPERATURE
    assert config.reads[0].register_kind is ModbusRegisterKind.INPUT
    assert config.reads[0].data_type is RegisterDataType.INT16


def test_serial_defaults_are_applied() -> None:
    config = parse_configuration(document(), created_at=STAMP)
    source = config.source("source_bus")

    assert (source.baudrate, source.parity, source.bytesize) == (9600, "N", 8)
    assert source.timeout == 1.0


def test_quantity_scale_and_offset_have_defaults() -> None:
    config = parse_configuration(document(), created_at=STAMP)

    assert config.reads[0].quantity == 1
    assert config.reads[0].offset == 0.0


def test_unknown_source_lookup_is_rejected() -> None:
    config = parse_configuration(document(), created_at=STAMP)

    with pytest.raises(ConfigurationError, match="unknown source"):
        config.source("missing")


def test_unsupported_version_is_rejected() -> None:
    payload = document()
    payload["version"] = CONFIGURATION_VERSION + 1

    with pytest.raises(ConfigurationError, match="unsupported configuration version"):
        parse_configuration(payload, created_at=STAMP)


def test_sensor_referencing_unknown_equipment_is_rejected() -> None:
    payload = document()
    payload["sensor"][0]["equipment_id"] = "missing"

    with pytest.raises(ConfigurationError, match="unknown equipment"):
        parse_configuration(payload, created_at=STAMP)


def test_sensor_referencing_unknown_source_is_rejected() -> None:
    payload = document()
    payload["sensor"][0]["source_id"] = "missing"

    with pytest.raises(ConfigurationError, match="unknown source"):
        parse_configuration(payload, created_at=STAMP)


def test_equipment_referencing_unknown_system_is_rejected() -> None:
    payload = document()
    payload["equipment"][0]["system_id"] = "missing"

    with pytest.raises(ConfigurationError, match="unknown system"):
        parse_configuration(payload, created_at=STAMP)


def test_read_referencing_unknown_sensor_is_rejected() -> None:
    payload = document()
    payload["read"][0]["sensor_id"] = "missing"

    with pytest.raises(ConfigurationError, match="unknown sensor"):
        parse_configuration(payload, created_at=STAMP)


def test_duplicate_ids_are_rejected() -> None:
    payload = document()
    payload["sensor"].append(dict(payload["sensor"][0]))

    with pytest.raises(ConfigurationError, match="duplicate sensor id"):
        parse_configuration(payload, created_at=STAMP)


def test_missing_system_is_rejected() -> None:
    payload = document()
    payload["system"] = []
    payload["equipment"][0]["system_id"] = "system_main"

    with pytest.raises(ConfigurationError, match="at least one"):
        parse_configuration(payload, created_at=STAMP)


def test_unknown_enum_value_lists_the_allowed_values() -> None:
    payload = document()
    payload["read"][0]["register"] = "coil"

    with pytest.raises(ConfigurationError, match="holding, input"):
        parse_configuration(payload, created_at=STAMP)


def test_source_reference_is_required_on_every_read() -> None:
    payload = document()
    del payload["read"][0]["source_reference"]

    with pytest.raises(ConfigurationError, match="source_reference"):
        parse_configuration(payload, created_at=STAMP)


def test_missing_file_is_reported_clearly(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="not found"):
        load_configuration(tmp_path / "absent.toml")


def test_invalid_toml_is_reported_clearly(tmp_path: Path) -> None:
    broken = tmp_path / "broken.toml"
    broken.write_text("version = = 1")

    with pytest.raises(ConfigurationError, match="not valid TOML"):
        load_configuration(broken)


def test_shipped_example_configuration_is_valid() -> None:
    config = load_configuration(EXAMPLE, created_at=STAMP)

    assert config.version == CONFIGURATION_VERSION
    assert config.sensors
    assert config.reads


def test_shipped_example_keeps_its_comments() -> None:
    """The comments are the point. A stripped example teaches nothing."""

    text = EXAMPLE.read_text()

    assert "PLACEHOLDER" in text
    assert text.count("#") > 10
    # It must still parse.
    with EXAMPLE.open("rb") as handle:
        tomllib.load(handle)


def document_with_bits() -> dict[str, Any]:
    payload = document()
    payload["sensor"].append(
        {
            "id": "sensor_zone_1_call",
            "equipment_id": "equipment_hp",
            "name": "Zone 1 call",
            "measurement_kind": "state",
            "sensor_kind": "state",
            "unit": "state",
            "source_id": "source_bus",
        }
    )
    payload["bit_read"] = [
        {
            "id": "read_zone_1",
            "source_id": "source_bus",
            "sensor_id": "sensor_zone_1_call",
            "unit_id": 2,
            "bit": "discrete_input",
            "address": 0,
            "source_reference": "relay panel mapping, 2026-08-16",
        }
    ]
    return payload


def test_bit_reads_are_parsed() -> None:
    config = parse_configuration(document_with_bits(), created_at=STAMP)

    read = config.bit_reads[0]
    assert read.bit_kind is ModbusBitKind.DISCRETE_INPUT
    assert read.unit_id == 2
    assert read.source_reference.startswith("relay panel")


def test_inversion_defaults_to_false() -> None:
    """A stored 1 means asserted, so inversion must be opted into."""

    config = parse_configuration(document_with_bits(), created_at=STAMP)

    assert config.bit_reads[0].inverted is False


def test_inversion_can_be_declared() -> None:
    payload = document_with_bits()
    payload["bit_read"][0]["inverted"] = True

    config = parse_configuration(payload, created_at=STAMP)

    assert config.bit_reads[0].inverted is True


def test_inversion_must_be_a_boolean() -> None:
    payload = document_with_bits()
    payload["bit_read"][0]["inverted"] = "yes"

    with pytest.raises(ConfigurationError, match="inverted"):
        parse_configuration(payload, created_at=STAMP)


def test_a_bit_read_requires_a_source_reference() -> None:
    payload = document_with_bits()
    del payload["bit_read"][0]["source_reference"]

    with pytest.raises(ConfigurationError, match="source_reference"):
        parse_configuration(payload, created_at=STAMP)


def test_a_bit_read_referencing_an_unknown_sensor_is_rejected() -> None:
    payload = document_with_bits()
    payload["bit_read"][0]["sensor_id"] = "missing"

    with pytest.raises(ConfigurationError, match="unknown sensor"):
        parse_configuration(payload, created_at=STAMP)


def test_a_bit_read_referencing_an_unknown_source_is_rejected() -> None:
    payload = document_with_bits()
    payload["bit_read"][0]["source_id"] = "missing"

    with pytest.raises(ConfigurationError, match="unknown source"):
        parse_configuration(payload, created_at=STAMP)


def test_duplicate_bit_read_ids_are_rejected() -> None:
    payload = document_with_bits()
    payload["bit_read"].append(dict(payload["bit_read"][0]))

    with pytest.raises(ConfigurationError, match="duplicate bit read id"):
        parse_configuration(payload, created_at=STAMP)


def test_an_installation_without_bit_reads_still_parses() -> None:
    config = parse_configuration(document(), created_at=STAMP)

    assert config.bit_reads == ()
