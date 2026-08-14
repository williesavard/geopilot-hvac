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
from geopilot.registry import (
    AssetNotFoundError,
    DuplicateAssetError,
    InMemoryAssetRegistry,
    InvalidAssetRelationshipError,
)

NOW = datetime(2026, 7, 21, 12, 0, 0, tzinfo=UTC)


def residence() -> Residence:
    return Residence(
        id="residence_home",
        name="Home",
        timezone="America/Toronto",
        created_at=NOW,
    )


def hvac_system(*, residence_id: str = "residence_home") -> HVACSystem:
    return HVACSystem(
        id="hvac_main",
        residence_id=residence_id,
        name="Main HVAC",
        system_type=SystemType.FORCED_AIR,
        created_at=NOW,
    )


def equipment(*, hvac_system_id: str = "hvac_main") -> Equipment:
    return Equipment(
        id="equipment_main",
        hvac_system_id=hvac_system_id,
        name="Main equipment",
        equipment_type=EquipmentType.HEAT_PUMP,
        created_at=NOW,
    )


def sensor(*, equipment_id: str = "equipment_main") -> Sensor:
    return Sensor(
        id="sensor_supply_air_temp",
        equipment_id=equipment_id,
        name="Supply air temperature",
        measurement_kind=MeasurementKind.TEMPERATURE,
        unit="degC",
        source_id="source_simulator",
        created_at=NOW,
    )


def populated_registry() -> InMemoryAssetRegistry:
    registry = InMemoryAssetRegistry()
    registry.add_residence(residence())
    registry.add_hvac_system(hvac_system())
    registry.add_equipment(equipment())
    return registry


def test_add_and_get_residence() -> None:
    registry = InMemoryAssetRegistry()
    item = residence()

    registry.add_residence(item)

    assert registry.get_residence(item.id) == item


def test_add_hvac_system_with_valid_residence() -> None:
    registry = InMemoryAssetRegistry()
    registry.add_residence(residence())
    system = hvac_system()

    registry.add_hvac_system(system)

    assert registry.get_hvac_system(system.id) == system


def test_reject_hvac_system_with_unknown_residence() -> None:
    registry = InMemoryAssetRegistry()

    with pytest.raises(InvalidAssetRelationshipError, match="unknown residence"):
        registry.add_hvac_system(hvac_system(residence_id="missing"))


def test_add_equipment_with_valid_system() -> None:
    registry = InMemoryAssetRegistry()
    registry.add_residence(residence())
    registry.add_hvac_system(hvac_system())
    item = equipment()

    registry.add_equipment(item)

    assert registry.get_equipment(item.id) == item


def test_reject_equipment_with_unknown_system() -> None:
    registry = InMemoryAssetRegistry()

    with pytest.raises(InvalidAssetRelationshipError, match="unknown HVAC system"):
        registry.add_equipment(equipment(hvac_system_id="missing"))


def test_add_sensor_with_valid_equipment() -> None:
    registry = populated_registry()
    item = sensor()

    registry.add_sensor(item)

    assert registry.get_sensor(item.id) == item


def test_reject_sensor_with_unknown_equipment() -> None:
    registry = InMemoryAssetRegistry()

    with pytest.raises(InvalidAssetRelationshipError, match="unknown equipment"):
        registry.add_sensor(sensor(equipment_id="missing"))


def test_reject_duplicate_residence() -> None:
    registry = InMemoryAssetRegistry()
    registry.add_residence(residence())

    with pytest.raises(DuplicateAssetError, match="Duplicate residence"):
        registry.add_residence(residence())


def test_reject_duplicate_hvac_system() -> None:
    registry = InMemoryAssetRegistry()
    registry.add_residence(residence())
    registry.add_hvac_system(hvac_system())

    with pytest.raises(DuplicateAssetError, match="Duplicate HVAC system"):
        registry.add_hvac_system(hvac_system())


def test_reject_duplicate_equipment() -> None:
    registry = populated_registry()

    with pytest.raises(DuplicateAssetError, match="Duplicate equipment"):
        registry.add_equipment(equipment())


def test_reject_duplicate_sensor() -> None:
    registry = populated_registry()
    registry.add_sensor(sensor())

    with pytest.raises(DuplicateAssetError, match="Duplicate sensor"):
        registry.add_sensor(sensor())


def test_unknown_resources_raise_explicit_errors() -> None:
    registry = InMemoryAssetRegistry()

    with pytest.raises(AssetNotFoundError, match="Unknown residence"):
        registry.get_residence("missing")
    with pytest.raises(AssetNotFoundError, match="Unknown HVAC system"):
        registry.get_hvac_system("missing")
    with pytest.raises(AssetNotFoundError, match="Unknown equipment"):
        registry.get_equipment("missing")
    with pytest.raises(AssetNotFoundError, match="Unknown sensor"):
        registry.get_sensor("missing")
