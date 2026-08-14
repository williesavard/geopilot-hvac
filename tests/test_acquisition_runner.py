from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from geopilot.acquisition import (
    AcquisitionErrorCode,
    AcquisitionFailure,
    AcquisitionPipeline,
    AcquisitionSuccess,
)
from geopilot.acquisition_runner import (
    AcquisitionPlan,
    AcquisitionRequest,
    AcquisitionRunner,
    AcquisitionRunnerError,
    AcquisitionRunReport,
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
RECEIVED_AT = datetime(2026, 7, 21, 12, 6, 0, tzinfo=UTC)
RUN_STARTED = datetime(2026, 7, 21, 12, 7, 0, tzinfo=UTC)
RUN_COMPLETED = datetime(2026, 7, 21, 12, 7, 1, tzinfo=UTC)


def test_runner_handles_empty_plan() -> None:
    registry = registry_with_runner_sensors()
    historian = InMemoryMeasurementHistorian()
    runner = runner_for(registry, historian, clock=clock_sequence(RUN_STARTED, RUN_COMPLETED))

    report = runner.run(AcquisitionPlan(plan_id="empty", requests=()))

    assert report.started_at == RUN_STARTED
    assert report.completed_at == RUN_COMPLETED
    assert report.results == ()
    assert report.success_count == 0
    assert report.failure_count == 0
    assert report.total_count == 0
    assert historian.all() == ()


def test_runner_executes_multiple_successes_in_request_order() -> None:
    registry = registry_with_runner_sensors()
    historian = InMemoryMeasurementHistorian()
    runner = runner_for(registry, historian, clock=clock_sequence(RUN_STARTED, RUN_COMPLETED))
    plan = AcquisitionPlan(
        plan_id="runner_successes",
        requests=(
            request_for("temperature", "sim.temperature", "sensor_temperature", "degC", 215, 0.1),
            request_for("humidity", "sim.humidity", "sensor_humidity", "%", 430, 0.1),
        ),
    )

    report = runner.run(plan)

    assert report.success_count == 2
    assert report.failure_count == 0
    assert report.total_count == 2
    assert [result.context.register_id for result in report.results] == [
        "sim.temperature",
        "sim.humidity",
    ]
    assert all(isinstance(result, AcquisitionSuccess) for result in report.results)
    assert [item.sensor_id for item in historian.all()] == [
        "sensor_temperature",
        "sensor_humidity",
    ]


def test_runner_reports_success_and_failure_without_failed_measurement() -> None:
    registry = registry_with_runner_sensors()
    historian = InMemoryMeasurementHistorian()
    runner = runner_for(registry, historian, clock=clock_sequence(RUN_STARTED, RUN_COMPLETED))
    plan = AcquisitionPlan(
        plan_id="runner_mixed",
        requests=(
            request_for("temperature", "sim.temperature", "sensor_temperature", "degC", 215, 0.1),
            missing_payload_request("missing", "sim.missing", "sensor_humidity", "%"),
        ),
    )

    report = runner.run(plan)

    assert report.success_count == 1
    assert report.failure_count == 1
    assert report.total_count == 2
    assert isinstance(report.results[0], AcquisitionSuccess)
    assert isinstance(report.results[1], AcquisitionFailure)
    assert report.results[1].code is AcquisitionErrorCode.READ_FAILED
    assert historian.count() == 1
    assert historian.all()[0].sensor_id == "sensor_temperature"


def test_runner_preserves_stable_result_order_across_multi_result_requests() -> None:
    registry = registry_with_runner_sensors()
    historian = InMemoryMeasurementHistorian()
    runner = runner_for(registry, historian, clock=clock_sequence(RUN_STARTED, RUN_COMPLETED))
    plan = AcquisitionPlan(
        plan_id="runner_order",
        requests=(
            AcquisitionRequest(
                request_id="multi",
                profile_id="simulated.combo.v1",
                executor=lambda pipeline: (
                    request_for(
                        "temperature",
                        "sim.temperature",
                        "sensor_temperature",
                        "degC",
                        215,
                        0.1,
                    ).executor(pipeline)
                    + missing_payload_request(
                        "missing",
                        "sim.missing",
                        "sensor_humidity",
                        "%",
                    ).executor(pipeline)
                ),
            ),
            request_for("humidity", "sim.humidity", "sensor_humidity", "%", 430, 0.1),
        ),
    )

    report = runner.run(plan)

    assert [result.context.register_id for result in report.results] == [
        "sim.temperature",
        "sim.missing",
        "sim.humidity",
    ]


def test_runner_rejects_duplicate_request_ids() -> None:
    request = request_for("temperature", "sim.temperature", "sensor_temperature", "degC", 215, 0.1)

    with pytest.raises(AcquisitionRunnerError, match="Duplicate"):
        AcquisitionPlan(plan_id="duplicate", requests=(request, request))


def test_report_rejects_naive_timestamps() -> None:
    with pytest.raises(AcquisitionRunnerError, match="started_at"):
        AcquisitionRunReport(
            plan_id="bad",
            started_at=datetime(2026, 7, 21, 12, 7, 0),
            completed_at=RUN_COMPLETED,
            results=(),
        )


def test_report_is_json_compatible() -> None:
    registry = registry_with_runner_sensors()
    historian = InMemoryMeasurementHistorian()
    runner = runner_for(registry, historian, clock=clock_sequence(RUN_STARTED, RUN_COMPLETED))
    report = runner.run(
        AcquisitionPlan(
            plan_id="runner_json",
            requests=(
                request_for(
                    "temperature",
                    "sim.temperature",
                    "sensor_temperature",
                    "degC",
                    215,
                    0.1,
                ),
            ),
        )
    )

    payload = report.to_dict()

    assert payload["started_at"] == "2026-07-21T12:07:00Z"
    assert payload["completed_at"] == "2026-07-21T12:07:01Z"
    assert payload["success_count"] == 1
    assert payload["failure_count"] == 0
    assert payload["total_count"] == 1
    assert payload["results"][0]["measurement"]["sensor_id"] == "sensor_temperature"
    json.dumps(payload, sort_keys=True)


def request_for(
    request_id: str,
    register_id: str,
    sensor_id: str,
    unit: str,
    word: int,
    scale: float,
) -> AcquisitionRequest:
    definition = register_definition(register_id, sensor_id, unit, scale=scale)
    service = SimulatedModbusAcquisitionService(
        SimulatedModbusRegisterClient((payload(register_id, word),))
    )
    return AcquisitionRequest(
        request_id=request_id,
        profile_id="simulated.profile.v1",
        executor=lambda pipeline: service.acquire(
            (definition,),
            pipeline,
            profile_id="simulated.profile.v1",
        ),
    )


def missing_payload_request(
    request_id: str,
    register_id: str,
    sensor_id: str,
    unit: str,
) -> AcquisitionRequest:
    definition = register_definition(register_id, sensor_id, unit, scale=1.0)
    service = SimulatedModbusAcquisitionService(SimulatedModbusRegisterClient(()))
    return AcquisitionRequest(
        request_id=request_id,
        profile_id="simulated.profile.v1",
        executor=lambda pipeline: service.acquire(
            (definition,),
            pipeline,
            profile_id="simulated.profile.v1",
        ),
    )


def register_definition(
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


def runner_for(
    registry: InMemoryAssetRegistry,
    historian: InMemoryMeasurementHistorian,
    *,
    clock: Callable[[], datetime],
) -> AcquisitionRunner:
    pipeline = AcquisitionPipeline(
        IngestionService(
            MeasurementNormalizer(clock=lambda: RECEIVED_AT),
            historian,
            registry,
        ),
        clock=lambda: RECEIVED_AT,
    )
    return AcquisitionRunner(pipeline, clock=clock)


def clock_sequence(*values: datetime) -> Callable[[], datetime]:
    timestamps = list(values)

    def tick() -> datetime:
        if not timestamps:
            raise AssertionError("clock exhausted")
        return timestamps.pop(0)

    return tick


def registry_with_runner_sensors() -> InMemoryAssetRegistry:
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
    registry.add_sensor(sensor("sensor_temperature", MeasurementKind.TEMPERATURE, "degC"))
    registry.add_sensor(sensor("sensor_humidity", MeasurementKind.HUMIDITY, "%"))
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
