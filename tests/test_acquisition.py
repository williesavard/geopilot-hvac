from __future__ import annotations

from datetime import UTC, datetime

import pytest
from geopilot.acquisition import (
    AcquisitionErrorCode,
    AcquisitionFailure,
    AcquisitionPipeline,
    AcquisitionResultError,
    AcquisitionSuccess,
    failures,
    successful_measurements,
)
from geopilot.domain import (
    Equipment,
    EquipmentType,
    HVACSystem,
    MeasurementKind,
    Residence,
    Sensor,
    SystemType,
)
from geopilot.historian import InMemoryMeasurementHistorian
from geopilot.ingestion import IngestionService, MeasurementNormalizer
from geopilot.modbus_simulator import (
    SimulatedModbusAcquisitionService,
    SimulatedModbusRegisterClient,
)
from geopilot.register_decoder import (
    RegisterDataType,
    RegisterDefinition,
    SimulatedRegisterPayload,
)
from geopilot.registry import InMemoryAssetRegistry

CREATED_AT = datetime(2026, 7, 21, 12, 0, 0, tzinfo=UTC)
OBSERVED_AT = datetime(2026, 7, 21, 12, 5, 0, tzinfo=UTC)
ACQUIRED_AT = datetime(2026, 7, 21, 12, 6, 0, tzinfo=UTC)


def test_acquisition_success_writes_measurement_to_historian() -> None:
    registry = registry_with_sensor("sensor_temperature", MeasurementKind.TEMPERATURE, "degC")
    historian = InMemoryMeasurementHistorian()
    pipeline = pipeline_for(registry, historian)
    service = SimulatedModbusAcquisitionService(
        SimulatedModbusRegisterClient((payload("sim.temperature", 215),))
    )

    results = service.acquire(
        (definition("sim.temperature", "sensor_temperature", "degC", scale=0.1),),
        pipeline,
        profile_id="simulated.temp_humidity_sensor.v1",
    )

    assert len(results) == 1
    assert isinstance(results[0], AcquisitionSuccess)
    assert results[0].measurement.value == 21.5
    assert results[0].context.profile_id == "simulated.temp_humidity_sensor.v1"
    assert results[0].context.register_id == "sim.temperature"
    assert results[0].context.sensor_id == "sensor_temperature"
    assert results[0].acquired_at == ACQUIRED_AT
    assert historian.all() == (results[0].measurement,)
    assert successful_measurements(results) == (results[0].measurement,)
    assert failures(results) == ()


def test_read_failure_returns_structured_result_without_writing_historian() -> None:
    registry = registry_with_sensor("sensor_temperature", MeasurementKind.TEMPERATURE, "degC")
    historian = InMemoryMeasurementHistorian()
    pipeline = pipeline_for(registry, historian)
    service = SimulatedModbusAcquisitionService(SimulatedModbusRegisterClient(()))

    results = service.acquire(
        (definition("sim.temperature", "sensor_temperature", "degC", scale=0.1),),
        pipeline,
        profile_id="simulated.temp_humidity_sensor.v1",
    )

    assert len(results) == 1
    assert isinstance(results[0], AcquisitionFailure)
    assert results[0].code is AcquisitionErrorCode.READ_FAILED
    assert results[0].context.register_id == "sim.temperature"
    assert results[0].context.sensor_id == "sensor_temperature"
    assert "Missing simulated payload" in results[0].message
    assert results[0].acquired_at == ACQUIRED_AT
    assert historian.all() == ()


def test_decode_failure_returns_structured_result() -> None:
    registry = registry_with_sensor("sensor_temperature", MeasurementKind.TEMPERATURE, "degC")
    historian = InMemoryMeasurementHistorian()
    pipeline = pipeline_for(registry, historian)
    service = SimulatedModbusAcquisitionService(
        SimulatedModbusRegisterClient(
            (
                SimulatedRegisterPayload(
                    register_id="sim.temperature",
                    words=(215, 216),
                    observed_at=OBSERVED_AT,
                ),
            )
        )
    )

    results = service.acquire(
        (definition("sim.temperature", "sensor_temperature", "degC", scale=0.1),),
        pipeline,
    )

    assert len(results) == 1
    assert isinstance(results[0], AcquisitionFailure)
    assert results[0].code is AcquisitionErrorCode.DECODE_FAILED
    assert "requires 2" not in results[0].message
    assert "requires 1" in results[0].message
    assert historian.all() == ()


