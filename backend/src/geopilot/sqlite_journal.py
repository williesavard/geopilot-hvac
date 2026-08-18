"""A command journal that survives a restart.

The in-memory journal was adequate while a person pressed every button: the
record existed for as long as the surface was open, which was as long as anyone
was looking. `docs/CONTROL_SURFACE_ADR.md` named replacing it as follow-up 1,
and stated the condition — **before anything automatic issues commands**.

An audit trail that a crash erases is not an audit trail. The question it exists
to answer is asked *after* an incident, and an incident is exactly the event
most likely to have restarted the process.

## Three decisions

**Its own file, not the measurements database.** Two reasons, and the second is
the one that decides it:

- SQLite permits one writer at a time per database. The poller writes every
  minute and the surface writes on command; separate files never contend;
- **the retention policy prunes measurements.** An audit record that a retention
  policy can delete is not an audit record. Commands are kept forever, and the
  cheapest way to guarantee that is to put them somewhere retention does not
  reach.

**Append only.** There is no update and no delete. A journal that can be
rewritten answers a different, weaker question than one that cannot, and the
difference matters precisely when somebody would like the record to say
something else.

**Refusals and failures are stored exactly like successes.** A command refused
because control was disabled, or because a relay had not rested long enough, is
evidence about what the system was asked to do — often more interesting than
what it did.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from types import TracebackType
from typing import Any, cast

from geopilot.control import CommandRecord, CommandStatus

SCHEMA_VERSION = 1
"""Schema revision stored in ``PRAGMA user_version``."""

VALID_SYNCHRONOUS_MODES = frozenset({"FULL", "EXTRA", "NORMAL", "OFF"})

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_MICROSECOND = timedelta(microseconds=1)

_COLUMNS = (
    "command_id, target_id, closed, reason, status, detail, "
    "decided_at_us, decided_at_offset_s"
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS commands (
    seq                 INTEGER PRIMARY KEY AUTOINCREMENT,
    command_id          TEXT    NOT NULL UNIQUE,
    target_id           TEXT    NOT NULL,
    closed              INTEGER NOT NULL,
    reason              TEXT    NOT NULL,
    status              TEXT    NOT NULL,
    detail              TEXT    NOT NULL,
    decided_at_us       INTEGER NOT NULL,
    decided_at_offset_s INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_commands_target_decided
    ON commands (target_id, decided_at_us);
"""
"""`seq` is the authority on order, not the timestamp.

Two commands can share a microsecond, and a host whose clock steps backwards can
stamp a later command earlier. The autoincrement key records the order they were
actually written, which is what an audit trail is asked about.
"""


class JournalStorageError(RuntimeError):
    """Raised when the journal cannot be opened or read."""


