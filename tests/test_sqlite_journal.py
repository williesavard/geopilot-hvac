"""Persistent command journal tests.

The claim worth proving is the one the in-memory journal could not make: the
record is still there after the process that wrote it is gone.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from geopilot.control import (
    CommandRecord,
    CommandRequest,
    CommandStatus,
    ControlPolicy,
    ControlService,
    ControlTarget,
)
from geopilot.modbus_write import FakeModbusWriteTransport
from geopilot.sqlite_journal import (
    SCHEMA_VERSION,
    JournalStorageError,
    SqliteCommandJournal,
)

NOW = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)


def record(
    command_id: str = "cmd-1",
    *,
    target_id: str = "target_zone_1",
    status: CommandStatus = CommandStatus.APPLIED,
    closed: bool = True,
    detail: str = "",
    decided_at: datetime = NOW,
) -> CommandRecord:
    return CommandRecord(
        command_id=command_id,
        target_id=target_id,
        closed=closed,
        reason="bench test",
        status=status,
        detail=detail,
        decided_at=decided_at,
    )


def test_a_command_survives_reopening_the_database(tmp_path: Path) -> None:
    """The whole point. An audit trail a restart erases is not one."""

    database = tmp_path / "commands.sqlite3"

    with SqliteCommandJournal(database) as journal:
        journal.append(record())

    with SqliteCommandJournal(database) as reopened:
        assert reopened.count() == 1
        stored = reopened.records[0]
        assert stored.command_id == "cmd-1"
        assert stored.reason == "bench test"
        assert stored.status is CommandStatus.APPLIED


def test_refusals_are_stored_exactly_like_successes(tmp_path: Path) -> None:
    """What the system was asked to do is often more interesting than what it did."""

    with SqliteCommandJournal(tmp_path / "j.sqlite3") as journal:
        journal.append(record("a", status=CommandStatus.APPLIED))
        journal.append(record("b", status=CommandStatus.REFUSED, detail="control_disabled"))
        journal.append(record("c", status=CommandStatus.FAILED, detail="no answer"))

        assert journal.count() == 3
        assert [item.status for item in journal.records] == [
            CommandStatus.APPLIED,
            CommandStatus.REFUSED,
            CommandStatus.FAILED,
        ]


def test_the_wall_clock_is_preserved(tmp_path: Path) -> None:
    """An audit record has to be readable by a person in their own time."""

    eastern = timezone(timedelta(hours=-4))
    stamped = datetime(2026, 8, 18, 21, 30, tzinfo=eastern)

    with SqliteCommandJournal(tmp_path / "j.sqlite3") as journal:
        journal.append(record(decided_at=stamped))

        stored = journal.records[0].decided_at
        assert stored == stamped
        assert stored.isoformat() == "2026-08-18T21:30:00-04:00"


def test_re_appending_the_same_command_is_ignored_not_raised(tmp_path: Path) -> None:
    """A retried write of a record already on disk is not a new event."""

    with SqliteCommandJournal(tmp_path / "j.sqlite3") as journal:
        journal.append(record("cmd-1"))
        journal.append(record("cmd-1"))

        assert journal.count() == 1


def test_order_follows_the_write_sequence_not_the_clock(tmp_path: Path) -> None:
    """A host whose clock steps backwards must not reorder history."""

    with SqliteCommandJournal(tmp_path / "j.sqlite3") as journal:
        journal.append(record("first", decided_at=NOW))
        journal.append(record("second", decided_at=NOW - timedelta(hours=1)))

        assert [item.command_id for item in journal.records] == ["first", "second"]


def test_recent_returns_the_newest_but_reads_oldest_first(tmp_path: Path) -> None:
    with SqliteCommandJournal(tmp_path / "j.sqlite3") as journal:
        for index in range(5):
            journal.append(record(f"cmd-{index}"))

        assert [item.command_id for item in journal.recent(limit=2)] == ["cmd-3", "cmd-4"]


def test_a_negative_limit_is_refused(tmp_path: Path) -> None:
    with SqliteCommandJournal(tmp_path / "j.sqlite3") as journal, pytest.raises(
        JournalStorageError, match="cannot be negative"
    ):
        journal.recent(limit=-1)


def test_one_relay_can_be_audited_on_its_own(tmp_path: Path) -> None:
    with SqliteCommandJournal(tmp_path / "j.sqlite3") as journal:
        journal.append(record("a", target_id="target_zone_1"))
        journal.append(record("b", target_id="target_zone_2"))
        journal.append(record("c", target_id="target_zone_1"))

        assert [item.command_id for item in journal.for_target("target_zone_1")] == ["a", "c"]


def test_the_last_application_is_found_ignoring_refusals(tmp_path: Path) -> None:
    """A refused command did not operate anything, so it does not count."""

    with SqliteCommandJournal(tmp_path / "j.sqlite3") as journal:
        journal.append(record("a", status=CommandStatus.APPLIED, decided_at=NOW))
        journal.append(
            record("b", status=CommandStatus.REFUSED, decided_at=NOW + timedelta(minutes=5))
        )

        assert journal.last_applied_at("target_zone_1") == NOW


def test_an_untouched_relay_has_no_last_application(tmp_path: Path) -> None:
    with SqliteCommandJournal(tmp_path / "j.sqlite3") as journal:
        assert journal.last_applied_at("target_absent") is None


def test_the_journal_has_no_way_to_delete_or_rewrite() -> None:
    """Append only, by having no other verb."""

    verbs = {name for name in dir(SqliteCommandJournal) if not name.startswith("_")}

    assert "append" in verbs
    assert not {"delete", "remove", "update", "prune", "clear"} & verbs


def test_the_schema_version_is_recorded(tmp_path: Path) -> None:
    database = tmp_path / "j.sqlite3"
    with SqliteCommandJournal(database):
        pass

    connection = sqlite3.connect(database)
    try:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    finally:
        connection.close()


def test_a_future_schema_is_refused_rather_than_guessed_at(tmp_path: Path) -> None:
    database = tmp_path / "j.sqlite3"
    connection = sqlite3.connect(database)
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    connection.commit()
    connection.close()

    with pytest.raises(JournalStorageError, match="unsupported schema version"):
        SqliteCommandJournal(database)


def test_a_naive_timestamp_is_refused(tmp_path: Path) -> None:
    with SqliteCommandJournal(tmp_path / "j.sqlite3") as journal, pytest.raises(
        JournalStorageError, match="aware datetime"
    ):
        journal.append(record(decided_at=datetime(2026, 8, 18, 12, 0)))


def test_an_invalid_synchronous_mode_is_refused() -> None:
    with pytest.raises(JournalStorageError, match="synchronous must be"):
        SqliteCommandJournal(":memory:", synchronous="SOMETIMES")


def test_the_rate_limit_survives_a_restart(tmp_path: Path) -> None:
    """A rate limit that resets when the process does is not a rate limit."""

    database = tmp_path / "commands.sqlite3"
    target = ControlTarget(
        target_id="target_zone_1",
        unit_id=1,
        address=0,
        minimum_interval_seconds=300,
    )
    policy = ControlPolicy(enabled=True, targets=(target,))

    with SqliteCommandJournal(database) as journal:
        first = ControlService(
            policy, FakeModbusWriteTransport(), journal=journal, clock=lambda: NOW
        )
        applied = first.execute(
            CommandRequest(
                command_id="cmd-1", target_id="target_zone_1", closed=True, reason="first"
            )
        )
        assert applied.status is CommandStatus.APPLIED

    # A new process, a new service, the same journal on disk.
    with SqliteCommandJournal(database) as reopened:
        second = ControlService(
            policy,
            FakeModbusWriteTransport(),
            journal=reopened,
            clock=lambda: NOW + timedelta(seconds=10),
        )
        again = second.execute(
            CommandRequest(
                command_id="cmd-2", target_id="target_zone_1", closed=False, reason="too soon"
            )
        )

    assert again.status is CommandStatus.REFUSED
    assert "rate_limited" in again.detail


def test_a_journal_that_cannot_remember_does_not_block_the_guard() -> None:
    """The in-memory journal has no last_applied_at contract to rely on."""

    class Forgetful:
        def append(self, record: CommandRecord) -> None:
            return None

    target = ControlTarget(
        target_id="target_zone_1", unit_id=1, address=0, minimum_interval_seconds=300
    )
    service = ControlService(
        ControlPolicy(enabled=True, targets=(target,)),
        FakeModbusWriteTransport(),
        journal=Forgetful(),
        clock=lambda: NOW,
    )

    outcome = service.execute(
        CommandRequest(
            command_id="cmd-1", target_id="target_zone_1", closed=True, reason="only one"
        )
    )

    assert outcome.status is CommandStatus.APPLIED
