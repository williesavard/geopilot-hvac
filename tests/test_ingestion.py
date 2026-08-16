from datetime import UTC, datetime, timedelta, timezone
from types import MappingProxyType
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
    SensorMeasurementKind,
    SystemType,
)
from geopilot.ingestion import (
    IncompatibleMeasurementUnitError,
    IngestionError,
    IngestionService,
    InMemoryMeasurementSink,
    MeasurementNormalizer,
    RawMeasurement,
)
from geopilot.registry import InMemoryAssetRegistry

OBSERVED = datetime(2026, 7, 21, 12, 0, 0, tzinfo=UTC)


def raw_measurement(
    *,
    value: object = 21.5,
    unit: str = "degC",
    sensor_id: str = "sensor_supply_air_temp",
    source_id: str = "source_simulator",
    timestamp: datetime = OBSERVED,
    quality: DataQuality = DataQuality.GOOD,
    metadata: dict[str, str | int | float | bool | None] | None = None,
) -> RawMeasurement:
    return RawMeasurement(
        source_id=source_id,
        sensor_id=sensor_id,
        value=value,  # type: ignore[arg-type]
        unit=unit,
        timestamp=timestamp,
        quality=quality,
        metadata=metadata,
    )


def normalize(raw: RawMeasurement) -> Measurement:
    return MeasurementNormalizer().normalize(raw)


def registry_with_sensor(sensor: Sensor) -> InMemoryAssetRegistry:
    registry = InMemoryAssetRegistry()
    registry.add_residence(
        Residence(
            id="residence_home",
            name="Home",
            timezone="America/Toronto",
            created_at=OBSERVED,
        )
    )
    registry.add_hvac_system(
        HVACSystem(
            id="hvac_main",
            residence_id="residence_home",
            name="Main HVAC",
            system_type=SystemType.FORCED_AIR,
            created_at=OBSERVED,
        )
    )
    registry.add_equipment(
        Equipment(
            id="equipment_main",
            hvac_system_id="hvac_main",
            name="Main equipment",
            equipment_type=EquipmentType.HEAT_PUMP,
            created_at=OBSERVED,
        )
    )
    registry.add_sensor(sensor)
    return registry


def temperature_sensor() -> Sensor:
    return Sensor(
        id="sensor_supply_air_temp",
        equipment_id="equipment_main",
        name="Supply air temperature",
        measurement_kind=MeasurementKind.TEMPERATURE,
        unit="degC",
        source_id="source_simulator",
        created_at=OBSERVED,
    )


def humidity_sensor() -> Sensor:
    return Sensor(
        id="sensor_return_air_humidity",
        equipment_id="equipment_main",
        name="Return air humidity",
        measurement_kind=MeasurementKind.HUMIDITY,
        unit="%",
        source_id="source_simulator",
        created_at=OBSERVED,
    )


def power_sensor() -> Sensor:
    return Sensor(
        id="sensor_power",
        equipment_id="equipment_main",
        name="Power",
        measurement_kind=MeasurementKind.POWER,
        unit="W",
        source_id="source_simulator",
        created_at=OBSERVED,
    )


def service_for(sensor: Sensor) -> IngestionService:
    return IngestionService(
        MeasurementNormalizer(),
        InMemoryMeasurementSink(),
        registry_with_sensor(sensor),
    )


def test_ingest_direct_celsius() -> None:
    measurement = normalize(raw_measurement(value=21.5, unit="degC"))

    assert measurement.value == 21.5
    assert measurement.unit == "degC"
    assert measurement.quality is DataQuality.GOOD


def test_ingest_celsius_symbol_as_canonical_temperature() -> None:
    measurement = normalize(raw_measurement(value=21.5, unit="°C"))

    assert measurement.value == 21.5
    assert measurement.unit == "degC"


def test_convert_fahrenheit_to_celsius() -> None:
    measurement = normalize(raw_measurement(value=68.0, unit="degF"))

    assert measurement.value == pytest.approx(20.0)
    assert measurement.unit == "degC"


def test_convert_fahrenheit_symbol_to_celsius() -> None:
    measurement = normalize(raw_measurement(value=68.0, unit="°F"))

    assert measurement.value == pytest.approx(20.0)
    assert measurement.unit == "degC"


