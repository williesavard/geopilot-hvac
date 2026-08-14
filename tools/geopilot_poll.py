#!/usr/bin/env python3
"""Record an installation, once or continuously.

This is the command that turns GeoPilot into something that runs. It reads an
installation configuration, opens the configured serial transports and database,
and executes acquisition cycles.

Two modes, per ``docs/CONTINUOUS_ACQUISITION_ADR.md``:

    # one shot, for a systemd timer or cron entry
    python3 tools/geopilot_poll.py --config installation.toml --once

    # interval loop, for bench work and sub-minute resolution
    python3 tools/geopilot_poll.py --config installation.toml --interval 30

It reads registers. It never writes one. It requires the optional ``modbus``
extra to reach real hardware.
"""

from __future__ import annotations

import argparse
import signal
import sys
from collections.abc import Sequence
from types import FrameType

from geopilot.configuration import ConfigurationError, load_configuration
from geopilot.runtime import AcquisitionSession, CycleOutcome, run_cycles, summarize

EXIT_OK = 0
EXIT_USAGE = 1
EXIT_FAILED_CYCLES = 2

_interrupted = False


def _handle_signal(_signum: int, _frame: FrameType | None) -> None:
    global _interrupted
    _interrupted = True


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""

    parser = argparse.ArgumentParser(
        prog="geopilot_poll.py",
        description="Record an installation described by a TOML configuration.",
    )
    parser.add_argument("--config", required=True, help="path to the installation TOML file")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--once",
        action="store_true",
        help="run a single cycle and exit, for a systemd timer or cron",
    )
    mode.add_argument(
        "--interval",
        type=float,
        help="seconds between cycles, runs until interrupted",
    )
    parser.add_argument(
        "--cycles",
        type=int,
        help="stop after this many cycles, for bench work",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="report only the final summary",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point. Returns a process exit code rather than raising."""

    arguments = build_parser().parse_args(argv)

    if arguments.interval is not None and arguments.interval < 0:
        print("error: --interval must not be negative", file=sys.stderr)
        return EXIT_USAGE
    if arguments.cycles is not None and arguments.cycles < 1:
        print("error: --cycles must be at least 1", file=sys.stderr)
        return EXIT_USAGE

    try:
        config = load_configuration(arguments.config)
    except ConfigurationError as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_USAGE

    cycles = 1 if arguments.once else arguments.cycles
    interval = 0.0 if arguments.once else float(arguments.interval or 0)

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    def report(index: int, outcome: CycleOutcome) -> None:
        if arguments.quiet:
            return
        if outcome.report is not None:
            print(
                f"cycle {index}: {outcome.report.success_count} stored, "
                f"{outcome.report.failure_count} failed"
            )
        else:
            print(f"cycle {index}: ERROR {outcome.error}", file=sys.stderr)

    try:
        with AcquisitionSession(config) as session:
            outcomes = run_cycles(
                session,
                cycles=cycles,
                interval_seconds=interval,
                on_cycle=report,
                should_stop=lambda: _interrupted,
            )
    except Exception as error:  # noqa: BLE001 - report rather than traceback
        print(f"error: {type(error).__name__}: {error}", file=sys.stderr)
        return EXIT_FAILED_CYCLES

    print(summarize(outcomes))
    failed = sum(1 for outcome in outcomes if not outcome.succeeded)
    return EXIT_FAILED_CYCLES if failed else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
