from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from geopilot.device_profiles import (
    SIMULATED_POWER_METER_V1,
    SIMULATED_TEMP_HUMIDITY_SENSOR_V1,
    DeviceProfile,
    DeviceProfileError,
    DeviceProfileRegistry,
    DeviceProfileStatus,
    DeviceRegisterProfile,
    built_in_device_profiles,
)
from geopilot.domain import (
    Equipment,
    EquipmentType,
    HVACSystem,
    MeasurementKind,
    ProtocolName,
    Residence,
    Sensor,
    SystemType,
)
from geopilot.export import export_measurements
from geopilot.historian import InMemoryMeasurementHistorian
from geopilot.ingestion import IngestionService, MeasurementNormalizer
from geopilot.modbus_simulator import (
    SimulatedModbusAcquisitionService,
    SimulatedModbusRegisterClient,
)
from geopilot.register_decoder import RegisterDataType, SimulatedRegisterPayload
from geopilot.registry import InMemoryAssetRegistry

CREATED_AT = datetime(2026, 7, 21, 12, 0, 0, tzinfo=UTC)
OBSERVED_AT = datetime(2026, 7, 21, 12, 5, 0, tzinfo=UTC)
RECEIVED_AT = datetime(2026, 7, 21, 12, 6, 0, tzinfo=UTC)


def test_built_in_profiles_are_simulated_only() -> None:
    registry = built_in_device_profiles()

    profiles = registry.all()

    assert [profile.device_id for profile in profiles] == [
        SIMULATED_POWER_METER_V1,
        SIMULATED_TEMP_HUMIDITY_SENSOR_V1,
    ]
    assert {profile.status for profile in profiles} == {DeviceProfileStatus.SIMULATED}
    assert all(register.address is None for profile in profiles for register in profile.registers)
    assert all(
        register.source_reference == "GeoPilot simulated profile"
        for profile in profiles
        for register in profile.registers
    )


def test_registry_rejects_duplicate_device_profiles() -> None:
    profile = built_in_device_profiles().get(SIMULATED_POWER_METER_V1)

    with pytest.raises(DeviceProfileError, match="Duplicate device profile"):
        DeviceProfileRegistry((profile, profile))


def test_profile_rejects_duplicate_register_names_and_ids() -> None:
    register = DeviceRegisterProfile(
        name="active_power",
        register_id="sim.power",
        address=None,
        quantity="power",
        data_type=RegisterDataType.UINT16,
        unit="W",
        measurement_kind=MeasurementKind.POWER,
        source_reference="GeoPilot simulated profile",
    )

    with pytest.raises(DeviceProfileError, match="Duplicate register id"):
        DeviceProfile(
            device_id="sim.duplicate",
            manufacturer="GeoPilot",
            model="Duplicate",
            protocol=ProtocolName.MODBUS,
            status=DeviceProfileStatus.SIMULATED,
            registers=(register, register),
        )


def test_non_simulated_profile_requires_confirmed_addresses() -> None:
    with pytest.raises(DeviceProfileError, match="confirmed register addresses"):
        DeviceProfile(
            device_id="real.sdm120.placeholder",
            manufacturer="Eastron",
            model="SDM120 TBD",
            protocol=ProtocolName.MODBUS,
            status=DeviceProfileStatus.UNDER_EVALUATION,
            registers=(
                DeviceRegisterProfile(
                    name="active_power",
                    register_id="sdm120.active_power",
                    address=None,
                    quantity="power",
                    data_type=RegisterDataType.UINT16,
                    unit="W",
                    measurement_kind=MeasurementKind.POWER,
                    source_reference="TBD official protocol",
                ),
            ),
        )


def test_register_profile_builds_decoder_definition_for_target_sensor() -> None:
    profile = built_in_device_profiles().get(SIMULATED_TEMP_HUMIDITY_SENSOR_V1)
    register = profile.register_by_name("temperature")

    definition = register.to_register_definition(
        source_id="source_simulated_modbus",
        sensor_id="sensor_loop_entering_temp",
    )

    assert definition.register_id == "sim.temp_humidity.temperature"
    assert definition.sensor_id == "sensor_loop_entering_temp"
    assert definition.data_type is RegisterDataType.INT16
    assert definition.scale == 0.1
    assert definition.source_reference == "GeoPilot simulated profile"