def test_ingest_direct_watts() -> None:
    measurement = normalize(raw_measurement(value=1200, unit="W"))

    assert measurement.value == 1200
    assert measurement.unit == "W"


def test_convert_kw_to_watts() -> None:
    measurement = normalize(raw_measurement(value=1.25, unit="kW"))

    assert measurement.value == 1250
    assert measurement.unit == "W"


def test_temperature_sensor_accepts_celsius_symbol() -> None:
    measurement = service_for(temperature_sensor()).ingest(
        raw_measurement(value=19.5, unit="°C")
    )

    assert measurement.value == 19.5
    assert measurement.unit == "degC"


def test_temperature_sensor_accepts_fahrenheit_symbol() -> None:
    measurement = service_for(temperature_sensor()).ingest(
        raw_measurement(value=68.0, unit="°F")
    )

    assert measurement.value == pytest.approx(20.0)
    assert measurement.unit == "degC"


def test_reject_watts_on_temperature_sensor() -> None:
    with pytest.raises(IncompatibleMeasurementUnitError, match="temperature"):
        service_for(temperature_sensor()).ingest(raw_measurement(value=1200, unit="W"))


def test_humidity_sensor_accepts_percent() -> None:
    measurement = service_for(humidity_sensor()).ingest(
        raw_measurement(sensor_id="sensor_return_air_humidity", value=45.0, unit="%")
    )

    assert measurement.value == 45.0
    assert measurement.unit == "%"


def test_reject_celsius_on_humidity_sensor() -> None:
    with pytest.raises(IncompatibleMeasurementUnitError, match="relative humidity"):
        service_for(humidity_sensor()).ingest(
            raw_measurement(sensor_id="sensor_return_air_humidity", value=22.0, unit="°C")
        )


def test_power_sensor_accepts_watts() -> None:
    measurement = service_for(power_sensor()).ingest(
        raw_measurement(sensor_id="sensor_power", value=900.0, unit="W")
    )

    assert measurement.value == 900.0
    assert measurement.unit == "W"


def test_power_sensor_accepts_kw() -> None:
    measurement = service_for(power_sensor()).ingest(
        raw_measurement(sensor_id="sensor_power", value=1.5, unit="kW")
    )

    assert measurement.value == 1500.0
    assert measurement.unit == "W"


def test_reject_percent_on_power_sensor() -> None:
    with pytest.raises(IncompatibleMeasurementUnitError, match="power"):
        service_for(power_sensor()).ingest(
            raw_measurement(sensor_id="sensor_power", value=45.0, unit="%")
        )


def test_ingest_relative_humidity_percent() -> None:
    measurement = normalize(raw_measurement(value=45.0, unit="%"))

    assert measurement.value == 45.0
    assert measurement.unit == "%"


def test_reject_unknown_unit() -> None:
    with pytest.raises(IngestionError, match="Unsupported unit"):
        normalize(raw_measurement(value=100, unit="BTU/h"))


def test_reject_incompatible_conversion_unit() -> None:
    with pytest.raises(IngestionError, match="Unsupported unit"):
        normalize(raw_measurement(value=1, unit="degF_per_hour"))


def test_reject_naive_timestamp() -> None:
    with pytest.raises(IngestionError, match="timezone-aware"):
        raw_measurement(timestamp=datetime(2026, 7, 21, 12, 0, 0))


def test_reject_empty_source_id() -> None:
    with pytest.raises(IngestionError, match="source_id"):
        raw_measurement(source_id=" ")


def test_reject_empty_sensor_id() -> None:
    with pytest.raises(IngestionError, match="sensor_id"):
        raw_measurement(sensor_id=" ")


def test_reject_bool_value() -> None:
    with pytest.raises(IngestionError, match="numeric"):
        raw_measurement(value=True)


def test_reject_nan_value() -> None:
    with pytest.raises(IngestionError, match="finite"):
        raw_measurement(value=float("nan"))


def test_reject_infinite_value() -> None:
    with pytest.raises(IngestionError, match="finite"):
        raw_measurement(value=float("inf"))


