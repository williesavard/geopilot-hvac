from __future__ import annotations

import json
from datetime import UTC, datetime

from geopilot.domain import DataQuality, Measurement
from geopilot.export import (
    EXPORT_SCHEMA_VERSION,
    export_measurement,
    export_measurements,
    export_snapshot,
)
from geopilot.scenarios import run_simulated_geothermal_snapshot

NOW = datetime(2026, 7, 21, 12, 0, 0, tzinfo=UTC)
RECEIVED = datetime(2026, 7, 21, 12, 30, 0, tzinfo=UTC)


def measurement(
    measurement_id: str,
    observed_at: datetime,
    received_at: datetime,
    value: int | float,
) -> Measurement:
    return Measurement(
        id=measurement_id,
        sensor_id="sensor_a",
        observed_at=observed_at,
        received_at=received_at,
        value=value,
        unit="degC",
        quality=DataQuality.GOOD,
        source_id="source_simulated",
    )


def test_export_measurement_is_json_safe() -> None:
    item = measurement("m1", NOW, RECEIVED, 21.5)

    payload = export_measurement(item)

    assert payload == {
        "id": "m1",
        "sensor_id": "sensor_a",
        "observed_at": "2026-07-21T12:00:00Z",
        "received_at": "2026-07-21T12:30:00Z",
        "value": 21.5,
        "unit": "degC",
        "quality": "good",
        "source_id": "source_simulated",
    }
    json.dumps(payload, sort_keys=True)


def test_export_measurements_sorts_deterministically() -> None:
    later_received = datetime(2026, 7, 21, 12, 31, 0, tzinfo=UTC)
    items = (
        measurement("m3", NOW, later_received, 3),
        measurement("m2", NOW, RECEIVED, 2),
        measurement("m1", NOW, RECEIVED, 1),
    )

    payload = export_measurements(items, export_id="export_test")

    assert payload["schema"] == "geopilot.measurements_export"
    assert payload["schema_version"] == EXPORT_SCHEMA_VERSION
    assert payload["export_id"] == "export_test"
    assert payload["count"] == 3
    assert [item["id"] for item in payload["measurements"]] == ["m1", "m2", "m3"]
    json.dumps(payload, sort_keys=True)


def test_export_snapshot_wraps_current_state_projection() -> None:
    snapshot = run_simulated_geothermal_snapshot()

    payload = export_snapshot(snapshot, export_id="snapshot_demo")

    assert payload["schema"] == "geopilot.snapshot_export"
    assert payload["schema_version"] == EXPORT_SCHEMA_VERSION
    assert payload["export_id"] == "snapshot_demo"
    assert payload["snapshot"]["generated_at"] == "2026-07-21T12:10:00Z"
    assert payload["snapshot"]["equipment"][0]["equipment_id"] == (
        "equipment_geothermal_heat_pump"
    )
    json.dumps(payload, sort_keys=True)
