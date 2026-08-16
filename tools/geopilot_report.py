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

    # the loop delta, day by day, only while the compressor was running
    python3 tools/geopilot_report.py --database db.sqlite3 \
        --sensor sensor_loop_in --minus sensor_loop_out \
        --while sensor_compressor --bucket 1d

    # the same, but only while it was off: the loop settling back
    python3 tools/geopilot_report.py --database db.sqlite3 \
        --sensor sensor_loop_in --minus sensor_loop_out \
        --while-not sensor_compressor --bucket 1d

    # how many times did it start today, and how long did each cycle last?
    python3 tools/geopilot_report.py --database db.sqlite3 \
        --sensor sensor_compressor --runs --sense on --bucket 1d

    # what was the loop doing in the 20 minutes before each lockout?
    python3 tools/geopilot_report.py --database db.sqlite3 \
        --sensor sensor_loop_out --minus sensor_loop_in \
        --events sensor_lockout --sense on --before 20m

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
    DEFAULT_APPROACH,
    DEFAULT_PAIRING_TOLERANCE,
    DEFAULT_RUN_BREAK,
    Bucket,
    DeltaSummary,
    ReportingError,
    RunSummary,
    SensorSummary,
    approaches,
    bucketed,
    bucketed_delta,
    bucketed_runs,
    coverage,
    delta,
    duty_cycle,
    open_readonly,
    pooled_mean,
    runs,
    summarize,
    summarize_runs,
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
    sense = parser.add_mutually_exclusive_group()
    sense.add_argument(
        "--while",
        dest="while_asserted",
        metavar="STATE_SENSOR",
        help="keep only the moments this state sensor read 1, for example a compressor call",
    )
    sense.add_argument(
        "--while-not",
        dest="while_not_asserted",
        metavar="STATE_SENSOR",
        help="keep only the moments this state sensor read 0, for example a loop recovering",
    )
    parser.add_argument(
        "--runs",
        action="store_true",
        help="split --sensor into unbroken stretches instead of averaging it",
    )
    parser.add_argument(
        "--sense",
        choices=("on", "off", "both"),
        help="which runs to use; default both for --runs, on for --events",
    )
    parser.add_argument(
        "--events",
        metavar="STATE_SENSOR",
        help="report what --sensor was doing around each run boundary of this signal",
    )
    parser.add_argument(
        "--edge",
        choices=("start", "end"),
        default="start",
        help="anchor each event to the start of a run, the default, or to its end",
    )
    parser.add_argument(
        "--before",
        help="how far back an event window reaches, default 15m",
    )
    parser.add_argument(
        "--after",
        help="how far past the event it reaches, default 0s",
    )
    parser.add_argument(
        "--max-gap",
        dest="max_gap",
        help=(
            "a hole longer than this ends a run rather than being assumed to have "
            "held, default 5m"
        ),
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


def describe_gate(while_asserted: str | None, while_not_asserted: str | None) -> str:
    """Name the gate in words, or return an empty string when there is none.

    The sense has to appear everywhere the gate does. A reader who sees only
    "sensor_compressor" beside a number has no way to tell whether they are
    looking at the loop working or the loop recovering.
    """

    if while_asserted:
        return f"{while_asserted} asserted"
    if while_not_asserted:
        return f"{while_not_asserted} not asserted"
    return ""


def _during(gate: str) -> str:
    return f" while {gate}" if gate else ""


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
        max_gap = parse_interval(arguments.max_gap) if arguments.max_gap else DEFAULT_RUN_BREAK
        before = parse_interval(arguments.before) if arguments.before else DEFAULT_APPROACH
        after = parse_interval(arguments.after) if arguments.after else timedelta(0)
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_USAGE

    if arguments.runs and arguments.events:
        print(
            "error: --runs measures a signal's own cycles, --events measures another "
            "sensor around them; ask for one",
            file=sys.stderr,
        )
        return EXIT_USAGE

    if arguments.events:
        if not arguments.sensor:
            print(
                "error: --events needs --sensor; an event window has to measure something",
                file=sys.stderr,
            )
            return EXIT_USAGE
        if arguments.while_asserted or arguments.while_not_asserted or interval is not None:
            print(
                "error: --events does not combine with --while or --bucket; its windows "
                "are the events themselves",
                file=sys.stderr,
            )
            return EXIT_USAGE
        if arguments.sense == "both":
            print(
                "error: --events needs --sense on or --sense off; an event is one edge of "
                "one sense",
                file=sys.stderr,
            )
            return EXIT_USAGE

    if arguments.runs:
        if not arguments.sensor:
            print("error: --runs needs --sensor; runs belong to one signal", file=sys.stderr)
            return EXIT_USAGE
        if arguments.minus or arguments.while_asserted or arguments.while_not_asserted:
            print(
                "error: --runs describes one state sensor on its own; it does not combine "
                "with --minus or --while",
                file=sys.stderr,
            )
            return EXIT_USAGE
        if interval is not None and (arguments.sense or "both") == "both":
            print(
                "error: --runs --bucket needs --sense on or --sense off; one table cannot "
                "hold two series",
                file=sys.stderr,
            )
            return EXIT_USAGE

    if interval is not None and not arguments.sensor:
        print("error: --bucket needs --sensor; buckets are per sensor", file=sys.stderr)
        return EXIT_USAGE

    if arguments.minus and not arguments.sensor:
        print("error: --minus needs --sensor; a delta has two ends", file=sys.stderr)
        return EXIT_USAGE

    gate = describe_gate(arguments.while_asserted, arguments.while_not_asserted)
    if gate and not arguments.sensor:
        print("error: --while needs --sensor; coverage is never gated", file=sys.stderr)
        return EXIT_USAGE

    try:
        connection = open_readonly(arguments.database)
    except ReportingError as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_USAGE

    try:
        if arguments.events:
            return _report_approaches(
                connection,
                arguments.sensor,
                events=arguments.events,
                minus=arguments.minus,
                event_asserted=(arguments.sense or "on") == "on",
                edge=arguments.edge,
                before=before,
                after=after,
                tolerance=tolerance,
                max_gap=max_gap,
                start=start,
                end=end,
            )
        if arguments.runs:
            return _report_runs(
                connection,
                arguments.sensor,
                sense=arguments.sense or "both",
                interval=interval,
                max_gap=max_gap,
                start=start,
                end=end,
                local=not arguments.utc,
                as_csv=arguments.csv,
            )
        if interval is not None:
            return _report_buckets(
                connection,
                arguments.sensor,
                minus=arguments.minus,
                interval=interval,
                while_asserted=arguments.while_asserted,
                while_not_asserted=arguments.while_not_asserted,
                gate=gate,
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
                while_asserted=arguments.while_asserted,
                while_not_asserted=arguments.while_not_asserted,
                gate=gate,
                tolerance=tolerance,
                start=start,
                end=end,
            )
        if arguments.sensor:
            return _report_sensor(
                connection,
                arguments.sensor,
                start,
                end,
                while_asserted=arguments.while_asserted,
                while_not_asserted=arguments.while_not_asserted,
                gate=gate,
                tolerance=tolerance,
            )
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
    *,
    while_asserted: str | None = None,
    while_not_asserted: str | None = None,
    gate: str = "",
    tolerance: timedelta = DEFAULT_PAIRING_TOLERANCE,
) -> int:
    summary = summarize(
        connection,
        sensor_id,
        while_asserted=while_asserted,
        while_not_asserted=while_not_asserted,
        tolerance=tolerance,
        start=start,
        end=end,
    )
    if summary is None:
        print(f"no measurements for {sensor_id}{_during(gate)} in that window")
        return EXIT_NO_DATA

    print(f"sensor : {summary.sensor_id}")
    if gate:
        print(f"while  : {gate}")
    print(f"unit   : {summary.unit}")
    print(f"count  : {summary.count:,}")
    print(f"min    : {summary.minimum:g}")
    print(f"max    : {summary.maximum:g}")
    print(f"mean   : {summary.mean:g}")
    if summary.excluded:
        print(f"\nexcluded: {summary.excluded:,} readings taken outside that condition")

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
    while_asserted: str | None,
    while_not_asserted: str | None,
    gate: str,
    tolerance: timedelta,
    start: datetime | None,
    end: datetime | None,
) -> int:
    summary = delta(
        connection,
        sensor_id,
        minus=minus,
        while_asserted=while_asserted,
        while_not_asserted=while_not_asserted,
        tolerance=tolerance,
        start=start,
        end=end,
    )
    if summary is None:
        print(f"no paired readings of {sensor_id} and {minus}{_during(gate)} in that window")
        return EXIT_NO_DATA

    print(f"delta  : {summary.sensor_id} minus {summary.minus}")
    if gate:
        print(f"while  : {gate}")
    print(f"unit   : {summary.unit}")
    print(f"pairs  : {summary.count:,}")
    print(f"min    : {summary.minimum:g}")
    print(f"max    : {summary.maximum:g}")
    print(f"mean   : {summary.mean:g}")

    if summary.excluded:
        print(f"\nexcluded: {summary.excluded:,} pairs taken outside that condition")
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
    while_asserted: str | None,
    while_not_asserted: str | None,
    gate: str,
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
            while_asserted=while_asserted,
            while_not_asserted=while_not_asserted,
            tolerance=tolerance,
            start=start,
            end=end,
            local=local,
        )
    else:
        buckets = bucketed(
            connection,
            sensor_id,
            interval=interval,
            while_asserted=while_asserted,
            while_not_asserted=while_not_asserted,
            tolerance=tolerance,
            start=start,
            end=end,
            local=local,
        )

    if not buckets:
        subject = f"{sensor_id} and {minus}" if minus else sensor_id
        print(f"no measurements for {subject}{_during(gate)} in that window")
        return EXIT_NO_DATA

    return _print_buckets(buckets, as_csv=as_csv)


