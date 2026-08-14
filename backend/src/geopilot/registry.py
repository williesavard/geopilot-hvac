"""In-memory asset registry for GeoPilot domain objects.

The registry owns local asset lookup and relationship validation. It does not
perform acquisition, normalization, storage, protocol parsing, discovery,
updates, deletion, or equipment control.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from geopilot.domain import Equipment, HVACSystem, Residence, Sensor


class DuplicateAssetError(ValueError):
    """Raised when an asset id is already present in the registry."""


class AssetNotFoundError(KeyError):
    """Raised when an asset id cannot be found."""


class InvalidAssetRelationshipError(ValueError):
    """Raised when an asset references a missing parent."""


class AssetRegistry(Protocol):
    """Storage-independent asset registry contract."""

    def get_residence(self, residence_id: str) -> Residence:
        """Return a residence by id."""

    def get_hvac_system(self, system_id: str) -> HVACSystem:
        """Return an HVAC system by id."""

    def get_equipment(self, equipment_id: str) -> Equipment:
        """Return equipment by id."""

    def get_sensor(self, sensor_id: str) -> Sensor:
        """Return a sensor by id."""

    def list_equipment_for_system(self, system_id: str) -> tuple[Equipment, ...]:
        """Return equipment for an HVAC system in deterministic order."""

    def list_sensors_for_equipment(self, equipment_id: str) -> tuple[Sensor, ...]:
        """Return sensors for equipment in deterministic order."""

    def add_residence(self, residence: Residence) -> None:
        """Add a residence."""

    def add_hvac_system(self, system: HVACSystem) -> None:
        """Add an HVAC system."""

    def add_equipment(self, equipment: Equipment) -> None:
        """Add equipment."""

    def add_sensor(self, sensor: Sensor) -> None:
        """Add a sensor."""


class InMemoryAssetRegistry:
    """Deterministic in-memory registry keyed by domain ids."""

    def __init__(self) -> None:
        self._residences: dict[str, Residence] = {}
        self._hvac_systems: dict[str, HVACSystem] = {}
        self._equipment: dict[str, Equipment] = {}
        self._sensors: dict[str, Sensor] = {}

    def get_residence(self, residence_id: str) -> Residence:
        try:
            return self._residences[residence_id]
        except KeyError as exc:
            raise AssetNotFoundError(f"Unknown residence: {residence_id}") from exc

    def get_hvac_system(self, system_id: str) -> HVACSystem:
        try:
            return self._hvac_systems[system_id]
        except KeyError as exc:
            raise AssetNotFoundError(f"Unknown HVAC system: {system_id}") from exc

    def get_equipment(self, equipment_id: str) -> Equipment:
        try:
            return self._equipment[equipment_id]
        except KeyError as exc:
            raise AssetNotFoundError(f"Unknown equipment: {equipment_id}") from exc

    def get_sensor(self, sensor_id: str) -> Sensor:
        try:
            return self._sensors[sensor_id]
        except KeyError as exc:
            raise AssetNotFoundError(f"Unknown sensor: {sensor_id}") from exc

    def list_equipment_for_system(self, system_id: str) -> tuple[Equipment, ...]:
        self.get_hvac_system(system_id)
        return tuple(
            sorted(
                (
                    equipment
                    for equipment in self._equipment.values()
                    if equipment.hvac_system_id == system_id
                ),
                key=lambda equipment: equipment.id,
            )
        )

    def list_sensors_for_equipment(self, equipment_id: str) -> tuple[Sensor, ...]:
        self.get_equipment(equipment_id)
        return tuple(
            sorted(
                (
                    sensor
                    for sensor in self._sensors.values()
                    if sensor.equipment_id == equipment_id
                ),
                key=lambda sensor: sensor.id,
            )
        )

    def add_residence(self, residence: Residence) -> None:
        self._reject_duplicate(residence.id, self._residences, "residence")
        self._residences[residence.id] = residence

    def add_hvac_system(self, system: HVACSystem) -> None:
        self._reject_duplicate(system.id, self._hvac_systems, "HVAC system")
        if system.residence_id not in self._residences:
            raise InvalidAssetRelationshipError(
                f"HVAC system {system.id} references unknown residence {system.residence_id}"
            )
        self._hvac_systems[system.id] = system

    def add_equipment(self, equipment: Equipment) -> None:
        self._reject_duplicate(equipment.id, self._equipment, "equipment")
        if equipment.hvac_system_id not in self._hvac_systems:
            raise InvalidAssetRelationshipError(
                f"Equipment {equipment.id} references unknown HVAC system "
                f"{equipment.hvac_system_id}"
            )
        self._equipment[equipment.id] = equipment

    def add_sensor(self, sensor: Sensor) -> None:
        self._reject_duplicate(sensor.id, self._sensors, "sensor")
        if sensor.equipment_id not in self._equipment:
            raise InvalidAssetRelationshipError(
                f"Sensor {sensor.id} references unknown equipment {sensor.equipment_id}"
            )
        self._sensors[sensor.id] = sensor

    def _reject_duplicate(
        self,
        asset_id: str,
        assets: Mapping[str, object],
        asset_type: str,
    ) -> None:
        if asset_id in assets:
            raise DuplicateAssetError(f"Duplicate {asset_type}: {asset_id}")
