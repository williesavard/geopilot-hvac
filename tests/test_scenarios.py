from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import pytest
from geopilot.scenarios import (
    SNAPSHOT_GENERATED_AT,
    build_simulated_geothermal_scenario,
    run_simulated_geothermal_history,
    run_simulated_geothermal_snapshot,
    simulated_history_query_window,
)


def sensor_payload(snapshot_payload: dict[str, Any], sensor_id: str) -> dict[str, Any]:
    equipment_payloads = cast(list[dict[str, Any]], snapshot_payload["equipment"])
    for equipment in equipment_payloads:
        sensor_payloads = cast(list[dict[str, Any]], equipment["sensors"])
        for sensor in sensor_payloads:
            if sensor["sensor_id"] == sensor_id:
                return dict(sensor)
    raise AssertionError(f"Missing sensor snapshot: {sensor_id}")


def test_build_simulated_geothermal_scenario_assets() -> None:
    scenario = build_simulated_geothermal_scenario()

    assert scenario.residence.id == "residence_demo"
    assert scenario.hvac_system.id == "system_geothermal_main"
    assert scenario.equipment.id == "equipment_geothermal_heat_pump"
    assert [sensor.id for sensor in scenario.sensors] == [
        "sensor_loop_entering_temp",
        "sensor_loop_leaving_temp",
        "sensor_return_air_temp",
        "sensor_supply_air_temp",
        "sensor_relative_humidity",
        "sensor_electrical_power",
    ]


def test_run_simulated_geothermal_snapshot_complete_pipeline() -> None:
    snapshot = run_simulated_geothermal_snapshot()

    assert snapshot.residence_id == "residence_demo"
    assert snapshot.system_id == "system_geothermal_main"
    assert snapshot.generated_at == SNAPSHOT_GENERATED_AT
    assert len(snapshot.equipment) == 1
    assert len(snapshot.equipment[0].sensors) == 6


def test_simulated_snapshot_exposes_expected_unit_conversions() -> None:
    payload = run_simulated_geothermal_snapshot().to_dict()

    entering_loop = sensor_payload(payload, "sensor_loop_entering_temp")
    electrical_power = sensor_payload(payload, "sensor_electrical_power")

    assert entering_loop["value"] == pytest.approx(7.5)
    assert entering_loop["unit"] == "degC"
    assert electrical_power["value"] == pytest.approx(2400.0)
    assert electrical_power["unit"] == "W"


def test_simulated_snapshot_uses_latest_supply_air_measurement() -> None:
    payload = run_simulated_geothermal_snapshot().to_dict()

    supply_air = sensor_payload(payload, "sensor_supply_air_temp")

    assert supply_air["value"] == 33.0
    assert supply_air["observed_at"] == "2026-07-21T12:05:00Z"


def test_simulated_snapshot_payload_is_json_serializable() -> None:
    payload = run_simulated_geothermal_snapshot().to_dict()

    json.dumps(payload, sort_keys=True)


def test_simulated_snapshot_example_runs_successfully() -> None:
    example = Path("examples/simulated_snapshot.py")

    result = subprocess.run(
        [sys.executable, str(example)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["residence_id"] == "residence_demo"
    assert payload["system_id"] == "system_geothermal_main"


def test_run_simulated_geothermal_history_complete_pipeline() -> None:
    history = run_simulated_geothermal_history()

    assert history.scenario.hvac_system.id == "system_geothermal_main"
    assert history.historian.count() == 9
    assert len(history.historian.query_sensor("sensor_supply_air_temp")) == 2
    assert len(history.historian.query_sensor("sensor_relative_humidity")) == 2


def test_simulated_history_query_window() -> None:
    history = run_simulated_geothermal_history()
    start, end = simulated_history_query_window()

    result = history.historian.query_sensor(
        "sensor_supply_air_temp",
        start=start,
        end=end,
    )

    assert [item.value for item in result] == [32.0, 33.0]


def test_simulated_history_example_runs_successfully() -> None:
    example = Path("examples/simulated_history.py")

    result = subprocess.run(
        [sys.executable, str(example)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["sensor_id"] == "sensor_supply_air_temp"
    assert payload["system_id"] == "system_geothermal_main"
    assert payload["count"] == 2
    assert payload["system_measurement_count"] == 8
