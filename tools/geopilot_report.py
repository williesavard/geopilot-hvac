#!/usr/bin/env python3
"""Report on a recorded GeoPilot database.

Answers the questions a recording exists to answer, without a dashboard.

    # is it still recording, and where are the holes?
    python3 tools/geopilot_report.py --database /var/lib/geopilot/geopilot.sqlite3

    # what did one sensor do over a window?
    python3 tools/geopilot_report.py --database db.sqlite3 \
        --sensor sensor_loop_in --since 2026-01-01

    # the curve: hourly averages, as CSV for plotting
    python3 tools/geopilot_report.py --database db.sqlite3 \
        --sensor sensor_loop_in --bucket 1h --csv > loop.csv

    # the loop delta, day by day
    python3 tools/geopilot_report.py --database db.sqlite3 \
        --sensor sensor_loop_in --minus sensor_loop_out --bucket 1d

Read-only. It opens the database in read-only mode, so it can run while the
recorder is still writing and cannot damage what it reads.
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from geopilot.reporting import (
    DEFAULT_PAIRING_TOLERANCE,
    ReportingError,
    bucketed,
    bucketed_delta,
    coverage,
    delta,
    duty_cycle,
    open_readonly,
    summarize,
)

EXIT_OK = 0
EXIT_USAGE = 1
EXIT_NO_DATA = 2

INTERVAL_UNITS = {
    "s": timedelta(seconds=1),
    "m": timedelta(minutes=1),
    "h": timedelta(hours=1),
    "d": timedelta(days=1),
}


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
    parser.add_argument(
        "--bucket",
        help="aggregate into intervals, for example 15m, 1h or 1d; requires --sensor",
    )
    parser.add_argument(
        "--utc",
        action="store_true",
        help="align buckets to UTC instead of the wall clock where readings were taken",
    )
    parser.add_argument(
        "--minus",
        help="report --sensor minus this sensor, pairing readings taken together",
    )
    parser.add_argument(
        "--tolerance",
        help=(
            "how far apart two readings may be and still be paired, default 30s; "
            "keep it under half the polling interval"
        ),
    )
    parser.add_argument(
        "--csv",
        action="store_true",
        help="write buckets as CSV, for plotting; ignored without --bucket",
    )
    return parser


def parse_interval(value: str) -> timedelta:
    """Parse a bucket interval such as `15m`, `1h` or `1d`.

    A bare number is refused. `--bucket 60` could mean a minute or an hour, and
    guessing wrong would silently produce a chart at the wrong resolution.
    """

    suffix = value[-1:]
    if suffix not in INTERVAL_UNITS:
        raise ValueError(
            f"--bucket needs a unit, one of {', '.join(sorted(INTERVAL_UNITS))}: {value}"
        )
    try:
        quantity = int(value[:-1])
    except ValueError as error:
        raise ValueError(f"--bucket is not a whole number of {suffix}: {value}") from error
    return quantity * INTERVAL_UNITS[suffix]


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
        interval = parse_interval(arguments.bucket) if arguments.bucket else None
        tolerance = (
            parse_interval(arguments.tolerance)
            if arguments.tolerance
            else DEFAULT_PAIRING_TOLERANCE
        )
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_USAGE

    if interval is not None and not arguments.sensor:
        print("error: --bucket needs --sensor; buckets are per sensor", file=sys.stderr)
        return EXIT_USAGE

    if arguments.minus and not arguments.sensor:
        print("error: --minus needs --sensor; a delta has two ends", file=sys.stderr)
        return EXIT_USAGE

    try:
        connection = open_readonly(arguments.database)
    except ReportingError as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_USAGE

    try:
        if interval is not None:
            return _report_buckets(
                connection,
                arguments.sensor,
                minus=arguments.minus,
                interval=interval,
                tolerance=tolerance,
                start=start,
                end=end,
                local=not arguments.utc,
                as_csv=arguments.csv,
            )
        if arguments.minus:
            return _report_delta(
                connection,
                arguments.sensor,
                minus=arguments.minus,
                tolerance=tolerance,
                start=start,
                end=end,
            )
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


def _report_delta(
    connection: sqlite3.Connection,
    sensor_id: str,
    *,
    minus: str,
    tolerance: timedelta,
    start: datetime | None,
    end: datetime | None,
) -> int:
    summary = delta(
        connection, sensor_id, minus=minus, tolerance=tolerance, start=start, end=end
    )
    if summary is None:
        print(f"no paired readings of {sensor_id} and {minus} in that window")
        return EXIT_NO_DATA

    print(f"delta  : {summary.sensor_id} minus {summary.minus}")
    print(f"unit   : {summary.unit}")
    print(f"pairs  : {summary.count:,}")
    print(f"min    : {summary.minimum:g}")
    print(f"max    : {summary.maximum:g}")
    print(f"mean   : {summary.mean:g}")

    if summary.unpaired or summary.unpaired_minus:
        print(
            f"\nunpaired: {summary.unpaired:,} of {summary.sensor_id}, "
            f"{summary.unpaired_minus:,} of {summary.minus}"
        )
        print("(a delta from few pairs describes few moments; widen --tolerance or check the bus)")

    return EXIT_OK


def _report_buckets(
    connection: sqlite3.Connection,
    sensor_id: str,
    *,
    minus: str | None,
    interval: timedelta,
    tolerance: timedelta,
    start: datetime | None,
    end: datetime | None,
    local: bool,
    as_csv: bool,
) -> int:
    if minus:
        buckets = bucketed_delta(
            connection,
            sensor_id,
            minus=minus,
            interval=interval,
            tolerance=tolerance,
            start=start,
            end=end,
            local=local,
        )
    else:
        buckets = bucketed(
            connection, sensor_id, interval=interval, start=start, end=end, local=local
        )

    if not buckets:
        subject = f"{sensor_id} and {minus}" if minus else sensor_id
        print(f"no measurements for {subject} in that window")
        return EXIT_NO_DATA

    if as_csv:
        writer = csv.writer(sys.stdout)
        writer.writerow(("starts_at", "count", "min", "max", "mean"))
        for bucket in buckets:
            writer.writerow(
                (
                    bucket.starts_at.isoformat(),
                    bucket.count,
                    bucket.minimum,
                    bucket.maximum,
                    bucket.mean,
                )
            )
        return EXIT_OK

    print(f"{'starts at':26s} {'count':>7s} {'min':>10s} {'max':>10s} {'mean':>10s}")
    for bucket in buckets:
        print(
            f"{bucket.starts_at.isoformat():26s} {bucket.count:>7,} "
            f"{bucket.minimum:>10g} {bucket.maximum:>10g} {bucket.mean:>10.4g}"
        )
    print(f"\n{len(buckets):,} intervals; an absent interval is a gap, not a zero")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
