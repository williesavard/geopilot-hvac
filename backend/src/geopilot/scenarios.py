"""Reusable simulated GeoPilot scenarios.

These scenarios exercise the in-memory domain, registry, ingestion, and
projection pipeline. They do not represent real hardware integrations.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

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
from geopilot.ingestion import (
    IngestionService,
    MeasurementNormalizer,
    RawMeasurement,
)
from geopilot.registry import InMemoryAssetRegistry
from geopilot.snapshot import CurrentStateProjector, GeothermalSnapshot

SCENARIO_CREATED_AT = datetime(2026, 7, 21, 12, 0, 0, tzinfo=UTC)
SNAPSHOT_GENERATED_AT = datetime(2026, 7, 21, 12, 10, 0, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class SimulatedGeothermalScenario:
    """Assets for the simulated geothermal snapshot scenario."""

    residence: Residence
    hvac_system: HVACSystem
    equipment: Equipment
    sensors: tuple[Sensor, ...]
    registry: InMemoryAssetRegistry


@dataclass(frozen=True, slots=True)
class SimulatedGeothermalHistory:
    """In-memory history result for the simulated geothermal scenario."""

    scenario: SimulatedGeothermalScenario
    historian: InMemoryMeasurementHistorian


def build_simulated_geothermal_scenario() -> SimulatedGeothermalScenario:
    """Build a deterministic in-memory geothermal residence scenario."""

    residence = Residence(
        id="residence_demo",
        name="Demo Residence",
        timezone="America/Toronto",
        created_at=SCENARIO_CREATED_AT,
    )
    hvac_system = HVACSystem(
        id="system_geothermal_main",
        residence_id=residence.id,
        name="Main geothermal HVAC system",
        system_type=SystemType.HYDRONIC,
        created_at=SCENARIO_CREATED_AT,
    )
    equipment = Equipment(
        id="equipment_geothermal_heat_pump",
        hvac_system_id=hvac_system.id,
        name="Geothermal heat pump",
        equipment_type=EquipmentType.HEAT_PUMP,
        created_at=SCENARIO_CREATED_AT,
    )
    sensors = (
        _temperature_sensor("sensor_loop_entering_temp", "Loop entering temperature"),
        _temperature_sensor("sensor_loop_leaving_temp", "Loop leaving temperature"),
        _temperature_sensor("sensor_return_air_temp", "Return air temperature"),
        _temperature_sensor("sensor_supply_air_temp", "Supply air temperature"),
        Sensor(
            id="sensor_relative_humidity",
            equipment_id=equipment.id,
            name="Relative humidity",
            measurement_kind=MeasurementKind.HUMIDITY,
            unit="%",
            source_id="source_simulated_geothermal",
            created_at=SCENARIO_CREATED_AT,
        ),
        Sensor(
            id="sensor_electrical_power",
            equipment_id=equipment.id,
            name="Electrical power",
            measurement_kind=MeasurementKind.POWER,
            unit="W",
            source_id="source_simulated_geothermal",
            created_at=SCENARIO_CREATED_AT,
        ),
    )

    registry = InMemoryAssetRegistry()
    registry.add_residence(residence)
    registry.add_hvac_system(hvac_system)
    registry.add_equipment(equipment)
    for sensor in sensors:
        registry.add_sensor(sensor)

    return SimulatedGeothermalScenario(
        residence=residence,
        hvac_system=hvac_system,
        equipment=equipment,
        sensors=sensors,
        registry=registry,
    )


def run_simulated_geothermal_snapshot() -> GeothermalSnapshot:
    """Run the complete in-memory simulated geothermal snapshot pipeline."""

    history = run_simulated_geothermal_history()
    scenario = history.scenario

    projector = CurrentStateProjector(
        scenario.registry,
        history.historian,
        clock=lambda: SNAPSHOT_GENERATED_AT,
    )
    return projector.project(
        residence_id=scenario.residence.id,
        system_id=scenario.hvac_system.id,
    )


def run_simulated_geothermal_history() -> SimulatedGeothermalHistory:
    """Run the complete in-memory simulated geothermal history pipeline."""

    scenario = build_simulated_geothermal_scenario()
    historian = InMemoryMeasurementHistorian()
    service = IngestionService(
        MeasurementNormalizer(clock=lambda: SNAPSHOT_GENERATED_AT),
        historian,
        scenario.registry,
    )

    for raw in _simulated_measurements():
        service.ingest(raw)

    return SimulatedGeothermalHistory(scenario=scenario, historian=historian)


def simulated_history_query_window() -> tuple[datetime, datetime]:
    """Return the default demonstration query window for simulated history."""

    return (
        datetime.fromisoformat("2026-07-21T12:00:00+00:00"),
        datetime.fromisoformat("2026-07-21T12:06:00+00:00"),
    )


def _temperature_sensor(sensor_id: str, name: str) -> Sensor:
    return Sensor(
        id=sensor_id,
        equipment_id="equipment_geothermal_heat_pump",
        name=name,
        measurement_kind=MeasurementKind.TEMPERATURE,
        unit="degC",
        source_id="source_simulated_geothermal",
        created_at=SCENARIO_CREATED_AT,
    )


def _simulated_measurements() -> tuple[RawMeasurement, ...]:
    return (
        _raw("sensor_loop_entering_temp", 44.6, "°F", "2026-07-21T11:55:00+00:00"),
        _raw("sensor_loop_entering_temp", 45.5, "°F", "2026-07-21T12:00:00+00:00"),
        _raw("sensor_loop_leaving_temp", 6.1, "°C", "2026-07-21T12:00:00+00:00"),
        _raw("sensor_return_air_temp", 20.0, "°C", "2026-07-21T12:00:00+00:00"),
        _raw("sensor_supply_air_temp", 32.0, "°C", "2026-07-21T12:00:00+00:00"),
        _raw("sensor_supply_air_temp", 33.0, "°C", "2026-07-21T12:05:00+00:00"),
        _raw("sensor_relative_humidity", 42.0, "%", "2026-07-21T12:00:00+00:00"),
        _raw("sensor_relative_humidity", 43.0, "%", "2026-07-21T12:04:00+00:00"),
        _raw("sensor_electrical_power", 2.4, "kW", "2026-07-21T12:00:00+00:00"),
    )


def _raw(sensor_id: str, value: int | float, unit: str, timestamp: str) -> RawMeasurement:
    return RawMeasurement(
        source_id="source_simulated_geothermal",
        sensor_id=sensor_id,
        value=value,
        unit=unit,
        timestamp=datetime.fromisoformat(timestamp),
    )
