#!/usr/bin/env python3
# ruff: noqa: E402
"""Run deterministic GeoPilot simulated polling cycles."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_SRC = REPO_ROOT / "backend" / "src"
if str(BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC))

from geopilot.acquisition import AcquisitionPipeline
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
    SimulatedPollingPlan,
    SimulatedPollingRunner,
)
from geopilot.snapshot import CurrentStateProjector

CREATED_AT = datetime(2026, 7, 21, 12, 0, 0, tzinfo=UTC)
RECEIVED_AT = datetime(2026, 7, 21, 12, 20, 0, tzinfo=UTC)
SNAPSHOT_AT = datetime(2026, 7, 21, 12, 15, 0, tzinfo=UTC)


def main() -> int:
    registry = build_registry()
    historian = InMemoryMeasurementHistorian()
    pipeline = AcquisitionPipeline(
        IngestionService(
            MeasurementNormalizer(clock=lambda: RECEIVED_AT),
            historian,
            registry,
        ),
        clock=lambda: RECEIVED_AT,
    )
    polling_runner = SimulatedPollingRunner(
        AcquisitionRunner(
            pipeline,
            clock=clock_sequence(
                datetime(2026, 7, 21, 12, 0, 1, tzinfo=UTC),
                datetime(2026, 7, 21, 12, 0, 2, tzinfo=UTC),
                datetime(2026, 7, 21, 12, 5, 1, tzinfo=UTC),
                datetime(2026, 7, 21, 12, 5, 2, tzinfo=UTC),
                datetime(2026, 7, 21, 12, 10, 1, tzinfo=UTC),
                datetime(2026, 7, 21, 12, 10, 2, tzinfo=UTC),
            ),
        ),
        clock=clock_sequence(
            datetime(2026, 7, 21, 12, 0, 0, tzinfo=UTC),
            datetime(2026, 7, 21, 12, 15, 0, tzinfo=UTC),
        ),
    )

    polling_report = polling_runner.run(build_polling_plan())
    snapshot = CurrentStateProjector(
        registry,
        historian,
        clock=lambda: SNAPSHOT_AT,
    ).project(residence_id="residence_home", system_id="system_main")

    payload = {
        "polling_report": polling_report.to_dict(),
        "history": export_measurements(
            historian.query_system("system_main", registry),
            export_id="simulated_polling_history",
        ),
        "snapshot": export_snapshot(
            snapshot,
            export_id="simulated_polling_snapshot",
        ),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def build_polling_plan() -> SimulatedPollingPlan:
    return SimulatedPollingPlan(
        plan_id="simulated_polling_demo",
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
                        request_for(
                            "humidity_cycle_1",
                            "sim.humidity",
                            "sensor_humidity",
                            "%",
                            420,
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
                            218,
                            0.1,
                            observed_at=datetime(2026, 7, 21, 12, 5, 0, tzinfo=UTC),
                        ),
                        request_for(
                            "humidity_cycle_2",
                            "sim.humidity",
                            "sensor_humidity",
                            "%",
                            435,
                            0.1,
                            observed_at=datetime(2026, 7, 21, 12, 5, 0, tzinfo=UTC),
                        ),
                    ),
                ),
            ),
            SimulatedPollingCycle(
                cycle_id="cycle_3",
                acquisition_plan=AcquisitionPlan(
                    plan_id="cycle_3_plan",
                    requests=(
                        request_for(
                            "temperature_cycle_3",
                            "sim.temperature",
                            "sensor_temperature",
                            "degC",
                            225,
                            0.1,
                            observed_at=datetime(2026, 7, 21, 12, 10, 0, tzinfo=UTC),
                        ),
                        request_for(
                            "humidity_cycle_3",
                            "sim.humidity",
                            "sensor_humidity",
                            "%",
                            440,
                            0.1,
                            observed_at=datetime(2026, 7, 21, 12, 10, 0, tzinfo=UTC),
                        ),
                    ),
                ),
            ),
        ),
    )


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
    definition = RegisterDefinition(
        register_id=register_id,
        source_id="source_simulated_modbus",
        sensor_id=sensor_id,
        unit=unit,
        data_type=RegisterDataType.UINT16,
        scale=scale,
        source_reference="simulated polling fixture",
    )
    service = SimulatedModbusAcquisitionService(
        SimulatedModbusRegisterClient(
            (
                SimulatedRegisterPayload(
                    register_id=register_id,
                    words=(word,),
                    observed_at=observed_at,
                ),
            )
        )
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


def build_registry() -> InMemoryAssetRegistry:
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


def clock_sequence(*values: datetime) -> Callable[[], datetime]:
    timestamps = list(values)

    def tick() -> datetime:
        if not timestamps:
            raise RuntimeError("clock exhausted")
        return timestamps.pop(0)

    return tick


if __name__ == "__main__":
    raise SystemExit(main())
