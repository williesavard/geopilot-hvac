#!/usr/bin/env python3
"""Run the GeoPilot simulated in-memory history example."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_SRC = REPO_ROOT / "backend" / "src"
if str(BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC))


def serialize(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return value


def measurement_to_dict(measurement: Any) -> dict[str, Any]:
    return {
        "id": measurement.id,
        "sensor_id": measurement.sensor_id,
        "value": measurement.value,
        "unit": measurement.unit,
        "observed_at": serialize(measurement.observed_at),
        "received_at": serialize(measurement.received_at),
        "quality": serialize(measurement.quality),
    }


def main() -> int:
    from geopilot.scenarios import (
        run_simulated_geothermal_history,
        simulated_history_query_window,
    )

    history = run_simulated_geothermal_history()
    start, end = simulated_history_query_window()
    sensor_id = "sensor_supply_air_temp"
    system_id = history.scenario.hvac_system.id
    sensor_measurements = history.historian.query_sensor(sensor_id, start=start, end=end)
    system_measurements = history.historian.query_system(
        system_id,
        history.scenario.registry,
        start=start,
        end=end,
    )

    payload = {
        "sensor_id": sensor_id,
        "start": serialize(start),
        "end": serialize(end),
        "count": len(sensor_measurements),
        "measurements": [measurement_to_dict(item) for item in sensor_measurements],
        "system_id": system_id,
        "system_measurement_count": len(system_measurements),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
