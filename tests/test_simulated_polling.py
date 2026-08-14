from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime

import pytest
from geopilot.acquisition import AcquisitionErrorCode, AcquisitionFailure, AcquisitionPipeline
from geopilot.acquisition_runner import AcquisitionPlan, AcquisitionRequest, AcquisitionRunner
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
    SimulatedModbusAcquisitionService,
    SimulatedModbusRegisterClient,
)
from geopilot.register_decoder import (
    RegisterDataType,
    RegisterDefinition,
    SimulatedRegisterPayload,
)
from geopilot.registry import InMemoryAssetRegistry
from geopilot.simulated_polling import (
    SimulatedPollingCycle,
    SimulatedPollingError,
    SimulatedPollingPlan,
    SimulatedPollingReport,
    SimulatedPollingRunner,
)
from geopilot.snapshot import CurrentStateProjector

CREATED_AT = datetime(2026, 7, 21, 12, 0, 0, tzinfo=UTC)
RECEIVED_AT = datetime(2026, 7, 21, 12, 20, 0, tzinfo=UTC)
POLLING_STARTED = datetime(2026, 7, 21, 12, 0, 0, tzinfo=UTC)
CYCLE_1_STARTED = datetime(2026, 7, 21, 12, 0, 1, tzinfo=UTC)
CYCLE_1_COMPLETED = datetime(2026, 7, 21, 12, 0, 2, tzinfo=UTC)
CYCLE_2_STARTED = datetime(2026, 7, 21, 12, 5, 1, tzinfo=UTC)
CYCLE_2_COMPLETED = datetime(2026, 7, 21, 12, 5, 2, tzinfo=UTC)
POLLING_COMPLETED = datetime(2026, 7, 21, 12, 10, 0, tzinfo=UTC)
SNAPSHOT_AT = datetime(2026, 7, 21, 12, 10, 30, tzinfo=UTC)


def test_polling_runner_handles_empty_plan() -> None:
    registry = registry_with_polling_sensors()
    historian = InMemoryMeasurementHistorian()
    runner = polling_runner_for(
        registry,
        historian,
        polling_clock=clock_sequence(POLLING_STARTED, POLLING_COMPLETED),
        acquisition_clock=clock_sequence(),
    )

    report = runner.run(SimulatedPollingPlan(plan_id="empty", cycles=()))

    assert report.started_at == POLLING_STARTED
    assert report.completed_at == POLLING_COMPLETED
    assert report.cycle_reports == ()
    assert report.cycle_count == 0
    assert report.success_count == 0
    assert report.failure_count == 0
    assert report.total_count == 0
    assert historian.all() == ()


def test_polling_runner_executes_cycles_in_order_and_accumulates_history() -> None:
    registry = registry_with_polling_sensors()
    historian = InMemoryMeasurementHistorian()
    runner = polling_runner_for(
        registry,
        historian,
        polling_clock=clock_sequence(POLLING_STARTED, POLLING_COMPLETED),
        acquisition_clock=clock_sequence(
            CYCLE_1_STARTED,
            CYCLE_1_COMPLETED,
            CYCLE_2_STARTED,
            CYCLE_2_COMPLETED,
        ),
    )
    plan = SimulatedPollingPlan(
        plan_id="polling_successes",
        cycles=(
            SimulatedPollingCycle(
                cycle_id="cycle_1",
                acquisition_plan=AcquisitionPlan(
                    plan_id="cycle_1_plan",
                    requests=(
                        request_for(
                            "temperature_cycle_1",
                            "sim.temperature",
                            "sensor_temperature",
                            "degC",
                            210,
                            0.1,
                            observed_at=datetime(2026, 7, 21, 12, 0, 0, tzinfo=UTC),
                        ),
                    ),
                ),
            ),
            SimulatedPollingCycle(
                cycle_id="cycle_2",
                acquisition_plan=AcquisitionPlan(
                    plan_id="cycle_2_plan",
                    requests=(
                        request_for(
                            "temperature_cycle_2",
                            "sim.temperature",
                            "sensor_temperature",
                            "degC",
                            220,
                            0.1,
                            observed_at=datetime(2026, 7, 21, 12, 5, 0, tzinfo=UTC),
                        ),
                        request_for(
                            "humidity_cycle_2",
                            "sim.humidity",
                            "sensor_humidity",
                            "%",
                            430,
                            0.1,
                            observed_at=datetime(2026, 7, 21, 12, 5, 0, tzinfo=UTC),
                        ),
                    ),
                ),
            ),
        ),
    )

    report = runner.run(plan)

    assert [item.cycle_id for item in report.cycle_reports] == ["cycle_1", "cycle_2"]
    assert [item.run_report.plan_id for item in report.cycle_reports] == [
        "cycle_1_plan",
        "cycle_2_plan",
    ]
    assert report.cycle_count == 2
    assert report.success_count == 3
    assert report.failure_count == 0
    assert report.total_count == 3
    assert [item.sensor_id for item in historian.all()] == [
        "sensor_temperature",
        "sensor_temperature",
        "sensor_humidity",
    ]


