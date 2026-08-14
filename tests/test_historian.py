"""Historian contract tests.

Every test in this file runs against both historian implementations through the
`MeasurementHistorian` protocol. A behavior that holds for one implementation
and not the other is a bug, so the suite is parametrized rather than
duplicated. Storage-specific behavior lives in `test_sqlite_historian.py`.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any, cast

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
from geopilot.historian import (
    DuplicateMeasurementConflictError,
    HistorianQueryError,
    InMemoryMeasurementHistorian,
    MeasurementHistorian,
)
from geopilot.ingestion import (
    IngestionService,
    MeasurementNormalizer,
    RawMeasurement,
)
from geopilot.registry import AssetNotFoundError, InMemoryAssetRegistry
from geopilot.snapshot import CurrentStateProjector
from geopilot.sqlite_historian import SqliteMeasurementHistorian

NOW = datetime(2026, 7, 21, 12, 0, 0, tzinfo=UTC)
RECEIVED = datetime(2026, 7, 21, 12, 30, 0, tzinfo=UTC)
LATER = datetime(2026, 7, 21, 12, 5, 0, tzinfo=UTC)


@pytest.fixture(params=["memory", "sqlite"])
def historian(request: pytest.FixtureRequest) -> Iterator[MeasurementHistorian]:
    if request.param == "memory":
        yield InMemoryMeasurementHistorian()
        return
    with SqliteMeasurementHistorian() as sqlite_historian:
        yield sqlite_historian


def measurement(
    sensor_id: str = "sensor_a",
    value: int | float = 20.0,
    observed_at: datetime = NOW,
    received_at: datetime = RECEIVED,
    *,
    measurement_id: str | None = None,
    unit: str = "degC",
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


def registry_with_two_systems() -> InMemoryAssetRegistry:
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
            name="Main system",
            system_type=SystemType.HYDRONIC,
            created_at=NOW,
        )
    )
    registry.add_hvac_system(
        HVACSystem(
            id="system_other",
            residence_id="residence_home",
            name="Other system",
            system_type=SystemType.FORCED_AIR,
            created_at=NOW,
        )
    )
    registry.add_equipment(
        Equipment(
            id="equipment_main",
            hvac_system_id="system_main",
            name="Main equipment",
            equipment_type=EquipmentType.HEAT_PUMP,
            created_at=NOW,
        )
    )
    registry.add_equipment(
        Equipment(
            id="equipment_other",
            hvac_system_id="system_other",
            name="Other equipment",
            equipment_type=EquipmentType.HEAT_PUMP,
            created_at=NOW,
        )
    )
    registry.add_sensor(sensor("sensor_b", "equipment_main"))
    registry.add_sensor(sensor("sensor_a", "equipment_main"))
    registry.add_sensor(sensor("sensor_other", "equipment_other"))
    return registry


def sensor(sensor_id: str, equipment_id: str) -> Sensor:
    return Sensor(
        id=sensor_id,
        equipment_id=equipment_id,
        name=sensor_id,
        measurement_kind=MeasurementKind.TEMPERATURE,
        unit="degC",
        source_id="source_simulated",
        created_at=NOW,
    )


def populate(historian: MeasurementHistorian) -> MeasurementHistorian:
    historian.append(measurement("sensor_a", 20.0, NOW, RECEIVED, measurement_id="m1"))
    historian.append(measurement("sensor_a", 21.0, LATER, RECEIVED, measurement_id="m2"))
    historian.append(measurement("sensor_b", 22.0, NOW, RECEIVED, measurement_id="m3"))
    historian.append(measurement("sensor_other", 23.0, NOW, RECEIVED, measurement_id="m4"))
    return historian


def test_append_and_count(historian: MeasurementHistorian) -> None:
    item = measurement()

    historian.append(item)

    assert historian.count() == 1
    assert historian.all() == (item,)


def test_all_preserves_insertion_order(historian: MeasurementHistorian) -> None:
    first = measurement("sensor_a", 1, NOW, RECEIVED, measurement_id="m2")
    second = measurement("sensor_a", 2, NOW, RECEIVED, measurement_id="m1")

    historian.append(first)
    historian.append(second)

    assert historian.all() == (first, second)


def test_latest_for_sensor_uses_temporal_sort_order(historian: MeasurementHistorian) -> None:
    latest = measurement("sensor_a", 21, LATER, RECEIVED, measurement_id="m2")
    historian.append(latest)
    historian.append(measurement("sensor_a", 20, NOW, RECEIVED, measurement_id="m1"))

    assert historian.latest_for_sensor("sensor_a") == latest
    assert historian.latest_for_sensor("missing") is None


def test_query_sensor_without_bounds(historian: MeasurementHistorian) -> None:
    populate(historian)

    result = historian.query_sensor("sensor_a")

    assert [item.id for item in result] == ["m1", "m2"]


def test_query_sensor_start_inclusive_and_end_exclusive(
    historian: MeasurementHistorian,
) -> None:
    populate(historian)

    result = historian.query_sensor("sensor_a", start=NOW, end=LATER)

    assert [item.id for item in result] == ["m1"]


def test_query_sensor_start_equal_end_returns_empty(historian: MeasurementHistorian) -> None:
    populate(historian)

    result = historian.query_sensor("sensor_a", start=NOW, end=NOW)

    assert result == ()


def test_query_rejects_start_after_end(historian: MeasurementHistorian) -> None:
    with pytest.raises(HistorianQueryError, match="start"):
        historian.query_sensor(
            "sensor_a",
            start=datetime(2026, 7, 21, 12, 1, 0, tzinfo=UTC),
            end=NOW,
        )


def test_query_rejects_naive_start_and_end(historian: MeasurementHistorian) -> None:
    with pytest.raises(HistorianQueryError, match="start"):
        historian.query_sensor("sensor_a", start=datetime(2026, 7, 21, 12, 0, 0))
    with pytest.raises(HistorianQueryError, match="end"):
        historian.query_sensor("sensor_a", end=datetime(2026, 7, 21, 12, 0, 0))


def test_query_rejects_blank_identifier(historian: MeasurementHistorian) -> None:
    with pytest.raises(HistorianQueryError, match="sensor_id"):
        historian.query_sensor("   ")


def test_query_sensor_sorts_by_observed_received_then_id(
    historian: MeasurementHistorian,
) -> None:
    later_received = datetime(2026, 7, 21, 12, 31, 0, tzinfo=UTC)
    historian.append(measurement("sensor_a", 3, NOW, later_received, measurement_id="m3"))
    historian.append(measurement("sensor_a", 1, NOW, RECEIVED, measurement_id="m2"))
    historian.append(measurement("sensor_a", 2, NOW, RECEIVED, measurement_id="m1"))

    result = historian.query_sensor("sensor_a")

    assert [item.id for item in result] == ["m1", "m2", "m3"]


def test_query_sensor_excludes_other_sensors(historian: MeasurementHistorian) -> None:
    populate(historian)

    result = historian.query_sensor("sensor_b")

    assert [item.sensor_id for item in result] == ["sensor_b"]


def test_duplicate_identical_measurement_is_idempotent(
    historian: MeasurementHistorian,
) -> None:
    item = measurement(measurement_id="same")

    historian.append(item)
    historian.append(item)

    assert historian.all() == (item,)
    assert historian.count() == 1


def test_same_observation_received_later_is_idempotent(
    historian: MeasurementHistorian,
) -> None:
    """A repeated read is the same observation arriving twice, not a conflict."""

    first = measurement(measurement_id="same", received_at=RECEIVED)
    later = measurement(
        measurement_id="same",
        received_at=datetime(2026, 7, 21, 18, 0, 0, tzinfo=UTC),
    )

    historian.append(first)
    historian.append(later)

    assert historian.count() == 1
    # The stored copy wins; a later ingestion does not rewrite history.
    assert historian.all() == (first,)


def test_duplicate_id_with_different_value_conflicts(
    historian: MeasurementHistorian,
) -> None:
    historian.append(measurement(value=20, measurement_id="same"))

    with pytest.raises(DuplicateMeasurementConflictError, match="different content"):
        historian.append(measurement(value=21, measurement_id="same"))

    assert historian.count() == 1


def test_duplicate_id_with_different_unit_conflicts(
    historian: MeasurementHistorian,
) -> None:
    historian.append(measurement(measurement_id="same", unit="degC"))

    with pytest.raises(DuplicateMeasurementConflictError, match="different content"):
        historian.append(measurement(measurement_id="same", unit="%"))


def test_duplicate_id_with_different_observed_at_conflicts(
    historian: MeasurementHistorian,
) -> None:
    historian.append(measurement(observed_at=NOW, measurement_id="same"))

    with pytest.raises(DuplicateMeasurementConflictError, match="different content"):
        historian.append(measurement(observed_at=LATER, measurement_id="same"))


def test_query_results_are_immutable_tuples(historian: MeasurementHistorian) -> None:
    populate(historian)
    result = historian.query_sensor("sensor_a")

    assert isinstance(result, tuple)
    with pytest.raises(TypeError):
        cast(Any, result)[0] = measurement()


def test_query_system_includes_only_system_sensors(historian: MeasurementHistorian) -> None:
    registry = registry_with_two_systems()
    populate(historian)

    result = historian.query_system("system_main", registry)

    assert [item.id for item in result] == ["m1", "m3", "m2"]
    assert {item.sensor_id for item in result} == {"sensor_a", "sensor_b"}


def test_query_system_rejects_unknown_system(historian: MeasurementHistorian) -> None:
    registry = registry_with_two_systems()

    with pytest.raises(AssetNotFoundError, match="Unknown HVAC system"):
        historian.query_system("missing", registry)


def test_query_system_filters_time_window_and_preserves_registry(
    historian: MeasurementHistorian,
) -> None:
    registry = registry_with_two_systems()
    populate(historian)
    before_equipment = registry.list_equipment_for_system("system_main")
    before_sensors = registry.list_sensors_for_equipment("equipment_main")

    result = historian.query_system("system_main", registry, start=NOW, end=LATER)

    assert [item.id for item in result] == ["m1", "m3"]
    assert registry.list_equipment_for_system("system_main") == before_equipment
    assert registry.list_sensors_for_equipment("equipment_main") == before_sensors


def test_ingestion_service_writes_into_historian(historian: MeasurementHistorian) -> None:
    registry = registry_with_two_systems()
    service = IngestionService(
        MeasurementNormalizer(clock=lambda: RECEIVED),
        historian,
        registry,
    )

    measurement_result = service.ingest(
        RawMeasurement(
            source_id="source_simulated",
            sensor_id="sensor_a",
            value=68.0,
            unit="°F",
            timestamp=NOW,
        )
    )

    assert historian.all() == (measurement_result,)
    assert historian.latest_for_sensor("sensor_a") == measurement_result


def test_reingesting_an_unchanged_reading_is_idempotent(
    historian: MeasurementHistorian,
) -> None:
    """Re-reading an unchanged register must not be an error.

    Before the measurement id ADR this raised
    `DuplicateMeasurementConflictError`, because the id was identical while
    `received_at` had moved. Repeated reads are normal on a real Modbus bus and
    the bench runbook repeats them deliberately.
    """

    registry = registry_with_two_systems()
    clocks = iter([RECEIVED, datetime(2026, 7, 21, 18, 0, 0, tzinfo=UTC)])
    service = IngestionService(
        MeasurementNormalizer(clock=lambda: next(clocks)),
        historian,
        registry,
    )
    raw = RawMeasurement(
        source_id="source_simulated",
        sensor_id="sensor_a",
        value=20.0,
        unit="degC",
        timestamp=NOW,
    )

    first = service.ingest(raw)
    second = service.ingest(raw)

    assert first.id == second.id
    assert second.received_at != first.received_at
    assert historian.count() == 1
    assert historian.all() == (first,)


def test_contradictory_reading_at_the_same_instant_conflicts(
    historian: MeasurementHistorian,
) -> None:
    """Two different values for one sensor at one instant is an acquisition fault.

    Before the measurement id ADR both were stored as unrelated measurements,
    because the value was part of the id.
    """

    registry = registry_with_two_systems()
    service = IngestionService(
        MeasurementNormalizer(clock=lambda: RECEIVED),
        historian,
        registry,
    )

    def reading(value: float) -> RawMeasurement:
        return RawMeasurement(
            source_id="source_simulated",
            sensor_id="sensor_a",
            value=value,
            unit="degC",
            timestamp=NOW,
        )

    service.ingest(reading(20.0))

    with pytest.raises(DuplicateMeasurementConflictError, match="different content"):
        service.ingest(reading(400.0))

    assert historian.count() == 1


def test_current_state_projector_works_with_historian(
    historian: MeasurementHistorian,
) -> None:
    registry = registry_with_two_systems()
    older = measurement("sensor_a", 20, NOW, RECEIVED, measurement_id="m1")
    newer = measurement("sensor_a", 21, LATER, RECEIVED, measurement_id="m2")
    historian.append(newer)
    historian.append(older)

    snapshot = CurrentStateProjector(
        registry,
        historian,
        clock=lambda: RECEIVED,
    ).project(residence_id="residence_home", system_id="system_main")

    assert snapshot.equipment[0].sensors[0].measurement_id == "m2"
