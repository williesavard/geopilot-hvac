#!/usr/bin/env python3
"""Run the GeoPilot simulated geothermal snapshot example."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_SRC = REPO_ROOT / "backend" / "src"
if str(BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC))


def main() -> int:
    from geopilot.scenarios import run_simulated_geothermal_snapshot

    snapshot = run_simulated_geothermal_snapshot()
    print(json.dumps(snapshot.to_dict(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