def test_polling_runner_reports_failure_without_failed_measurement() -> None:
    registry = registry_with_polling_sensors()
    historian = InMemoryMeasurementHistorian()
    runner = polling_runner_for(
        registry,
        historian,
        polling_clock=clock_sequence(POLLING_STARTED, POLLING_COMPLETED),
        acquisition_clock=clock_sequence(CYCLE_1_STARTED, CYCLE_1_COMPLETED),
    )
    plan = SimulatedPollingPlan(
        plan_id="polling_mixed",
        cycles=(
            SimulatedPollingCycle(
                cycle_id="cycle_1",
                acquisition_plan=AcquisitionPlan(
                    plan_id="cycle_1_plan",
                    requests=(
                        request_for(
                            "temperature",
                            "sim.temperature",
                            "sensor_temperature",
                            "degC",
                            210,
                            0.1,
                            observed_at=datetime(2026, 7, 21, 12, 0, 0, tzinfo=UTC),
                        ),
                        missing_payload_request(
                            "missing_humidity",
                            "sim.missing",
                            "sensor_humidity",
                            "%",
                        ),
                    ),
                ),
            ),
        ),
    )

    report = runner.run(plan)

    assert report.success_count == 1
    assert report.failure_count == 1
    assert report.total_count == 2
    failure = report.cycle_reports[0].run_report.results[1]
    assert isinstance(failure, AcquisitionFailure)
    assert failure.code is AcquisitionErrorCode.READ_FAILED
    assert historian.count() == 1
    assert historian.all()[0].sensor_id == "sensor_temperature"


def test_polling_runner_rejects_duplicate_cycle_ids() -> None:
    cycle = SimulatedPollingCycle(
        cycle_id="cycle_1",
        acquisition_plan=AcquisitionPlan(plan_id="plan", requests=()),
    )

    with pytest.raises(SimulatedPollingError, match="Duplicate"):
        SimulatedPollingPlan(plan_id="duplicate", cycles=(cycle, cycle))


def test_polling_report_rejects_naive_timestamps() -> None:
    with pytest.raises(SimulatedPollingError, match="started_at"):
        SimulatedPollingReport(
            plan_id="bad",
            started_at=datetime(2026, 7, 21, 12, 0, 0),
            completed_at=POLLING_COMPLETED,
            cycle_reports=(),
        )


def test_polling_report_is_json_compatible() -> None:
    registry = registry_with_polling_sensors()
    historian = InMemoryMeasurementHistorian()
    runner = polling_runner_for(
        registry,
        historian,
        polling_clock=clock_sequence(POLLING_STARTED, POLLING_COMPLETED),
        acquisition_clock=clock_sequence(CYCLE_1_STARTED, CYCLE_1_COMPLETED),
    )
    report = runner.run(
        SimulatedPollingPlan(
            plan_id="polling_json",
            cycles=(
                SimulatedPollingCycle(
                    cycle_id="cycle_1",
                    acquisition_plan=AcquisitionPlan(
                        plan_id="cycle_1_plan",
                        requests=(
                            request_for(
                                "temperature",
                                "sim.temperature",
                                "sensor_temperature",
                                "degC",
                                210,
                                0.1,
                                observed_at=datetime(2026, 7, 21, 12, 0, 0, tzinfo=UTC),
                            ),
                        ),
                    ),
                ),
            ),
        )
    )

    payload = report.to_dict()

    assert payload["started_at"] == "2026-07-21T12:00:00Z"
    assert payload["completed_at"] == "2026-07-21T12:10:00Z"
    assert payload["cycle_count"] == 1
    assert payload["success_count"] == 1
    assert payload["failure_count"] == 0
    assert payload["total_count"] == 1
    assert payload["cycle_reports"][0]["cycle_id"] == "cycle_1"
    assert payload["cycle_reports"][0]["run_report"]["results"][0]["measurement"][
        "sensor_id"
    ] == "sensor_temperature"
    json.dumps(payload, sort_keys=True)