def test_in_memory_sink_preserves_insertion_order() -> None:
    sink = InMemoryMeasurementSink()
    first = normalize(raw_measurement(sensor_id="sensor_1", value=1, unit="W"))
    second = normalize(raw_measurement(sensor_id="sensor_2", value=2, unit="W"))

    sink.append(first)
    sink.append(second)

    assert sink.all() == (first, second)


def test_latest_for_sensor_returns_newest_matching_measurement() -> None:
    sink = InMemoryMeasurementSink()
    first = normalize(raw_measurement(sensor_id="sensor_1", value=1, unit="W"))
    unrelated = normalize(raw_measurement(sensor_id="sensor_2", value=2, unit="W"))
    latest = normalize(raw_measurement(sensor_id="sensor_1", value=3, unit="W"))

    sink.append(first)
    sink.append(unrelated)
    sink.append(latest)

    assert sink.latest_for_sensor("sensor_1") == latest


def test_empty_sink() -> None:
    sink = InMemoryMeasurementSink()

    assert sink.count() == 0
    assert sink.all() == ()
    assert sink.latest_for_sensor("sensor_1") is None


def test_metadata_is_defensively_copied_and_immutable() -> None:
    metadata: dict[str, str | int | float | bool | None] = {"raw_unit": "degF", "sample": 1}
    raw = raw_measurement(metadata=metadata)
    metadata["sample"] = 2

    assert isinstance(raw.metadata, MappingProxyType)
    assert raw.metadata["sample"] == 1

    with pytest.raises(TypeError):
        cast(Any, raw.metadata)["sample"] = 3


def test_service_ingests_into_memory_sink() -> None:
    sink = InMemoryMeasurementSink()
    service = IngestionService(MeasurementNormalizer(), sink)

    measurement = service.ingest(raw_measurement(value=1.5, unit="kW"))

    assert measurement.value == 1500
    assert sink.all() == (measurement,)


def test_normalizer_uses_injected_clock_for_received_at() -> None:
    received_at = datetime(2026, 7, 21, 12, 30, 0, tzinfo=UTC)
    normalizer = MeasurementNormalizer(clock=lambda: received_at)

    measurement = normalizer.normalize(raw_measurement(value=22, unit="degC"))

    assert measurement.received_at == received_at


class FakeMeasurementSink:
    def __init__(self) -> None:
        self.written: list[Measurement] = []

    def append(self, measurement: Measurement) -> None:
        self.written.append(measurement)


def test_service_uses_fake_sink_implementing_measurement_sink() -> None:
    sink = FakeMeasurementSink()
    service = IngestionService(MeasurementNormalizer(), sink)

    measurement = service.ingest(raw_measurement(value=22, unit="degC"))

    assert sink.written == [measurement]


def test_ingestion_service_with_registry_requires_known_sensor() -> None:
    registry = registry_with_sensor(temperature_sensor())
    sink = InMemoryMeasurementSink()
    service = IngestionService(MeasurementNormalizer(), sink, registry)

    measurement = service.ingest(raw_measurement(value=22, unit="degC"))

    assert sink.all() == (measurement,)


def test_measurement_id_is_stable_for_identical_measurement() -> None:
    normalizer = MeasurementNormalizer()
    raw = raw_measurement(value=20.0, unit="degC")

    first = normalizer.normalize(raw)
    second = normalizer.normalize(raw)

    assert first.id == second.id


def test_measurement_id_is_source_sensor_and_instant() -> None:
    measurement = normalize(raw_measurement(value=20.0, unit="degC"))

    assert measurement.id == "source_simulator:sensor_supply_air_temp:1784635200000000"


def test_measurement_id_ignores_the_value() -> None:
    """Identity is the coordinates of an observation, not the observation.

    Two different values for the same source, sensor and instant must collide so
    the historian reports a conflict instead of storing both as unrelated
    measurements.
    """

    first = normalize(raw_measurement(value=20.0, unit="degC"))
    second = normalize(raw_measurement(value=21.0, unit="degC"))

    assert first.id == second.id


def test_measurement_id_changes_with_the_instant() -> None:
    first = normalize(raw_measurement(value=20.0, unit="degC"))
    second = normalize(
        raw_measurement(
            value=20.0,
            unit="degC",
            timestamp=datetime(2026, 7, 21, 12, 0, 1, tzinfo=UTC),
        )
    )

    assert first.id != second.id


