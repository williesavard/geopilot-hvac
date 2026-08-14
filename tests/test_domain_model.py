from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest
from geopilot.domain import (
    Alert,
    DataQuality,
    Equipment,
    EquipmentOperationalState,
    EquipmentState,
    EquipmentType,
    Event,
    GeoPilotDomainError,
    HVACSystem,
    Measurement,
    MeasurementKind,
    ProtocolName,
    ProtocolSource,
    Residence,
    Sensor,
    SensorMeasurementKind,
    Severity,
    SourceType,
    SystemType,
    Unit,
)

NOW = datetime(2026, 7, 21, 2, 0, 0, tzinfo=UTC)
RECEIVED = datetime(2026, 7, 21, 2, 0, 3, tzinfo=UTC)
ALERT_TIME = datetime(2026, 7, 21, 2, 10, 0, tzinfo=UTC)


def mutate_frozen_instance(instance: object, field_name: str, value: object) -> None:
    setattr(instance, field_name, value)


def test_create_valid_residence() -> None:
    residence = Residence(
        id="residence_home",
        name="Home",
        timezone="America/Toronto",
        created_at=NOW,
    )

    assert residence.to_dict() == {
        "id": "residence_home",
        "name": "Home",
        "timezone": "America/Toronto",
        "created_at": "2026-07-21T02:00:00Z",
    }


def test_create_valid_hvac_system() -> None:
    hvac_system = HVACSystem(
        id="hvac_main",
        residence_id="residence_home",
        name="Main HVAC system",
        system_type=SystemType.FORCED_AIR,
        created_at=NOW,
    )

    assert hvac_system.to_dict()["system_type"] == "forced_air"


def test_create_valid_equipment() -> None:
    equipment = Equipment(
        id="equipment_main_hvac",
        hvac_system_id="hvac_main",
        name="Main heat pump",
        equipment_type=EquipmentType.HEAT_PUMP,
        created_at=NOW,
        manufacturer="Example",
        model="Example Model",
    )

    assert equipment.to_dict()["equipment_type"] == "heat_pump"


def test_create_valid_protocol_source() -> None:
    source = ProtocolSource(
        id="source_simulator",
        name="Simulator",
        source_type=SourceType.SIMULATOR,
        protocol=ProtocolName.FILE,
        created_at=NOW,
    )

    assert source.to_dict() == {
        "id": "source_simulator",
        "name": "Simulator",
        "source_type": "simulator",
        "created_at": "2026-07-21T02:00:00Z",
        "protocol": "file",
    }


def test_create_valid_sensor() -> None:
    sensor = Sensor(
        id="sensor_supply_air_temp",
        equipment_id="equipment_main_hvac",
        name="Supply air temperature",
        measurement_kind=MeasurementKind.TEMPERATURE,
        unit="degC",
        source_id="source_simulator",
        created_at=NOW,
    )

    assert sensor.to_dict()["measurement_kind"] == "temperature"
    assert sensor.to_dict()["sensor_kind"] == "temperature"


def test_create_sensor_with_explicit_relative_humidity_kind() -> None:
    sensor = Sensor(
        id="sensor_return_air_humidity",
        equipment_id="equipment_main_hvac",
        name="Return air humidity",
        measurement_kind=MeasurementKind.HUMIDITY,
        sensor_kind=SensorMeasurementKind.RELATIVE_HUMIDITY,
        unit="%",
        source_id="source_simulator",
        created_at=NOW,
    )

    assert sensor.to_dict()["sensor_kind"] == "relative_humidity"


def test_create_valid_unit() -> None:
    unit = Unit(code="degC", quantity="temperature", symbol="degC")

    assert unit.to_dict() == {
        "code": "degC",
        "quantity": "temperature",
        "symbol": "degC",
    }


def test_measurement_matches_documented_json_example() -> None:
    measurement = Measurement(
        id="m_001",
        sensor_id="sensor_supply_air_temp",
        observed_at=NOW,
        received_at=RECEIVED,
        value=18.7,
        unit="degC",
        quality=DataQuality.GOOD,
        source_id="source_simulator",
    )

    assert measurement.to_dict() == {
        "id": "m_001",
        "sensor_id": "sensor_supply_air_temp",
        "observed_at": "2026-07-21T02:00:00Z",
        "received_at": "2026-07-21T02:00:03Z",
        "value": 18.7,
        "unit": "degC",
        "quality": "good",
        "source_id": "source_simulator",
    }


