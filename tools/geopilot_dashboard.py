#!/usr/bin/env python3
"""Render a recorded GeoPilot database as one self-contained HTML page.

    python3 tools/geopilot_dashboard.py \
        --database /var/lib/geopilot/geopilot.sqlite3 \
        --output ~/geopilot.html \
        --delta sensor_loop_in:sensor_loop_out

Open the result in any browser. It carries its own styles, its own script and
its own data, so it works from a USB stick or an email attachment, with no
server and no connection.

Read-only: the database is opened in read-only mode and can be rendered while
the recorder is still writing.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from geopilot.configuration import ConfigurationError, load_configuration
from geopilot.connectivity import ConfiguredSensor, roster_from
from geopilot.dashboard import DeltaPair, render
from geopilot.reporting import ReportingError, open_readonly

EXIT_OK = 0
EXIT_USAGE = 1


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""

    parser = argparse.ArgumentParser(
        prog="geopilot_dashboard.py",
        description="Render a recorded GeoPilot database as one HTML page.",
    )
    parser.add_argument("--database", required=True, help="path to the SQLite database")
    parser.add_argument("--output", required=True, help="path to write the HTML page to")
    parser.add_argument(
        "--delta",
        action="append",
        default=[],
        metavar="SENSOR:MINUS",
        help="chart the difference between two sensors; repeatable",
    )
    parser.add_argument(
        "--while",
        dest="while_asserted",
        metavar="STATE_SENSOR",
        help="restrict the delta charts to the moments this state sensor read 1",
    )
    parser.add_argument(
        "--config",
        help=(
            "installation TOML; supplies the roster, so a sensor that never reported "
            "is shown as never seen instead of being invisible"
        ),
    )
    parser.add_argument("--title", default="GeoPilot", help="heading for the page")
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite the output file if it already exists",
    )
    return parser


def parse_delta(value: str) -> DeltaPair:
    """Parse `sensor:minus`.

    Both ends are required and neither is guessed. Which way round a delta runs
    changes its sign, and a tool that picked for you would be picking wrong half
    the time without saying so.
    """

    sensor_id, separator, minus = value.partition(":")
    if not separator or not sensor_id or not minus:
        raise ValueError(f"--delta needs SENSOR:MINUS, received {value!r}")
    return DeltaPair(sensor_id=sensor_id, minus=minus)


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point. Returns a process exit code rather than raising."""

    arguments = build_parser().parse_args(argv)

    try:
        deltas = tuple(parse_delta(value) for value in arguments.delta)
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_USAGE

    roster: tuple[ConfiguredSensor, ...] = ()
    if arguments.config:
        try:
            roster = roster_from(load_configuration(Path(arguments.config)))
        except ConfigurationError as error:
            print(f"error: {error}", file=sys.stderr)
            return EXIT_USAGE

    output = Path(arguments.output)
    if output.exists() and not arguments.force:
        print(f"error: {output} already exists; pass --force to replace it", file=sys.stderr)
        return EXIT_USAGE

    try:
        connection = open_readonly(arguments.database)
    except ReportingError as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_USAGE

    try:
        page = render(
            connection,
            title=arguments.title,
            deltas=deltas,
            while_asserted=arguments.while_asserted,
            generated_at=datetime.now(UTC).astimezone(),
            roster=roster,
        )
    except ReportingError as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_USAGE
    finally:
        connection.close()

    output.write_text(page, encoding="utf-8")
    print(f"wrote {output} ({len(page.encode('utf-8')) / 1024:.0f} kB)")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
