#!/usr/bin/env python3
"""Back up everything GeoPilot cannot regenerate, and check that it worked.

    python3 tools/geopilot_backup.py --config config/installation.toml \
        --into /media/backup

Two databases matter and they are not interchangeable:

- **the measurements.** A year of them cannot be re-created. Losing a week of
  winter is losing a week of the evidence the recording exists to produce;
- **the command journal.** Its whole purpose is to still exist after something
  went wrong, which makes "it was only on the SD card" an odd place to keep it.

SD cards fail, and a Raspberry Pi writing every minute for a winter is a fair
test of one. This is the thing that should be in a cron job before the first
cold night.

**It uses SQLite's online backup API, not a file copy.** Under WAL journalling
a `cp` of a live database produces a file that opens and is missing whatever was
in the write-ahead log — see docs/BACKUP_AND_RESTORE.md, where that is
demonstrated rather than asserted.

**And it verifies.** A backup nobody has opened is a hope. Every copy is
reopened and its rows counted against the source before this reports success.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from geopilot.configuration import ConfigurationError, load_configuration

EXIT_OK = 0
EXIT_USAGE = 1
EXIT_VERIFY_FAILED = 2


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""

    parser = argparse.ArgumentParser(
        prog="geopilot_backup.py",
        description="Back up the GeoPilot databases and verify the copies.",
    )
    parser.add_argument("--config", help="installation TOML; supplies the database path")
    parser.add_argument("--database", help="measurements database, if not using --config")
    parser.add_argument(
        "--journal",
        help="command journal; defaults to commands.sqlite3 beside the measurements",
    )
    parser.add_argument("--into", required=True, help="directory to write the backups into")
    parser.add_argument(
        "--stamp",
        help="timestamp for the file names, ISO 8601; defaults to now",
    )
    return parser


def backup_one(source: Path, destination: Path) -> tuple[int, int]:
    """Copy one database and count its rows before and after.

    Returns (source rows, backup rows). Counting every table rather than a
    known one keeps this working when a schema gains a table, and keeps it
    honest about what it verified.
    """

    origin = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    try:
        target = sqlite3.connect(str(destination))
        try:
            origin.backup(target)
            # The copy inherits WAL journalling, which means it is three files.
            # A backup should be one file you can put on a stick without
            # wondering which of its companions matter — so the copy is
            # switched out of WAL, which checkpoints and removes the sidecars.
            target.execute("PRAGMA journal_mode=DELETE")
        finally:
            target.close()
        before = _total_rows(origin)
    finally:
        origin.close()

    copy = sqlite3.connect(f"file:{destination}?mode=ro", uri=True)
    try:
        after = _total_rows(copy)
    finally:
        copy.close()

    return before, after


def _total_rows(connection: sqlite3.Connection) -> int:
    tables = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    total = 0
    for (name,) in tables:
        # The table name comes from sqlite_master, not from user input, and
        # cannot be parameterised in a FROM clause.
        row = connection.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()
        total += int(row[0])
    return total


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point. Returns a process exit code rather than raising."""

    arguments = build_parser().parse_args(argv)

    if bool(arguments.config) == bool(arguments.database):
        print("error: give either --config or --database, not both", file=sys.stderr)
        return EXIT_USAGE

    if arguments.config:
        try:
            database = Path(load_configuration(Path(arguments.config)).database)
        except ConfigurationError as error:
            print(f"error: {error}", file=sys.stderr)
            return EXIT_USAGE
    else:
        database = Path(arguments.database)

    journal = (
        Path(arguments.journal)
        if arguments.journal
        else database.with_name("commands.sqlite3")
    )

    into = Path(arguments.into)
    if not into.is_dir():
        print(f"error: {into} is not a directory", file=sys.stderr)
        return EXIT_USAGE

    stamp = arguments.stamp or datetime.now(UTC).astimezone().strftime("%Y%m%dT%H%M%S")

    failures = 0
    copied = 0
    for source in (database, journal):
        if not source.exists():
            # The journal legitimately does not exist until a command is issued.
            print(f"skipped {source.name}: not present")
            continue

        destination = into / f"{source.stem}-{stamp}{source.suffix}"
        try:
            before, after = backup_one(source, destination)
        except sqlite3.Error as error:
            print(f"FAILED {source.name}: {error}", file=sys.stderr)
            failures += 1
            continue

        size = destination.stat().st_size
        sidecars = [
            companion
            for companion in (
                destination.with_name(destination.name + suffix)
                for suffix in ("-wal", "-shm")
            )
            if companion.exists()
        ]
        verdict = "verified" if before == after else f"MISMATCH {before} vs {after}"
        print(
            f"{source.name} -> {destination.name}  "
            f"{before:,} rows, {size / 1024:,.0f} kB, {verdict}"
        )
        if sidecars:
            print(
                f"  WARNING: {destination.name} still has "
                f"{', '.join(item.suffix for item in sidecars)}; copy them too",
                file=sys.stderr,
            )
        if before != after:
            failures += 1
        copied += 1

    # Failures are reported before the empty case. A corrupt database copies
    # nothing, and calling that "nothing to back up" would tell a cron job it
    # was invoked wrongly when in fact the data is broken.
    if failures:
        print(
            f"\n{failures} backup(s) failed or did not verify. Do not trust them.",
            file=sys.stderr,
        )
        return EXIT_VERIFY_FAILED

    if not copied:
        print("nothing to back up", file=sys.stderr)
        return EXIT_USAGE

    print("\nEvery copy was reopened and its rows counted against the source.")
    print("Now put one somewhere that is not this machine.")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
