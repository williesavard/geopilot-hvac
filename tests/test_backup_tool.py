"""Backup tool tests.

The claim that matters is not "a file appeared". It is that the copy contains
what the source contained, and that the tool says so only after checking.
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from geopilot.control import CommandRecord, CommandStatus
from geopilot.domain import DataQuality, Measurement
from geopilot.sqlite_historian import SqliteMeasurementHistorian
from geopilot.sqlite_journal import SqliteCommandJournal

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from geopilot_backup import (  # noqa: E402
    EXIT_OK,
    EXIT_USAGE,
    EXIT_VERIFY_FAILED,
    backup_one,
    main,
)

NOW = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)


def measurements(path: Path, count: int = 25) -> Path:
    with SqliteMeasurementHistorian(path) as historian:
        for index in range(count):
            moment = NOW + timedelta(minutes=index)
            historian.append(
                Measurement(
                    id=f"s:sensor_loop_in:{index}",
                    sensor_id="sensor_loop_in",
                    observed_at=moment,
                    received_at=moment,
                    value=2.0,
                    unit="degC",
                    quality=DataQuality.GOOD,
                    source_id="source_bus",
                )
            )
    return path


def commands(path: Path, count: int = 3) -> Path:
    with SqliteCommandJournal(path) as journal:
        for index in range(count):
            journal.append(
                CommandRecord(
                    command_id=f"cmd-{index}",
                    target_id="target_zone_1",
                    closed=True,
                    reason="test",
                    status=CommandStatus.APPLIED,
                    detail="",
                    decided_at=NOW + timedelta(minutes=index),
                )
            )
    return path


def test_a_backup_contains_what_the_source_contained(tmp_path: Path) -> None:
    source = measurements(tmp_path / "geopilot.sqlite3")
    destination = tmp_path / "copy.sqlite3"

    before, after = backup_one(source, destination)

    assert before == after == 25


def test_the_backup_is_one_file_with_no_sidecars(tmp_path: Path) -> None:
    """A backup you put on a stick should not have companions that matter."""

    source = measurements(tmp_path / "geopilot.sqlite3")
    destination = tmp_path / "copy.sqlite3"

    backup_one(source, destination)

    assert destination.exists()
    assert not destination.with_name("copy.sqlite3-wal").exists()
    assert not destination.with_name("copy.sqlite3-shm").exists()


def test_a_backup_taken_while_writing_is_still_consistent(tmp_path: Path) -> None:
    """The reason this uses the online API instead of a file copy."""

    source = tmp_path / "geopilot.sqlite3"
    destination = tmp_path / "copy.sqlite3"

    with SqliteMeasurementHistorian(source) as historian:
        for index in range(10):
            moment = NOW + timedelta(minutes=index)
            historian.append(
                Measurement(
                    id=f"s:sensor_loop_in:{index}",
                    sensor_id="sensor_loop_in",
                    observed_at=moment,
                    received_at=moment,
                    value=2.0,
                    unit="degC",
                    quality=DataQuality.GOOD,
                    source_id="source_bus",
                )
            )

        # Still open, WAL not checkpointed, which is exactly when `cp` loses data.
        before, after = backup_one(source, destination)

    assert before == after == 10


def test_both_databases_are_backed_up(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    database = measurements(tmp_path / "geopilot.sqlite3")
    commands(tmp_path / "commands.sqlite3")
    into = tmp_path / "out"
    into.mkdir()

    exit_code = main(
        ["--database", str(database), "--into", str(into), "--stamp", "20260818T120000"]
    )

    output = capsys.readouterr().out
    assert exit_code == EXIT_OK
    assert (into / "geopilot-20260818T120000.sqlite3").exists()
    assert (into / "commands-20260818T120000.sqlite3").exists()
    assert "verified" in output
    assert "not this machine" in output


def test_a_missing_journal_is_skipped_not_failed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """It legitimately does not exist until a command has been issued."""

    database = measurements(tmp_path / "geopilot.sqlite3")
    into = tmp_path / "out"
    into.mkdir()

    exit_code = main(["--database", str(database), "--into", str(into)])

    assert exit_code == EXIT_OK
    assert "skipped commands.sqlite3" in capsys.readouterr().out


def test_a_corrupt_source_fails_loudly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A backup tool that reports success over a broken file is worse than none."""

    broken = tmp_path / "geopilot.sqlite3"
    broken.write_bytes(b"this is not a database")
    into = tmp_path / "out"
    into.mkdir()

    exit_code = main(["--database", str(broken), "--into", str(into)])

    assert exit_code == EXIT_VERIFY_FAILED
    assert "FAILED" in capsys.readouterr().err


def test_nothing_to_back_up_is_a_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    into = tmp_path / "out"
    into.mkdir()

    exit_code = main(["--database", str(tmp_path / "absent.sqlite3"), "--into", str(into)])

    assert exit_code == EXIT_USAGE
    assert "nothing to back up" in capsys.readouterr().err


def test_a_destination_that_is_not_a_directory_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    database = measurements(tmp_path / "geopilot.sqlite3")

    exit_code = main(["--database", str(database), "--into", str(database)])

    assert exit_code == EXIT_USAGE
    assert "not a directory" in capsys.readouterr().err


def test_a_source_must_be_named_exactly_once(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for arguments in ([], ["--config", "x.toml", "--database", "y.sqlite3"]):
        exit_code = main([*arguments, "--into", str(tmp_path)])
        assert exit_code == EXIT_USAGE
        assert "--config or --database" in capsys.readouterr().err


def test_the_journal_can_back_itself_up(tmp_path: Path) -> None:
    """Same online API as the historian, for the same reason."""

    source = tmp_path / "commands.sqlite3"
    destination = tmp_path / "copy.sqlite3"

    with SqliteCommandJournal(source) as journal:
        journal.append(
            CommandRecord(
                command_id="cmd-1",
                target_id="target_zone_1",
                closed=True,
                reason="test",
                status=CommandStatus.APPLIED,
                detail="",
                decided_at=NOW,
            )
        )
        journal.backup(destination)

    with SqliteCommandJournal(destination) as restored:
        assert restored.count() == 1
        assert restored.records[0].command_id == "cmd-1"


def test_the_backup_of_a_journal_is_readable_as_a_journal(tmp_path: Path) -> None:
    """Not just bytes: it opens with the schema version the code expects."""

    commands(tmp_path / "commands.sqlite3", count=4)
    destination = tmp_path / "copy.sqlite3"
    backup_one(tmp_path / "commands.sqlite3", destination)

    connection = sqlite3.connect(destination)
    try:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
    finally:
        connection.close()

    with SqliteCommandJournal(destination) as restored:
        assert restored.count() == 4