def test_simulated_profiles_feed_modbus_simulator_chain() -> None:
    device_profiles = built_in_device_profiles()
    temp_humidity = device_profiles.get(SIMULATED_TEMP_HUMIDITY_SENSOR_V1)
    power_meter = device_profiles.get(SIMULATED_POWER_METER_V1)
    definitions = (
        temp_humidity.register_by_name("temperature").to_register_definition(
            source_id="source_simulated_modbus",
            sensor_id="sensor_loop_entering_temp",
        ),
        temp_humidity.register_by_name("relative_humidity").to_register_definition(
            source_id="source_simulated_modbus",
            sensor_id="sensor_relative_humidity",
        ),
        power_meter.register_by_name("active_power").to_register_definition(
            source_id="source_simulated_modbus",
            sensor_id="sensor_electrical_power",
        ),
    )
    client = SimulatedModbusRegisterClient(
        (
            payload("sim.temp_humidity.temperature", 215),
            payload("sim.temp_humidity.relative_humidity", 430),
            payload("sim.power_meter.active_power", 24),
        )
    )
    registry = registry_with_profile_sensors()
    historian = InMemoryMeasurementHistorian()
    ingestion = IngestionService(
        MeasurementNormalizer(clock=lambda: RECEIVED_AT),
        historian,
        registry,
    )

    raw_measurements = SimulatedModbusAcquisitionService(client).read_raw_measurements(
        definitions
    )
    for raw in raw_measurements:
        ingestion.ingest(raw)

    payload_json = export_measurements(
        historian.query_system("system_main", registry),
        export_id="profile_driven_simulated_modbus",
    )

    assert payload_json["count"] == 3
    assert {
        item["sensor_id"]: item["value"]
        for item in payload_json["measurements"]
    } == {
        "sensor_electrical_power": 2400.0,
        "sensor_loop_entering_temp": 21.5,
        "sensor_relative_humidity": 43.0,
    }
    json.dumps(payload_json, sort_keys=True)


def payload(register_id: str, word: int) -> SimulatedRegisterPayload:
    return SimulatedRegisterPayload(
        register_id=register_id,
        words=(word,),
        observed_at=OBSERVED_AT,
    )


def registry_with_profile_sensors() -> InMemoryAssetRegistry:
    registry = InMemoryAssetRegistry()
    registry.add_residence(
        Residence(
            id="residence_home",
            name="Home",
            timezone="America/Toronto",
            created_at=CREATED_AT,
        )
    )
    registry.add_hvac_system(
        HVACSystem(
            id="system_main",
            residence_id="residence_home",
            name="Main system",
            system_type=SystemType.HYDRONIC,
            created_at=CREATED_AT,
        )
    )
    registry.add_equipment(
        Equipment(
            id="equipment_heat_pump",
            hvac_system_id="system_main",
            name="Heat pump",
            equipment_type=EquipmentType.HEAT_PUMP,
            created_at=CREATED_AT,
        )
    )
    registry.add_sensor(
        sensor("sensor_loop_entering_temp", MeasurementKind.TEMPERATURE, "degC")
    )
    registry.add_sensor(sensor("sensor_relative_humidity", MeasurementKind.HUMIDITY, "%"))
    registry.add_sensor(sensor("sensor_electrical_power", MeasurementKind.POWER, "W"))
    return registry


def sensor(sensor_id: str, kind: MeasurementKind, unit: str) -> Sensor:
    return Sensor(
        id=sensor_id,
        equipment_id="equipment_heat_pump",
        name=sensor_id.replace("_", " ").title(),
        measurement_kind=kind,
        unit=unit,
        source_id="source_simulated_modbus",
        created_at=CREATED_AT,
    )