def test_measurement_id_changes_with_the_source_and_sensor() -> None:
    baseline = normalize(raw_measurement())
    other_source = normalize(raw_measurement(source_id="source_modbus"))
    other_sensor = normalize(raw_measurement(sensor_id="sensor_return_air_temp"))

    assert baseline.id != other_source.id
    assert baseline.id != other_sensor.id


def test_measurement_id_is_stable_across_equivalent_source_units() -> None:
    celsius = normalize(raw_measurement(value=20.0, unit="degC"))
    fahrenheit = normalize(raw_measurement(value=68.0, unit="degF"))

    assert celsius.id == fahrenheit.id
    assert celsius.value == fahrenheit.value


def test_measurement_id_uses_the_instant_not_the_local_offset() -> None:
    montreal = timezone(timedelta(hours=-4))
    utc_form = normalize(raw_measurement(timestamp=OBSERVED))
    offset_form = normalize(
        raw_measurement(timestamp=OBSERVED.astimezone(montreal)),
    )

    assert utc_form.id == offset_form.id


def test_ingested_measurement_serializes_to_dict() -> None:
    measurement = service_for(power_sensor()).ingest(
        raw_measurement(sensor_id="sensor_power", value=1.5, unit="kW")
    )

    assert measurement.to_dict() == {
        "id": "source_simulator:sensor_power:1784635200000000",
        "sensor_id": "sensor_power",
        "observed_at": "2026-07-21T12:00:00Z",
        "received_at": measurement.to_dict()["received_at"],
        "value": 1500.0,
        "unit": "W",
        "quality": "good",
        "source_id": "source_simulator",
    }


def state_sensor() -> Sensor:
    return Sensor(
        id="sensor_zone_1_call",
        equipment_id="equipment_main",
        name="Zone 1 call",
        measurement_kind=MeasurementKind.STATE,
        unit="state",
        source_id="source_simulator",
        created_at=OBSERVED,
        sensor_kind=SensorMeasurementKind.STATE,
    )


def test_a_state_is_stored_unchanged() -> None:
    measurement = service_for(state_sensor()).ingest(
        raw_measurement(sensor_id="sensor_zone_1_call", value=1, unit="state")
    )

    assert measurement.value == 1
    assert measurement.unit == "state"


def test_a_state_value_stays_an_integer() -> None:
    """0 and 1 must not become floats, so a state never reads as 1.0."""

    measurement = service_for(state_sensor()).ingest(
        raw_measurement(sensor_id="sensor_zone_1_call", value=0, unit="state")
    )

    assert isinstance(measurement.value, int)


def test_a_fractional_state_is_refused() -> None:
    """A quantity that can be 0.7 is not a state."""

    with pytest.raises(IngestionError, match="must be 0 or 1"):
        service_for(state_sensor()).ingest(
            raw_measurement(sensor_id="sensor_zone_1_call", value=0.7, unit="state")
        )


def test_a_state_above_one_is_refused() -> None:
    with pytest.raises(IngestionError, match="must be 0 or 1"):
        service_for(state_sensor()).ingest(
            raw_measurement(sensor_id="sensor_zone_1_call", value=2, unit="state")
        )


def test_a_boolean_never_reaches_normalization() -> None:
    """The domain rejects booleans before a unit is ever considered."""

    with pytest.raises(IngestionError, match="numeric"):
        raw_measurement(sensor_id="sensor_zone_1_call", value=True, unit="state")


def test_a_state_sensor_refuses_a_physical_unit() -> None:
    with pytest.raises(IncompatibleMeasurementUnitError, match="state sensors"):
        service_for(state_sensor()).ingest(
            raw_measurement(sensor_id="sensor_zone_1_call", value=1, unit="degC")
        )


def test_a_temperature_sensor_refuses_the_state_unit() -> None:
    with pytest.raises(IncompatibleMeasurementUnitError):
        service_for(temperature_sensor()).ingest(
            raw_measurement(value=1, unit="state")
        )


def test_state_normalizes_without_a_sensor() -> None:
    measurement = normalize(raw_measurement(value=1, unit="state"))

    assert measurement.value == 1
    assert measurement.unit == "state"