def _print_buckets(
    buckets: Sequence[Bucket], *, as_csv: bool, footnote: str = ""
) -> int:
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
    if footnote:
        print(footnote)
    return EXIT_OK


def _report_runs(
    connection: sqlite3.Connection,
    sensor_id: str,
    *,
    sense: str,
    interval: timedelta | None,
    max_gap: timedelta,
    start: datetime | None,
    end: datetime | None,
    local: bool,
    as_csv: bool,
) -> int:
    if interval is not None:
        buckets = bucketed_runs(
            connection,
            sensor_id,
            asserted=sense == "on",
            interval=interval,
            max_gap=max_gap,
            start=start,
            end=end,
            local=local,
        )
        if not buckets:
            print(f"no {_sense_words(sense == 'on')} runs of {sensor_id} in that window")
            return EXIT_NO_DATA
        return _print_buckets(
            buckets,
            as_csv=as_csv,
            footnote="count is how many runs started; min, max and mean are seconds",
        )

    senses = (True, False) if sense == "both" else (sense == "on",)
    reported = 0
    for asserted in senses:
        summary = summarize_runs(
            connection,
            sensor_id,
            asserted=asserted,
            max_gap=max_gap,
            start=start,
            end=end,
        )
        if summary is None:
            print(f"no {_sense_words(asserted)} runs of {sensor_id} in that window\n")
            continue
        _print_run_summary(summary)
        reported += 1

    return EXIT_OK if reported else EXIT_NO_DATA


