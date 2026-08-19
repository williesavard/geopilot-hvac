#!/usr/bin/env python3
"""Assemble the evidence package an engineer receives.

    python3 tools/geopilot_dossier.py \
        --database /var/lib/geopilot/geopilot.sqlite3 \
        --into ~/dossier-2027-05 \
        --since 2026-10-01 --until 2027-05-01 \
        --delta sensor_loop_in:sensor_loop_out \
        --prepared-for "Hubert Langevin, ing."

Everything else in GeoPilot serves the person operating it. This serves the
person who has to **stamp a recommendation** — and that is a different job, with
a different requirement: not "show me the numbers" but "show me what the numbers
are worth".

So the centrepiece of the output is not the CSVs. It is `README.md`, which says
what was measured, with what, calibrated how, with which holes, and — at
length — **what this data cannot tell you**. A dossier that omits its own limits
is worse than no dossier, because it invites a conclusion it cannot support.

It reads the database, not the configuration. The dossier therefore contains
sensor ids, readings and calibration history, and **no address, no equipment
serial numbers and nothing from the private site notes**. That is deliberate: a
deliverable is a thing that gets forwarded. What it needs beyond that is added
by hand, by somebody who has decided to add it.

Read-only, and safe to run while the recorder is still writing.
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

from geopilot.provenance import compare
from geopilot.reporting import (
    Bucket,
    ReportingError,
    SensorCoverage,
    bucketed,
    bucketed_delta,
    coverage,
    delta,
    open_readonly,
)
from geopilot.sqlite_provenance import (
    ConfigurationEpoch,
    ProvenanceStorageError,
    SqliteProvenanceJournal,
    provenance_path,
)

EXIT_OK = 0
EXIT_USAGE = 1
EXIT_NO_DATA = 2

INTERVAL_UNITS = {"m": timedelta(minutes=1), "h": timedelta(hours=1), "d": timedelta(days=1)}

HEALTHY_GAP = timedelta(hours=1)
"""A gap below this is ordinary. Above it, the reader is told the number."""

SERIOUS_GAP = timedelta(days=1)
"""A gap above this is a hole in the evidence, and is called one."""


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""

    parser = argparse.ArgumentParser(
        prog="geopilot_dossier.py",
        description="Assemble a reviewable evidence package from a recording.",
    )
    parser.add_argument("--database", required=True, help="path to the SQLite database")
    parser.add_argument("--into", required=True, help="directory to create and fill")
    parser.add_argument("--since", help="window start, ISO 8601")
    parser.add_argument("--until", help="window end, ISO 8601, exclusive")
    parser.add_argument(
        "--bucket",
        default="1h",
        help="resolution of the exported series, default 1h; raw readings are not exported",
    )
    parser.add_argument(
        "--delta",
        action="append",
        default=[],
        metavar="SENSOR:MINUS",
        help="also export the difference between two sensors; repeatable",
    )
    parser.add_argument(
        "--prepared-for",
        default="",
        help="who receives this, named on the first page",
    )
    parser.add_argument(
        "--title",
        default="GeoPilot monitoring dossier",
        help="heading for the README",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="write into a directory that already has files in it",
    )
    return parser


def parse_interval(value: str) -> timedelta:
    """Parse `15m`, `1h` or `1d`. A bare number is refused."""

    suffix = value[-1:]
    if suffix not in INTERVAL_UNITS:
        raise ValueError(
            f"--bucket needs a unit, one of {', '.join(sorted(INTERVAL_UNITS))}: {value}"
        )
    try:
        quantity = int(value[:-1])
    except ValueError as error:
        raise ValueError(f"--bucket is not a whole number of {suffix}: {value}") from error
    if quantity < 1:
        raise ValueError(f"--bucket must be positive: {value}")
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


def parse_pair(value: str) -> tuple[str, str]:
    """Parse `sensor:minus`; both ends are required and neither is guessed."""

    sensor_id, separator, minus = value.partition(":")
    if not separator or not sensor_id or not minus:
        raise ValueError(f"--delta needs SENSOR:MINUS, received {value!r}")
    return sensor_id, minus


def format_duration(span: timedelta) -> str:
    """Render a duration the way a person reads one."""

    seconds = int(span.total_seconds())
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        minutes = seconds % 3600 // 60
        return f"{seconds // 3600}h" + (f" {minutes}m" if minutes else "")
    hours = seconds % 86400 // 3600
    return f"{seconds // 86400}d" + (f" {hours}h" if hours else "")


DECIMALS = 6
"""How many decimal places a value is written with.