def test_equipment_state_matches_documented_json_example() -> None:
    state = EquipmentState(
        id="state_001",
        equipment_id="equipment_main_hvac",
        observed_at=NOW,
        state=EquipmentOperationalState.COOLING,
        source_id="source_simulator",
        quality=DataQuality.GOOD,
    )

    assert state.to_dict() == {
        "id": "state_001",
        "equipment_id": "equipment_main_hvac",
        "observed_at": "2026-07-21T02:00:00Z",
        "state": "cooling",
        "source_id": "source_simulator",
        "quality": "good",
    }


def test_create_valid_event() -> None:
    event = Event(
        id="event_001",
        equipment_id="equipment_main_hvac",
        occurred_at=NOW,
        event_type="mode_changed",
        severity=Severity.INFO,
        message="Operating mode changed.",
        source_id="source_simulator",
    )

    assert event.to_dict() == {
        "id": "event_001",
        "occurred_at": "2026-07-21T02:00:00Z",
        "event_type": "mode_changed",
        "severity": "info",
        "message": "Operating mode changed.",
        "source_id": "source_simulator",
        "equipment_id": "equipment_main_hvac",
    }


def test_alert_matches_documented_json_example() -> None:
    alert = Alert(
        id="alert_001",
        triggered_at=ALERT_TIME,
        cleared_at=None,
        severity=Severity.WARNING,
        summary="A local threshold rule was triggered.",
        source_id="rule_local_threshold",
        related_measurement_ids=("m_001",),
    )

    assert alert.to_dict() == {
        "id": "alert_001",
        "triggered_at": "2026-07-21T02:10:00Z",
        "severity": "warning",
        "summary": "A local threshold rule was triggered.",
        "source_id": "rule_local_threshold",
        "cleared_at": None,
        "related_measurement_ids": ["m_001"],
    }


def test_reject_empty_identifier() -> None:
    with pytest.raises(GeoPilotDomainError, match="id"):
        Unit(code="", quantity="temperature", symbol="degC")


def test_reject_naive_timestamp() -> None:
    with pytest.raises(GeoPilotDomainError, match="timezone-aware"):
        Residence(
            id="residence_home",
            name="Home",
            timezone="America/Toronto",
            created_at=datetime(2026, 7, 21, 2, 0, 0),
        )


def test_reject_non_numeric_measurement_value() -> None:
    with pytest.raises(GeoPilotDomainError, match="numeric"):
        Measurement(
            id="m_001",
            sensor_id="sensor_supply_air_temp",
            observed_at=NOW,
            received_at=RECEIVED,
            value=True,
            unit="degC",
            quality=DataQuality.GOOD,
            source_id="source_simulator",
        )


def test_reject_missing_measurement_unit() -> None:
    with pytest.raises(GeoPilotDomainError, match="unit"):
        Measurement(
            id="m_001",
            sensor_id="sensor_supply_air_temp",
            observed_at=NOW,
            received_at=RECEIVED,
            value=18.7,
            unit=" ",
            quality=DataQuality.GOOD,
            source_id="source_simulator",
        )


def test_invalid_alert_severity_is_rejected_by_enum() -> None:
    with pytest.raises(ValueError):
        Severity("emergency")


def test_invalid_equipment_state_is_rejected_by_enum() -> None:
    with pytest.raises(ValueError):
        EquipmentOperationalState("compressor_stage_4")


def test_measurement_is_immutable() -> None:
    measurement = Measurement(
        id="m_001",
        sensor_id="sensor_supply_air_temp",
        observed_at=NOW,
        received_at=RECEIVED,
        value=18.7,
        unit="degC",
        quality=DataQuality.GOOD,
        source_id="source_simulator",
    )

    with pytest.raises(FrozenInstanceError):
        mutate_frozen_instance(measurement, "value", 20.0)


def test_event_is_immutable() -> None:
    event = Event(
        id="event_001",
        occurred_at=NOW,
        event_type="mode_changed",
        severity=Severity.INFO,
        message="Operating mode changed.",
        source_id="source_simulator",
    )

    with pytest.raises(FrozenInstanceError):
        mutate_frozen_instance(event, "message", "Changed")