def _print_run_summary(summary: RunSummary) -> None:
    print(f"runs   : {summary.sensor_id} {_sense_words(summary.asserted)}")
    print(f"count  : {summary.count:,}")
    print(f"shortest: {format_duration(summary.shortest)}")
    print(f"longest : {format_duration(summary.longest)}")
    print(f"mean    : {format_duration(summary.mean)}")
    print(f"total   : {format_duration(summary.total)}")
    if summary.truncated:
        print(
            f"\n{summary.truncated:,} of these were cut by the window edge or a recording "
            "gap; their durations are lower bounds"
        )
    print()


def _sense_words(asserted: bool) -> str:
    return "asserted" if asserted else "idle"


def _report_approaches(
    connection: sqlite3.Connection,
    sensor_id: str,
    *,
    events: str,
    minus: str | None,
    event_asserted: bool,
    edge: str,
    before: timedelta,
    after: timedelta,
    tolerance: timedelta,
    max_gap: timedelta,
    start: datetime | None,
    end: datetime | None,
) -> int:
    found = approaches(
        connection,
        sensor_id,
        events=events,
        event_asserted=event_asserted,
        edge=edge,
        before=before,
        after=after,
        minus=minus,
        tolerance=tolerance,
        max_gap=max_gap,
        start=start,
        end=end,
    )

    subject = f"{sensor_id} minus {minus}" if minus else sensor_id
    occasions = len(
        runs(connection, events, asserted=event_asserted, max_gap=max_gap, start=start, end=end)
    )

    if not found:
        print(f"no readings of {subject} around any {events} event in that window")
        return EXIT_NO_DATA

    print(f"subject: {subject}")
    print(f"events : {_sense_words(event_asserted)} runs of {events}, at their {edge}")
    print(f"window : {format_duration(before)} before to {format_duration(after)} after\n")

    print(f"{'event at':26s} {'count':>7s} {'min':>10s} {'max':>10s} {'mean':>10s}")
    for approach in found:
        print(
            f"{approach.event_at.isoformat():26s} {approach.count:>7,} "
            f"{approach.minimum:>10g} {approach.maximum:>10g} {approach.mean:>10.4g}"
        )

    pooled = pooled_mean(found)
    baseline = _baseline(connection, sensor_id, minus, tolerance, start, end)
    if pooled is not None:
        print(f"\npooled mean around these events: {pooled:.4g}")
    if baseline is not None:
        print(f"mean over the whole window:       {baseline:.4g}")
        print("(the baseline includes these windows, so any contrast is understated)")

    if len(found) < occasions:
        print(f"\n{occasions - len(found):,} of {occasions:,} events had no reading in range")

    print("\nthis describes what happened around the events; it does not say why")
    return EXIT_OK


def _baseline(
    connection: sqlite3.Connection,
    sensor_id: str,
    minus: str | None,
    tolerance: timedelta,
    start: datetime | None,
    end: datetime | None,
) -> float | None:
    """The same measurement over the whole window, for contrast."""

    overall: DeltaSummary | SensorSummary | None
    if minus:
        overall = delta(
            connection, sensor_id, minus=minus, tolerance=tolerance, start=start, end=end
        )
    else:
        overall = summarize(connection, sensor_id, start=start, end=end)
    return overall.mean if overall else None


if __name__ == "__main__":
    sys.exit(main())
