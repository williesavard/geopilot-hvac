#!/usr/bin/env python3
"""Report on a recorded GeoPilot database.

Answers the questions a recording exists to answer, without a dashboard.

    # is it still recording, and where are the holes?
    python3 tools/geopilot_report.py --database /var/lib/geopilot/geopilot.sqlite3

    # what did one sensor do over a window?
    python3 tools/geopilot_report.py --database db.sqlite3 \
        --sensor sensor_loop_in --since 2026-01-01

Read-only. It opens the database in read-only mode, so it can run while the
recorder is still writing and cannot damage what it reads.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from geopilot.reporting import (
    ReportingError,
    coverage,
    duty_cycle,
    open_readonly,
    summarize,
)

EXIT_OK = 0
EXIT_USAGE = 1
EXIT_NO_DATA = 2


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""

    parser = argparse.ArgumentParser(
        prog="geopilot_report.py",
        description="Report on a recorded GeoPilot database, read-only.",
    )
    parser.add_argument("--database", required=True, help="path to the SQLite database")
    parser.add_argument("--sensor", help="summarize one sensor instead of reporting coverage")
    parser.add_argument("--since", help="window start, ISO 8601, for example 2026-01-01")
    parser.add_argument("--until", help="window end, ISO 8601, exclusive")
    return parser


def parse_moment(value: str | None, label: str) -> datetime | None:
    """Parse an ISO 8601 moment, assuming UTC when no offset is given."""

    if value is None:
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{label} is not a valid ISO 8601 moment: {value}") from error
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def format_duration(span: timedelta) -> str:
    """Render a duration in units a human reads without arithmetic."""

    seconds = int(span.total_seconds())
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    if seconds < 86400:
        return f"{seconds // 3600}h {(seconds % 3600) // 60}m"
    return f"{seconds // 86400}d {(seconds % 86400) // 3600}h"


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point. Returns a process exit code rather than raising."""

    arguments = build_parser().parse_args(argv)

    try:
        start = parse_moment(arguments.since, "--since")
        end = parse_moment(arguments.until, "--until")
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_USAGE

    try:
        connection = open_readonly(arguments.database)
    except ReportingError as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_USAGE

    try:
        if arguments.sensor:
            return _report_sensor(connection, arguments.sensor, start, end)
        return _report_coverage(connection)
    except ReportingError as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_USAGE
    finally:
        connection.close()


def _report_coverage(connection: sqlite3.Connection) -> int:
    reports = coverage(connection)
    if not reports:
        print("no measurements recorded")
        return EXIT_NO_DATA

    print(f"{'sensor':32s} {'unit':6s} {'count':>9s} {'span':>12s} {'largest gap':>12s}")
    for report in reports:
        print(
            f"{report.sensor_id:32s} {report.unit:6s} {report.count:>9,} "
            f"{format_duration(report.span):>12s} {format_duration(report.largest_gap):>12s}"
        )

    latest = max(report.last_observed_at for report in reports)
    print(f"\nlast observation: {latest.isoformat()}")
    return EXIT_OK


def _report_sensor(
    connection: sqlite3.Connection,
    sensor_id: str,
    start: datetime | None,
    end: datetime | None,
) -> int:
    summary = summarize(connection, sensor_id, start=start, end=end)
    if summary is None:
        print(f"no measurements for {sensor_id} in that window")
        return EXIT_NO_DATA

    print(f"sensor : {summary.sensor_id}")
    print(f"unit   : {summary.unit}")
    print(f"count  : {summary.count:,}")
    print(f"min    : {summary.minimum:g}")
    print(f"max    : {summary.maximum:g}")
    print(f"mean   : {summary.mean:g}")

    if summary.unit == "state":
        ratio = duty_cycle(connection, sensor_id, start=start, end=end)
        if ratio is not None:
            print(f"asserted in {ratio * 100:.1f}% of samples")
            print("(a ratio of samples, not of time; even sampling makes them equal)")

    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