Subtracting two floats produces things like `2.8000000000000003`, and writing
that into a deliverable claims sixteen significant digits from a probe whose
resolution is 0.0625 °C. Rounding here removes the binary artefact and nothing
else: six places is micro-units in every unit this records, which is orders of
magnitude below any sensor's resolution.

It is applied on the way out, to the report. The stored measurements are
untouched.
"""


def _number(value: float) -> float:
    """Drop the floating-point artefact without touching real precision."""

    return round(value, DECIMALS)


def write_buckets(path: Path, buckets: Sequence[Bucket]) -> None:
    """One series, one file. Columns named so a spreadsheet needs no legend."""

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["starts_at", "count", "min", "max", "mean"])
        for bucket in buckets:
            writer.writerow(
                [
                    bucket.starts_at.isoformat(),
                    bucket.count,
                    _number(bucket.minimum),
                    _number(bucket.maximum),
                    _number(bucket.mean),
                ]
            )


def write_coverage(path: Path, reports: Sequence[SensorCoverage]) -> None:
    """The holes, as data rather than as prose."""

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "sensor_id",
                "unit",
                "count",
                "first_observed_at",
                "last_observed_at",
                "span_seconds",
                "largest_gap_seconds",
            ]
        )
        for report in reports:
            writer.writerow(
                [
                    report.sensor_id,
                    report.unit,
                    report.count,
                    report.first_observed_at.isoformat(),
                    report.last_observed_at.isoformat(),
                    int(report.span.total_seconds()),
                    int(report.largest_gap.total_seconds()),
                ]
            )


def write_provenance(path: Path, epochs: Sequence[ConfigurationEpoch]) -> None:
    """Every correction that was ever in effect, and from when."""

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "in_effect_from",
                "epoch",
                "sensor_id",
                "kind",
                "reference",
                "unit",
                "scale",
                "offset",
                "inverted",
            ]
        )
        for epoch in epochs:
            for entry in epoch.sensors:
                writer.writerow(
                    [
                        epoch.recorded_at.isoformat(),
                        epoch.short_fingerprint,
                        entry.sensor_id,
                        str(entry.kind),
                        entry.reference,
                        entry.unit,
                        entry.scale,
                        entry.offset,
                        int(entry.inverted),
                    ]
                )


def gap_verdict(largest: timedelta) -> str:
    """Say plainly how much a hole matters, rather than printing a number."""

    if largest <= HEALTHY_GAP:
        return "continuous"
    if largest < SERIOUS_GAP:
        return f"interrupted ({format_duration(largest)})"
    return f"**hole of {format_duration(largest)}**"


def render_readme(
    *,
    title: str,
    prepared_for: str,
    generated_at: datetime,
    database: str,
    start: datetime | None,
    end: datetime | None,
    interval: timedelta,
    reports: Sequence[SensorCoverage],
    epochs: Sequence[ConfigurationEpoch],
    series: Sequence[tuple[str, str, int]],
    deltas: Sequence[tuple[str, str, str, int, int]],
) -> str:
    """The method statement.

    Written for somebody who has to decide whether these numbers can carry a
    recommendation, which means the limits are not an appendix. They are the
    part that stops a reader concluding more than the measurement supports.
    """

    lines: list[str] = [f"# {title}", ""]
    if prepared_for:
        lines += [f"**Prepared for:** {prepared_for}"]
    lines += [
        f"**Generated:** {generated_at.isoformat(timespec='seconds')}",
        f"**Source:** `{Path(database).name}`",
        "",
        "This package was produced by GeoPilot, a local-first monitoring system",
        "recording a residential geothermal heat pump. It contains measurements,",
        "the calibration history behind them, and a statement of what they can and",
        "cannot support.",
        "",
        "**Read [Limits](#limits) before drawing a conclusion from any figure here.**",
        "",
        "## Window",
        "",
    ]

    observed_first = min((item.first_observed_at for item in reports), default=None)
    observed_last = max((item.last_observed_at for item in reports), default=None)
    lines += [
        f"- requested: {start.isoformat() if start else 'everything recorded'}"
        f" to {end.isoformat() if end else 'the last reading'}",
        f"- actually recorded: {observed_first.isoformat() if observed_first else 'nothing'}"
        f" to {observed_last.isoformat() if observed_last else 'nothing'}",
        f"- exported at: {format_duration(interval)} resolution",
        "",
        "Raw per-reading data is **not** in this package. Every series here is",
        f"aggregated into {format_duration(interval)} buckets carrying the count, minimum,",
        "maximum and mean of the readings that fell inside. The raw database can be",
        "supplied on request; it is one file.",
        "",
        "## What was measured",
        "",
        "| sensor | unit | readings | recorded from | to | continuity |",
        "| --- | --- | --- | --- | --- | --- |",
    ]

    for report in reports:
        lines.append(
            f"| `{report.sensor_id}` | {report.unit} | {report.count:,} | "
            f"{report.first_observed_at.date()} | {report.last_observed_at.date()} | "
            f"{gap_verdict(report.largest_gap)} |"
        )

    lines += [
        "",
        "`continuity` reports the **largest single gap**, not the total missing time.",
        "A gap means nothing was recorded — it does not mean the value was zero, and",
        "a mean computed across one is a mean of what was seen, not of what happened.",
        "",
        "## How each value was derived",
        "",
    ]

    if not epochs:
        lines += [
            "**No calibration history is available for this recording.** The",
            "provenance journal did not exist when these measurements were taken, so",
            "the corrections applied to them cannot be stated. Treat every figure",
            "here as uncalibrated: comparisons within one sensor remain valid,",
            "comparisons between two sensors do not.",
            "",
        ]
    else:
        latest = epochs[-1]
        lines += [
            "Every stored value has already had a correction applied — a probe",
            "offset, a register scale, a polarity flip. These were in effect at the",
            f"end of the window (epoch `{latest.short_fingerprint}`, from",
            f"{latest.recorded_at.date()}):",
            "",
            "| sensor | derived from | correction |",
            "| --- | --- | --- |",
        ]
        for entry in latest.sensors:
            correction = []
            if entry.scale != 1.0:
                correction.append(f"× {entry.scale:g}")
            if entry.offset:
                correction.append(f"{entry.offset:+g}")
            if entry.inverted:
                correction.append("inverted")
            lines.append(
                f"| `{entry.sensor_id}` | `{entry.reference}` | "
                f"{', '.join(correction) or 'none'} |"
            )
        lines += ["", f"Full history: `provenance.csv` ({len(epochs)} epoch(s))."]

        if len(epochs) > 1:
            lines += [
                "",
                "### Corrections changed during this recording",
                "",
                "**This matters for anything spanning the dates below.** Measurements",
                "on either side of each moment were computed differently, so a step in",
                "the numbers there may be the configuration rather than the equipment.",
                "",
            ]
            for index in range(1, len(epochs)):
                changes = compare(epochs[index - 1].sensors, epochs[index].sensors)
                lines.append(
                    f"- **{epochs[index].recorded_at.isoformat(timespec='minutes')}** "
                    f"(epoch `{epochs[index].short_fingerprint}`)"
                )
                for change in changes:
                    lines.append(f"  - {change.describe()}")

    lines += ["", "## Files", "", "| file | contents |", "| --- | --- |"]
    lines.append("| `coverage.csv` | per sensor: reading count, span, largest gap |")
    lines.append("| `provenance.csv` | every correction ever in effect, and from when |")
    for sensor_id, unit, count in series:
        lines.append(
            f"| `series/{sensor_id}.csv` | {sensor_id} in {unit}, {count:,} buckets |"
        )
    for sensor_id, minus, unit, count, pairs in deltas:
        lines.append(
            f"| `deltas/{sensor_id}-minus-{minus}.csv` | "
            f"{sensor_id} − {minus} in {unit}, {count:,} buckets from {pairs:,} pairs |"
        )

    lines += [
        "",
        "Series columns are `starts_at, count, min, max, mean`. `starts_at` is the",
        "beginning of the interval, not the first reading in it, and `count` is how",
        "many readings the bucket actually held — a bucket with a low count is a",
        "bucket to distrust.",
        "",
        f"Values are written to {DECIMALS} decimal places. That removes the binary",
        "floating-point artefacts a subtraction produces and nothing else — it is",
        "orders of magnitude below the resolution of any sensor here, and the stored",
        "measurements are untouched.",
        "",
        "## Limits",
        "",
        "### The absolute temperatures are worth ±0.5 °C; the differences are worth more",
        "",
        "The probes are DS18B20s, specified to **±0.5 °C absolute**. They were",
        "calibrated in a common bath, which makes them **agree with each other** —",
        "the right target for a difference between two points on one loop, and the",
        "reason a delta here is trustworthy to roughly ±0.1 °C.",
        "",
        "It is not the same as being absolutely right. Nothing here is traceable to",
        "a reference standard. **A loop entering-water temperature quoted from this",
        "data carries ±0.5 °C; a loop delta does not.**",
        "",
        "### There is no flow measurement, so there is no heat transfer",
        "",
        "A temperature difference is not a rate of heat. Without flow, the delta in",
        "this package cannot be converted to kW, and no coefficient of performance",
        "can be computed from it. Any figure of that kind must come from elsewhere.",
        "",
        "### This records the configuration, not the truth",
        "",
        "A probe physically clamped to the return pipe but configured as the supply",
        "is recorded faithfully as the supply. The provenance history establishes",
        "that nothing *in the configuration* changed unnoticed; it cannot establish",
        "that the configuration matched the plumbing. Physical verification is a",
        "site visit, not a file.",
        "",
        "### Gaps are absences, not zeros",
        "",
        "Where a sensor stopped reporting there is no row. Averages, minima and",
        "maxima are computed over what exists. A sensor whose continuity above reads",
        "as a hole should have that hole checked against the question being asked",
        "before its statistics are used.",
        "",
        "### What is deliberately not here",
        "",
        "No address, no equipment serial numbers, no occupancy data and nothing from",
        "the private site notes. This package is derived from the measurement",
        "database alone, so that forwarding it discloses readings and nothing about",
        "a household. Anything further is added by hand.",
        "",
    ]

    return "\n".join(lines) + "\n"


def load_epochs(database: str) -> tuple[ConfigurationEpoch, ...]:
    """The calibration history, or nothing when the recording predates it."""

    location = provenance_path(database)
    if not Path(location).exists():
        return ()
    journal = SqliteProvenanceJournal(location)
    try:
        return journal.epochs()
    except ProvenanceStorageError:
        return ()
    finally:
        journal.close()


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point. Returns a process exit code rather than raising."""

    arguments = build_parser().parse_args(argv)

    try:
        start = parse_moment(arguments.since, "--since")
        end = parse_moment(arguments.until, "--until")
        interval = parse_interval(arguments.bucket)
        pairs = [parse_pair(value) for value in arguments.delta]
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_USAGE

    if start is not None and end is not None and start >= end:
        print("error: --since must come before --until", file=sys.stderr)
        return EXIT_USAGE

    into = Path(arguments.into)
    if into.exists() and any(into.iterdir()) and not arguments.force:
        print(
            f"error: {into} already has files in it; use --force to write anyway",
            file=sys.stderr,
        )
        return EXIT_USAGE

    try:
        connection = open_readonly(arguments.database)
    except ReportingError as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_USAGE

    try:
        reports = coverage(connection)
        if not reports:
            print("error: the database holds no measurements", file=sys.stderr)
            return EXIT_NO_DATA

        into.mkdir(parents=True, exist_ok=True)
        (into / "series").mkdir(exist_ok=True)

        write_coverage(into / "coverage.csv", reports)
        epochs = load_epochs(arguments.database)
        write_provenance(into / "provenance.csv", epochs)

        series = _export_series(connection, into, reports, interval, start, end)
        exported = _export_deltas(connection, into, pairs, interval, start, end)
    except ReportingError as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_USAGE
    finally:
        connection.close()

    (into / "README.md").write_text(
        render_readme(
            title=arguments.title,
            prepared_for=arguments.prepared_for,
            generated_at=datetime.now(UTC).astimezone(),
            database=arguments.database,
            start=start,
            end=end,
            interval=interval,
            reports=reports,
            epochs=epochs,
            series=series,
            deltas=exported,
        ),
        encoding="utf-8",
    )

    print(f"wrote {into}")
    print(f"  {len(series)} series, {len(exported)} delta(s), {len(epochs)} epoch(s)")
    if not epochs:
        print(
            "  NOTE: no calibration history; the README says so plainly",
            file=sys.stderr,
        )
    if len(epochs) > 1:
        print(
            f"  NOTE: corrections changed {len(epochs) - 1} time(s) during this "
            "recording; the README dates each one",
            file=sys.stderr,
        )
    print("  read README.md before sending it")
    return EXIT_OK


