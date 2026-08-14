"""Deterministic JSON-safe export helpers for GeoPilot read models.

These helpers prepare local data structures for JSON encoding. They do not
write files, open network connections, persist data, calculate diagnostics, or
perform equipment control.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, cast

from geopilot.domain import Measurement
from geopilot.snapshot import GeothermalSnapshot

EXPORT_SCHEMA_VERSION = "0.1.0"


def export_measurement(measurement: Measurement) -> dict[str, Any]:
    """Return a JSON-safe representation of one normalized measurement."""

    return cast(dict[str, Any], _json_safe(measurement))


def export_measurements(
    measurements: Iterable[Measurement],
    *,
    export_id: str,
) -> dict[str, Any]:
    """Return a deterministic JSON-safe measurement collection export."""

    ordered = sorted(measurements, key=_measurement_sort_key)
    return {
        "schema": "geopilot.measurements_export",
        "schema_version": EXPORT_SCHEMA_VERSION,
        "export_id": export_id,
        "count": len(ordered),
        "measurements": [export_measurement(item) for item in ordered],
    }


def export_snapshot(
    snapshot: GeothermalSnapshot,
    *,
    export_id: str,
) -> dict[str, Any]:
    """Return a JSON-safe current-state snapshot export."""

    return {
        "schema": "geopilot.snapshot_export",
        "schema_version": EXPORT_SCHEMA_VERSION,
        "export_id": export_id,
        "snapshot": _json_safe(snapshot),
    }


def _measurement_sort_key(measurement: Measurement) -> tuple[datetime, datetime, str]:
    return (measurement.observed_at, measurement.received_at, measurement.id)


def _json_safe(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value

    if isinstance(value, datetime):
        if value.tzinfo is UTC or value.utcoffset() == UTC.utcoffset(value):
            return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
        return value.isoformat()

    if isinstance(value, tuple | list):
        return [_json_safe(item) for item in value]

    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}

    if hasattr(value, "to_dict"):
        return _json_safe(value.to_dict())

    return value