class SqliteCommandJournal:
    """Durable, append-only storage for command attempts.

    Satisfies the `CommandJournal` protocol, and adds the queries an audit
    actually needs: what happened to one relay, and what happened in a window.
    """

    def __init__(
        self,
        database: str | Path = ":memory:",
        *,
        synchronous: str = "FULL",
    ) -> None:
        mode = synchronous.upper()
        if mode not in VALID_SYNCHRONOUS_MODES:
            raise JournalStorageError(
                f"synchronous must be one of {sorted(VALID_SYNCHRONOUS_MODES)}"
            )

        try:
            self._connection = sqlite3.connect(str(database))
        except sqlite3.OperationalError as error:
            raise JournalStorageError(f"could not open {database}: {error}") from error

        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute(f"PRAGMA synchronous={mode}")
        self._initialize_schema()

    def append(self, record: CommandRecord) -> None:
        """Store one command attempt.

        Re-appending the same `command_id` is ignored rather than raising. A
        retried write of a record already on disk is not a new event, and a
        journal that throws while being written is a journal that loses the
        thing it was recording.
        """

        decided_us, decided_offset = _to_storage(record.decided_at)
        with self._connection:
            self._connection.execute(
                f"INSERT OR IGNORE INTO commands ({_COLUMNS}) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record.command_id,
                    record.target_id,
                    int(record.closed),
                    record.reason,
                    record.status.value,
                    record.detail,
                    decided_us,
                    decided_offset,
                ),
            )

    @property
    def records(self) -> tuple[CommandRecord, ...]:
        """Every command, oldest first.

        Named to match the in-memory journal, so the control surface reads
        either without knowing which it has.
        """

        return self.recent(limit=None)

    def recent(self, limit: int | None = 20) -> tuple[CommandRecord, ...]:
        """The most recent commands, returned oldest first.

        Ordered by `seq` rather than by timestamp, so a clock that stepped
        backwards cannot reorder history.
        """

        query = f"SELECT {_COLUMNS} FROM commands ORDER BY seq DESC"
        parameters: tuple[Any, ...] = ()
        if limit is not None:
            if limit < 0:
                raise JournalStorageError("a limit cannot be negative")
            query += " LIMIT ?"
            parameters = (limit,)

        rows = self._connection.execute(query, parameters).fetchall()
        return tuple(_row_to_record(cast(tuple[Any, ...], row)) for row in reversed(rows))

    def for_target(self, target_id: str) -> tuple[CommandRecord, ...]:
        """Everything ever asked of one relay, oldest first."""

        rows = self._connection.execute(
            f"SELECT {_COLUMNS} FROM commands WHERE target_id = ? ORDER BY seq",
            (target_id,),
        ).fetchall()
        return tuple(_row_to_record(cast(tuple[Any, ...], row)) for row in rows)

    def last_applied_at(self, target_id: str) -> datetime | None:
        """When a target was last successfully operated.

        The in-memory journal offers this too. It matters here because it
        survives a restart: without it, restarting the surface forgets that a
        relay was operated a moment ago and the rate limit starts over.
        """

        row = self._connection.execute(
            "SELECT decided_at_us, decided_at_offset_s FROM commands "
            "WHERE target_id = ? AND status = ? ORDER BY seq DESC LIMIT 1",
            (target_id, CommandStatus.APPLIED.value),
        ).fetchone()
        if row is None:
            return None
        return _from_storage(int(row[0]), int(row[1]))

    def count(self) -> int:
        """How many attempts have been recorded."""

        row = self._connection.execute("SELECT COUNT(*) FROM commands").fetchone()
        return int(cast(tuple[Any, ...], row)[0])

    def close(self) -> None:
        """Close the connection."""

        self._connection.close()

    def __enter__(self) -> SqliteCommandJournal:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def _initialize_schema(self) -> None:
        row = self._connection.execute("PRAGMA user_version").fetchone()
        version = int(cast(tuple[Any, ...], row)[0])
        if version == SCHEMA_VERSION:
            return
        if version != 0:
            raise JournalStorageError(
                f"unsupported schema version {version}; this build expects {SCHEMA_VERSION}"
            )

        self._connection.executescript(_SCHEMA)
        self._connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        self._connection.commit()


def _to_storage(moment: datetime) -> tuple[int, int]:
    """Epoch microseconds plus the UTC offset that was in effect.

    The same representation the historian uses, and for the same reason: an
    instant and the wall clock it was written on are different facts, and an
    audit trail needs the second one to be readable by a person.
    """

    offset = moment.utcoffset()
    if offset is None:
        raise JournalStorageError("a command must be stamped with an aware datetime")
    return (moment - _EPOCH) // _MICROSECOND, int(offset.total_seconds())


def _from_storage(microseconds: int, offset_seconds: int) -> datetime:
    zone = timezone(timedelta(seconds=offset_seconds))
    return (_EPOCH + timedelta(microseconds=microseconds)).astimezone(zone)


def _row_to_record(row: tuple[Any, ...]) -> CommandRecord:
    return CommandRecord(
        command_id=str(row[0]),
        target_id=str(row[1]),
        closed=bool(row[2]),
        reason=str(row[3]),
        status=CommandStatus(str(row[4])),
        detail=str(row[5]),
        decided_at=_from_storage(int(row[6]), int(row[7])),
    )
