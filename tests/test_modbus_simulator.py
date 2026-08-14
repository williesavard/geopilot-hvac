from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from geopilot.domain import (
    Equipment,
    EquipmentType,
    HVACSystem,
    MeasurementKind,
    Residence,
    Sensor,
    SystemType,
)
from geopilot.export import export_measurements, export_snapshot
from geopilot.historian import InMemoryMeasurementHistorian
from geopilot.ingestion import IngestionService, MeasurementNormalizer
from geopilot.modbus_simulator import (
    ModbusSimulatorError,
    SimulatedModbusAcquisitionService,
    SimulatedModbusRegisterClient,
)
from geopilot.register_decoder import (
    RegisterDataType,
    RegisterDefinition,
    SimulatedRegisterPayload,
)
from geopilot.registry import InMemoryAssetRegistry
from geopilot.snapshot import CurrentStateProjector

CREATED_AT = datetime(2026, 7, 21, 12, 0, 0, tzinfo=UTC)
OBSERVED_AT = datetime(2026, 7, 21, 12, 5, 0, tzinfo=UTC)
RECEIVED_AT = datetime(2026, 7, 21, 12, 6, 0, tzinfo=UTC)
GENERATED_AT = datetime(2026, 7, 21, 12, 7, 0, tzinfo=UTC)


def register_definition(
    register_id: str,
    sensor_id: str,
    unit: str,
    *,
    scale: float,
    data_type: RegisterDataType = RegisterDataType.UINT16,
) -> RegisterDefinition:
    return RegisterDefinition(
        register_id=register_id,
        source_id="source_simulated_modbus",
        sensor_id=sensor_id,
        unit=unit,
        data_type=data_type,
        scale=scale,
        source_reference="simulated Modbus RTU fixture",
    )


def payload(register_id: str, word: int) -> SimulatedRegisterPayload:
    return SimulatedRegisterPayload(
        register_id=register_id,
        words=(word,),
        observed_at=OBSERVED_AT,
    )


def registry_with_modbus_sensors() -> InMemoryAssetRegistry:
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


def test_simulated_modbus_client_reads_payloads_by_register_definition() -> None:
    definition = register_definition(
        "sim.temperature",
        "sensor_loop_entering_temp",
        "degC",
        scale=0.1,
    )
    expected = payload("sim.temperature", 215)
    client = SimulatedModbusRegisterClient((expected,))

    result = client.read_register(definition)

    assert result == expected
    assert client.read_register_ids() == ("sim.temperature",)


def test_simulated_modbus_client_rejects_duplicate_payloads() -> None:
    item = payload("sim.temperature", 215)

    with pytest.raises(ModbusSimulatorError, match="Duplicate"):
        SimulatedModbusRegisterClient((item, item))


def test_simulated_modbus_client_rejects_missing_payload() -> None:
    definition = register_definition(
        "sim.temperature",
        "sensor_loop_entering_temp",
        "degC",
        scale=0.1,
    )
    client = SimulatedModbusRegisterClient(())

    with pytest.raises(ModbusSimulatorError, match="Missing"):
        client.read_register(definition)


def test_acquisition_service_decodes_raw_measurements_in_definition_order() -> None:
    definitions = (
        register_definition("sim.temperature", "sensor_loop_entering_temp", "degC", scale=0.1),
        register_definition("sim.humidity", "sensor_relative_humidity", "%", scale=0.1),
    )
    client = SimulatedModbusRegisterClient(
        (
            payload("sim.humidity", 430),
            payload("sim.temperature", 215),
        )
    )

    raw_measurements = SimulatedModbusAcquisitionService(client).read_raw_measurements(
        definitions
    )

    assert [item.sensor_id for item in raw_measurements] == [
        "sensor_loop_entering_temp",
        "sensor_relative_humidity",
    ]
    assert [item.value for item in raw_measurements] == [21.5, 43.0]
    assert client.read_register_ids() == ("sim.temperature", "sim.humidity")


def test_simulated_modbus_chain_reaches_historian_export_and_snapshot() -> None:
    registry = registry_with_modbus_sensors()
    historian = InMemoryMeasurementHistorian()
    ingestion = IngestionService(
        MeasurementNormalizer(clock=lambda: RECEIVED_AT),
        historian,
        registry,
    )
    definitions = (
        register_definition("sim.temperature", "sensor_loop_entering_temp", "degC", scale=0.1),
        register_definition("sim.humidity", "sensor_relative_humidity", "%", scale=0.1),
        register_definition("sim.power", "sensor_electrical_power", "W", scale=100.0),
    )
    client = SimulatedModbusRegisterClient(
        (
            payload("sim.temperature", 215),
            payload("sim.humidity", 430),
            payload("sim.power", 24),
        )
    )

    raw_measurements = SimulatedModbusAcquisitionService(client).read_raw_measurements(
        definitions
    )
    for raw in raw_measurements:
        ingestion.ingest(raw)

    snapshot = CurrentStateProjector(
        registry,
        historian,
        clock=lambda: GENERATED_AT,
    ).project(residence_id="residence_home", system_id="system_main")
    measurements_payload = export_measurements(
        historian.query_system("system_main", registry),
        export_id="simulated_modbus_chain",
    )
    snapshot_payload = export_snapshot(snapshot, export_id="simulated_modbus_snapshot")

    assert historian.count() == 3
    assert measurements_payload["count"] == 3
    assert [item["sensor_id"] for item in measurements_payload["measurements"]] == [
        "sensor_electrical_power",
        "sensor_loop_entering_temp",
        "sensor_relative_humidity",
    ]
    values_by_sensor = {
        item["sensor_id"]: item["value"]
        for item in measurements_payload["measurements"]
    }
    assert values_by_sensor == {
        "sensor_electrical_power": 2400.0,
        "sensor_loop_entering_temp": 21.5,
        "sensor_relative_humidity": 43.0,
    }
    snapshot_sensors = snapshot_payload["snapshot"]["equipment"][0]["sensors"]
    assert {item["sensor_id"] for item in snapshot_sensors} == {
        "sensor_electrical_power",
        "sensor_loop_entering_temp",
        "sensor_relative_humidity",
    }
    json.dumps(measurements_payload, sort_keys=True)
    json.dumps(snapshot_payload, sort_keys=True)