def test_normalization_failure_returns_structured_result() -> None:
    registry = registry_with_sensor("sensor_temperature", MeasurementKind.TEMPERATURE, "degC")
    historian = InMemoryMeasurementHistorian()
    pipeline = pipeline_for(registry, historian)
    service = SimulatedModbusAcquisitionService(
        SimulatedModbusRegisterClient((payload("sim.temperature", 215),))
    )

    results = service.acquire(
        (definition("sim.temperature", "sensor_temperature", "V", scale=0.1),),
        pipeline,
    )

    assert len(results) == 1
    assert isinstance(results[0], AcquisitionFailure)
    assert results[0].code is AcquisitionErrorCode.NORMALIZATION_FAILED
    assert "incompatible with temperature sensors" in results[0].message
    assert historian.all() == ()


def test_unknown_sensor_returns_structured_result() -> None:
    registry = registry_with_sensor("sensor_temperature", MeasurementKind.TEMPERATURE, "degC")
    historian = InMemoryMeasurementHistorian()
    pipeline = pipeline_for(registry, historian)
    service = SimulatedModbusAcquisitionService(
        SimulatedModbusRegisterClient((payload("sim.temperature", 215),))
    )

    results = service.acquire(
        (definition("sim.temperature", "sensor_missing", "degC", scale=0.1),),
        pipeline,
    )

    assert len(results) == 1
    assert isinstance(results[0], AcquisitionFailure)
    assert results[0].code is AcquisitionErrorCode.SENSOR_NOT_FOUND
    assert results[0].context.sensor_id == "sensor_missing"
    assert historian.all() == ()


def test_acquisition_failure_requires_timezone_aware_timestamp() -> None:
    registry = registry_with_sensor("sensor_temperature", MeasurementKind.TEMPERATURE, "degC")
    historian = InMemoryMeasurementHistorian()
    pipeline = AcquisitionPipeline(
        IngestionService(MeasurementNormalizer(), historian, registry),
        clock=lambda: datetime(2026, 7, 21, 12, 6, 0),
    )
    service = SimulatedModbusAcquisitionService(SimulatedModbusRegisterClient(()))

    with pytest.raises(AcquisitionResultError, match="timezone-aware"):
        service.acquire(
            (definition("sim.temperature", "sensor_temperature", "degC", scale=0.1),),
            pipeline,
        )


def definition(
    register_id: str,
    sensor_id: str,
    unit: str,
    *,
    scale: float,
) -> RegisterDefinition:
    return RegisterDefinition(
        register_id=register_id,
        source_id="source_simulated_modbus",
        sensor_id=sensor_id,
        unit=unit,
        data_type=RegisterDataType.UINT16,
        scale=scale,
        source_reference="simulated fixture",
    )


def payload(register_id: str, word: int) -> SimulatedRegisterPayload:
    return SimulatedRegisterPayload(
        register_id=register_id,
        words=(word,),
        observed_at=OBSERVED_AT,
    )


def pipeline_for(
    registry: InMemoryAssetRegistry,
    historian: InMemoryMeasurementHistorian,
) -> AcquisitionPipeline:
    return AcquisitionPipeline(
        IngestionService(
            MeasurementNormalizer(clock=lambda: ACQUIRED_AT),
            historian,
            registry,
        ),
        clock=lambda: ACQUIRED_AT,
    )


def registry_with_sensor(
    sensor_id: str,
    kind: MeasurementKind,
    unit: str,
) -> InMemoryAssetRegistry:
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
        Sensor(
            id=sensor_id,
            equipment_id="equipment_heat_pump",
            name=sensor_id.replace("_", " ").title(),
            measurement_kind=kind,
            unit=unit,
            source_id="source_simulated_modbus",
            created_at=CREATED_AT,
        )
    )
    return registry