def test_polling_cycle_can_build_final_snapshot_and_export() -> None:
    registry = registry_with_polling_sensors()
    historian = InMemoryMeasurementHistorian()
    runner = polling_runner_for(
        registry,
        historian,
        polling_clock=clock_sequence(POLLING_STARTED, POLLING_COMPLETED),
        acquisition_clock=clock_sequence(
            CYCLE_1_STARTED,
            CYCLE_1_COMPLETED,
            CYCLE_2_STARTED,
            CYCLE_2_COMPLETED,
        ),
    )
    plan = SimulatedPollingPlan(
        plan_id="polling_snapshot",
        cycles=(
            SimulatedPollingCycle(
                cycle_id="cycle_1",
                acquisition_plan=AcquisitionPlan(
                    plan_id="cycle_1_plan",
                    requests=(
                        request_for(
                            "temperature_cycle_1",
                            "sim.temperature",
                            "sensor_temperature",
                            "degC",
                            210,
                            0.1,
                            observed_at=datetime(2026, 7, 21, 12, 0, 0, tzinfo=UTC),
                        ),
                    ),
                ),
            ),
            SimulatedPollingCycle(
                cycle_id="cycle_2",
                acquisition_plan=AcquisitionPlan(
                    plan_id="cycle_2_plan",
                    requests=(
                        request_for(
                            "temperature_cycle_2",
                            "sim.temperature",
                            "sensor_temperature",
                            "degC",
                            225,
                            0.1,
                            observed_at=datetime(2026, 7, 21, 12, 5, 0, tzinfo=UTC),
                        ),
                        request_for(
                            "humidity_cycle_2",
                            "sim.humidity",
                            "sensor_humidity",
                            "%",
                            440,
                            0.1,
                            observed_at=datetime(2026, 7, 21, 12, 5, 0, tzinfo=UTC),
                        ),
                    ),
                ),
            ),
        ),
    )

    report = runner.run(plan)
    snapshot = CurrentStateProjector(
        registry,
        historian,
        clock=lambda: SNAPSHOT_AT,
    ).project(residence_id="residence_home", system_id="system_main")
    history_payload = export_measurements(
        historian.query_system("system_main", registry),
        export_id="simulated_polling_history",
    )
    snapshot_payload = export_snapshot(snapshot, export_id="simulated_polling_snapshot")

    assert report.success_count == 3
    assert historian.count() == 3
    assert history_payload["count"] == 3
    snapshot_sensors = snapshot_payload["snapshot"]["equipment"][0]["sensors"]
    values_by_sensor = {item["sensor_id"]: item["value"] for item in snapshot_sensors}
    assert values_by_sensor == {
        "sensor_temperature": 22.5,
        "sensor_humidity": 44.0,
    }
    json.dumps(report.to_dict(), sort_keys=True)
    json.dumps(history_payload, sort_keys=True)
    json.dumps(snapshot_payload, sort_keys=True)


def request_for(
    request_id: str,
    register_id: str,
    sensor_id: str,
    unit: str,
    word: int,
    scale: float,
    *,
    observed_at: datetime,
) -> AcquisitionRequest:
    definition = register_definition(register_id, sensor_id, unit, scale=scale)
    service = SimulatedModbusAcquisitionService(
        SimulatedModbusRegisterClient((payload(register_id, word, observed_at),))
    )
    return AcquisitionRequest(
        request_id=request_id,
        profile_id="simulated.polling.v1",
        executor=lambda pipeline: service.acquire(
            (definition,),
            pipeline,
            profile_id="simulated.polling.v1",
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
        profile_id="simulated.polling.v1",
        executor=lambda pipeline: service.acquire(
            (definition,),
            pipeline,
            profile_id="simulated.polling.v1",
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
        source_reference="simulated polling fixture",
    )


def payload(
    register_id: str,
    word: int,
    observed_at: datetime,
) -> SimulatedRegisterPayload:
    return SimulatedRegisterPayload(
        register_id=register_id,
        words=(word,),
        observed_at=observed_at,
    )


def polling_runner_for(
    registry: InMemoryAssetRegistry,
    historian: InMemoryMeasurementHistorian,
    *,
    polling_clock: Callable[[], datetime],
    acquisition_clock: Callable[[], datetime],
) -> SimulatedPollingRunner:
    pipeline = AcquisitionPipeline(
        IngestionService(
            MeasurementNormalizer(clock=lambda: RECEIVED_AT),
            historian,
            registry,
        ),
        clock=lambda: RECEIVED_AT,
    )
    return SimulatedPollingRunner(
        AcquisitionRunner(pipeline, clock=acquisition_clock),
        clock=polling_clock,
    )


def clock_sequence(*values: datetime) -> Callable[[], datetime]:
    timestamps = list(values)

    def tick() -> datetime:
        if not timestamps:
            raise AssertionError("clock exhausted")
        return timestamps.pop(0)

    return tick


def registry_with_polling_sensors() -> InMemoryAssetRegistry:
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