def _export_series(
    connection: sqlite3.Connection,
    into: Path,
    reports: Sequence[SensorCoverage],
    interval: timedelta,
    start: datetime | None,
    end: datetime | None,
) -> list[tuple[str, str, int]]:
    """One file per sensor. A sensor with nothing in the window is skipped and
    reported as skipped, rather than written as an empty file somebody has to
    open to understand."""

    exported: list[tuple[str, str, int]] = []
    for report in reports:
        buckets = bucketed(
            connection,
            report.sensor_id,
            interval=interval,
            start=start,
            end=end,
        )
        if not buckets:
            print(f"  skipped {report.sensor_id}: nothing in the window", file=sys.stderr)
            continue
        write_buckets(into / "series" / f"{report.sensor_id}.csv", buckets)
        exported.append((report.sensor_id, report.unit, len(buckets)))
    return exported


def _export_deltas(
    connection: sqlite3.Connection,
    into: Path,
    pairs: Sequence[tuple[str, str]],
    interval: timedelta,
    start: datetime | None,
    end: datetime | None,
) -> list[tuple[str, str, str, int, int]]:
    """Requested differences, with the pair count carried into the README.

    A delta computed from 40 pairs out of 1,440 readings is a different claim
    from one computed from 1,438, so the count travels with the file.
    """

    if not pairs:
        return []

    (into / "deltas").mkdir(exist_ok=True)
    exported: list[tuple[str, str, str, int, int]] = []
    for sensor_id, minus in pairs:
        # The summary decides whether there is anything to export: it is the one
        # that reports None when nothing paired, and it carries the unit and the
        # pair count the README needs.
        summary = delta(connection, sensor_id, minus=minus, start=start, end=end)
        if summary is None:
            print(
                f"  skipped {sensor_id} minus {minus}: no paired readings",
                file=sys.stderr,
            )
            continue

        buckets = bucketed_delta(
            connection,
            sensor_id,
            minus=minus,
            interval=interval,
            start=start,
            end=end,
        )
        write_buckets(into / "deltas" / f"{sensor_id}-minus-{minus}.csv", buckets)
        exported.append((sensor_id, minus, summary.unit, len(buckets), summary.count))
    return exported


if __name__ == "__main__":
    sys.exit(main())
