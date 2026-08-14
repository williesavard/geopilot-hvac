import json
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from typing import cast

import pytest
from geopilot.domain import (
    DataQuality,
    Equipment,
    EquipmentType,
    HVACSystem,
    Measurement,
    MeasurementKind,
    Residence,
    Sensor,
    SystemType,
)
from geopilot.ingestion import InMemoryMeasurementSink
from geopilot.registry import InMemoryAssetRegistry
from geopilot.snapshot import CurrentStateProjector, GeothermalSnapshot

NOW = datetime(2026, 7, 21, 12, 0, 0, tzinfo=UTC)
GENERATED_AT = datetime(2026, 7, 21, 12, 30, 0, tzinfo=UTC)


def registry_with_assets() -> InMemoryAssetRegistry:
    registry = InMemoryAssetRegistry()
    registry.add_residence(
        Residence(
            id="residence_home",
            name="Home",
            timezone="America/Toronto",
            created_at=NOW,
        )
    )
    registry.add_hvac_system(
        HVACSystem(
            id="system_main",
            residence_id="residence_home",
            name="Main geothermal system",
            system_type=SystemType.HYDRONIC,
            created_at=NOW,
        )
    )
    registry.add_equipment(
        Equipment(
            id="equipment_b",
            hvac_system_id="system_main",
            name="Equipment B",
            equipment_type=EquipmentType.HEAT_PUMP,
            created_at=NOW,
        )
    )
    registry.add_equipment(
        Equipment(
            id="equipment_a",
            hvac_system_id="system_main",
            name="Equipment A",
            equipment_type=EquipmentType.HEAT_PUMP,
            created_at=NOW,
        )
    )
    registry.add_sensor(sensor("sensor_b", "equipment_a", MeasurementKind.TEMPERATURE))
    registry.add_sensor(sensor("sensor_a", "equipment_a", MeasurementKind.TEMPERATURE))
    registry.add_sensor(sensor("sensor_c", "equipment_b", MeasurementKind.POWER, unit="W"))
    return registry


def sensor(
    sensor_id: str,
    equipment_id: str,
    kind: MeasurementKind,
    *,
    unit: str = "degC",
) -> Sensor:
    return Sensor(
        id=sensor_id,
        equipment_id=equipment_id,
        name=sensor_id.replace("_", " ").title(),
        measurement_kind=kind,
        unit=unit,
        source_id="source_simulated",
        created_at=NOW,
    )


def measurement(
    sensor_id: str,
    value: int | float,
    observed_at: datetime,
    received_at: datetime,
    *,
    unit: str = "degC",
    measurement_id: str | None = None,
) -> Measurement:
    return Measurement(
        id=measurement_id or f"measurement:{sensor_id}:{observed_at.isoformat()}:{value}",
        sensor_id=sensor_id,
        observed_at=observed_at,
        received_at=received_at,
        value=value,
        unit=unit,
        quality=DataQuality.GOOD,
        source_id="source_simulated",
    )


def project(
    sink: InMemoryMeasurementSink,
    registry: InMemoryAssetRegistry,
) -> GeothermalSnapshot:
    return CurrentStateProjector(
        registry,
        sink,
        clock=lambda: GENERATED_AT,
    ).project(residence_id="residence_home", system_id="system_main")


def test_snapshot_ignores_sensors_without_measurements() -> None:
    registry = registry_with_assets()
    sink = InMemoryMeasurementSink()

    snapshot = project(sink, registry)

    assert snapshot.generated_at == GENERATED_AT
    assert tuple(equipment.sensors for equipment in snapshot.equipment) == ((), ())


def test_projector_selects_latest_measurement_by_observed_at() -> None:
    registry = registry_with_assets()
    sink = InMemoryMeasurementSink()
    sink.append(measurement("sensor_a", 20.0, NOW, NOW))
    sink.append(
        measurement(
            "sensor_a",
            21.0,
            datetime(2026, 7, 21, 12, 5, 0, tzinfo=UTC),
            NOW,
        )
    )

    snapshot = project(sink, registry)

    assert snapshot.equipment[0].sensors[0].value == 21.0


def test_projector_tiebreaks_same_observed_at_by_received_at_then_id() -> None:
    registry = registry_with_assets()
    sink = InMemoryMeasurementSink()
    sink.append(measurement("sensor_a", 20.0, NOW, NOW, measurement_id="measurement:a"))
    sink.append(
        measurement(
            "sensor_a",
            21.0,
            NOW,
            datetime(2026, 7, 21, 12, 1, 0, tzinfo=UTC),
            measurement_id="measurement:b",
        )
    )
    sink.append(
        measurement(
            "sensor_b",
            22.0,
            NOW,
            NOW,
            measurement_id="measurement:c",
        )
    )
    sink.append(
        measurement(
            "sensor_b",
            23.0,
            NOW,
            NOW,
            measurement_id="measurement:d",
        )
    )

    snapshot = project(sink, registry)
    values_by_sensor = {
        sensor.sensor_id: sensor.value
        for equipment in snapshot.equipment
        for sensor in equipment.sensors
    }

    assert values_by_sensor["sensor_a"] == 21.0
    assert values_by_sensor["sensor_b"] == 23.0


def test_projector_outputs_equipment_and_sensors_in_deterministic_order() -> None:
    registry = registry_with_assets()
    sink = InMemoryMeasurementSink()
    sink.append(measurement("sensor_b", 20.0, NOW, NOW))
    sink.append(measurement("sensor_a", 21.0, NOW, NOW))
    sink.append(measurement("sensor_c", 1200.0, NOW, NOW, unit="W"))

    snapshot = project(sink, registry)

    assert [equipment.equipment_id for equipment in snapshot.equipment] == [
        "equipment_a",
        "equipment_b",
    ]
    assert [sensor.sensor_id for sensor in snapshot.equipment[0].sensors] == [
        "sensor_a",
        "sensor_b",
    ]


def test_snapshot_is_immutable() -> None:
    registry = registry_with_assets()
    sink = InMemoryMeasurementSink()
    sink.append(measurement("sensor_a", 21.0, NOW, NOW))

    snapshot = project(sink, registry)

    with pytest.raises(FrozenInstanceError):
        cast(object, snapshot).residence_id = "other"  # type: ignore[attr-defined]


def test_snapshot_serializes_to_json_compatible_dict() -> None:
    registry = registry_with_assets()
    sink = InMemoryMeasurementSink()
    sink.append(measurement("sensor_a", 21.0, NOW, NOW))

    snapshot = project(sink, registry)
    payload = snapshot.to_dict()

    assert payload["generated_at"] == "2026-07-21T12:30:00Z"
    assert payload["equipment"][0]["sensors"][0]["sensor_kind"] == "temperature"
    json.dumps(payload, sort_keys=True)


def test_projection_does_not_mutate_registry_or_sink() -> None:
    registry = registry_with_assets()
    sink = InMemoryMeasurementSink()
    item = measurement("sensor_a", 21.0, NOW, NOW)
    sink.append(item)
    before_measurements = sink.all()
    before_sensors = registry.list_sensors_for_equipment("equipment_a")

    project(sink, registry)

    assert sink.all() == before_measurements
    assert registry.list_sensors_for_equipment("equipment_a") == before_sensors
