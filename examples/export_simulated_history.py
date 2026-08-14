#!/usr/bin/env python3
"""Export the GeoPilot simulated in-memory history as deterministic JSON."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_SRC = REPO_ROOT / "backend" / "src"
if str(BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC))


def main() -> int:
    from geopilot.export import export_measurements
    from geopilot.scenarios import (
        run_simulated_geothermal_history,
        simulated_history_query_window,
    )

    history = run_simulated_geothermal_history()
    start, end = simulated_history_query_window()
    measurements = history.historian.query_system(
        history.scenario.hvac_system.id,
        history.scenario.registry,
        start=start,
        end=end,
    )
    payload = export_measurements(
        measurements,
        export_id="simulated_geothermal_history",
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
