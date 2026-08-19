"""Durable storage for configuration epochs.

Its own file, beside the measurements and the command journal, for the reason
the command journal has its own: retention prunes measurements, and the record
of what those measurements *meant* must outlive them. A year of loop
temperatures whose calibration history was deleted to save space is a year of
numbers nobody can defend.

Append only. An epoch is written when the fingerprint moves and never again, so
the file grows by one row per real configuration change — a handful across a
heating season, not one per cycle.

The historian's timestamp representation is reused unchanged: epoch
microseconds plus the UTC offset in effect. An epoch boundary has to be
readable as the wall-clock moment somebody edited a file.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from types import TracebackType
from typing import Any, cast

from geopilot.provenance import (
    ProvenanceChange,
    ProvenanceKind,
    SensorProvenance,
    compare,
    fingerprint,
)

SCHEMA_VERSION = 1
"""Schema revision stored in ``PRAGMA user_version``."""

VALID_SYNCHRONOUS_MODES = frozenset({"FULL", "EXTRA", "NORMAL", "OFF"})

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_MICROSECOND = timedelta(microseconds=1)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS epochs (
    seq                  INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint          TEXT    NOT NULL,
    recorded_at_us       INTEGER NOT NULL,
    recorded_at_offset_s INTEGER NOT NULL,
    note                 TEXT    NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS epoch_sensors (
    epoch_seq  INTEGER NOT NULL REFERENCES epochs (seq),
    sensor_id  TEXT    NOT NULL,
    kind       TEXT    NOT NULL,
    reference  TEXT    NOT NULL,
    unit       TEXT    NOT NULL,
    scale      REAL    NOT NULL,
    offset     REAL    NOT NULL,
    inverted   INTEGER NOT NULL,
    PRIMARY KEY (epoch_seq, sensor_id, kind)
);

CREATE INDEX IF NOT EXISTS idx_epochs_recorded ON epochs (recorded_at_us);
"""


class ProvenanceStorageError(RuntimeError):
    """Raised when the provenance journal cannot be opened or read."""


class ConfigurationEpoch:
    """One configuration, and the moment it came into effect.

    Not a frozen dataclass only because it carries the storage sequence, which
    callers should read and never set.
    """

    __slots__ = ("seq", "fingerprint", "recorded_at", "sensors", "note")

    def __init__(
        self,
        *,
        seq: int,
        fingerprint: str,
        recorded_at: datetime,
        sensors: tuple[SensorProvenance, ...],
        note: str = "",
    ) -> None:
        self.seq = seq
        self.fingerprint = fingerprint
        self.recorded_at = recorded_at
        self.sensors = sensors
        self.note = note

    @property
    def short_fingerprint(self) -> str:
        """The first 12 hex characters, which is what reports print."""

        return self.fingerprint[:12]

    def sensor(self, sensor_id: str) -> SensorProvenance | None:
        """How one sensor was derived during this epoch."""

        for entry in self.sensors:
            if entry.sensor_id == sensor_id:
                return entry
        return None

    def __repr__(self) -> str:
        return (
            f"ConfigurationEpoch(seq={self.seq}, "
            f"fingerprint={self.short_fingerprint!r}, "
            f"recorded_at={self.recorded_at.isoformat()}, "
            f"sensors={len(self.sensors)})"
        )


class SqliteProvenanceJournal:
    """Append-only storage for configuration epochs."""

    def __init__(
        self,
        database: str | Path = ":memory:",
        *,
        synchronous: str = "FULL",
    ) -> None:
        mode = synchronous.upper()
        if mode not in VALID_SYNCHRONOUS_MODES:
            raise ProvenanceStorageError(
                f"synchronous must be one of {sorted(VALID_SYNCHRONOUS_MODES)}"
            )

        try:
            # Same reasoning as the command journal: the writer is not always
            # the thread that opened the file. Serialised by the lock below.
            self._connection = sqlite3.connect(str(database), check_same_thread=False)
        except sqlite3.OperationalError as error:
            raise ProvenanceStorageError(f"could not open {database}: {error}") from error

        # Reentrant: `_hydrate` takes the lock, and it is called from methods
        # that have only just released it. A plain Lock would work today and
        # deadlock the first time somebody hydrates while holding it.
        self._lock = threading.RLock()
        with self._lock:
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute(f"PRAGMA synchronous={mode}")
            self._initialize_schema()

    def record(
        self,
        sensors: tuple[SensorProvenance, ...],
        *,
        at: datetime,
        note: str = "",
    ) -> ConfigurationEpoch | None:
        """Store this configuration if it differs from the last one recorded.

        Returns the new epoch, or None when nothing changed — which is the
        common case, since this is called every time the recorder starts.
        """

        if at.utcoffset() is None:
            raise ProvenanceStorageError("an epoch must be stamped with an aware datetime")

        digest = fingerprint(sensors)
        latest = self.latest()
        if latest is not None and latest.fingerprint == digest:
            return None

        recorded_us, recorded_offset = _to_storage(at)
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "INSERT INTO epochs (fingerprint, recorded_at_us, recorded_at_offset_s, note) "
                "VALUES (?, ?, ?, ?)",
                (digest, recorded_us, recorded_offset, note),
            )
            seq = int(cast(int, cursor.lastrowid))
            self._connection.executemany(
                "INSERT INTO epoch_sensors "
                "(epoch_seq, sensor_id, kind, reference, unit, scale, offset, inverted) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [(seq, *entry.as_row()) for entry in sensors],
            )

        return ConfigurationEpoch(
            seq=seq,
            fingerprint=digest,
            recorded_at=at,
            sensors=sensors,
            note=note,
        )

    def epochs(self) -> tuple[ConfigurationEpoch, ...]:
        """Every epoch, oldest first."""

        with self._lock:
            rows = self._connection.execute(
                "SELECT seq, fingerprint, recorded_at_us, recorded_at_offset_s, note "
                "FROM epochs ORDER BY seq"
            ).fetchall()
        return tuple(self._hydrate(cast(tuple[Any, ...], row)) for row in rows)

    def latest(self) -> ConfigurationEpoch | None:
        """The most recently recorded epoch, or None on a fresh journal."""

        with self._lock:
            row = self._connection.execute(
                "SELECT seq, fingerprint, recorded_at_us, recorded_at_offset_s, note "
                "FROM epochs ORDER BY seq DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        return self._hydrate(cast(tuple[Any, ...], row))

    def at(self, moment: datetime) -> ConfigurationEpoch | None:
        """The epoch in effect at an instant.

        None means the recording predates any epoch, which is what a database
        written before this journal existed looks like. That is worth saying out
        loud rather than guessing the configuration backwards.
        """

        microseconds, _ = _to_storage(moment)
        with self._lock:
            row = self._connection.execute(
                "SELECT seq, fingerprint, recorded_at_us, recorded_at_offset_s, note "
                "FROM epochs WHERE recorded_at_us <= ? ORDER BY seq DESC LIMIT 1",
                (microseconds,),
            ).fetchone()
        if row is None:
            return None
        return self._hydrate(cast(tuple[Any, ...], row))

    def spanning(
        self, start: datetime, end: datetime
    ) -> tuple[ConfigurationEpoch, ...]:
        """Every epoch a window touches, oldest first.

        Includes the epoch already in effect when the window opened, because a
        window whose corrections were set months earlier still has corrections.
        """

        opening = self.at(start)
        start_us, _ = _to_storage(start)
        end_us, _ = _to_storage(end)
        with self._lock:
            rows = self._connection.execute(
                "SELECT seq, fingerprint, recorded_at_us, recorded_at_offset_s, note "
                "FROM epochs WHERE recorded_at_us > ? AND recorded_at_us <= ? ORDER BY seq",
                (start_us, end_us),
            ).fetchall()

        inside = tuple(self._hydrate(cast(tuple[Any, ...], row)) for row in rows)
        if opening is None:
            return inside
        return (opening, *inside)

    def changes_between(
        self, start: datetime, end: datetime
    ) -> tuple[tuple[ConfigurationEpoch, tuple[ProvenanceChange, ...]], ...]:
        """What actually changed inside a window, epoch by epoch.

        The answer a report needs: not "the configuration moved" but "these two
        sensors' corrections moved, on this date, by this much".
        """

        touched = self.spanning(start, end)
        result: list[tuple[ConfigurationEpoch, tuple[ProvenanceChange, ...]]] = []
        for previous, current in zip(touched, touched[1:], strict=False):
            result.append((current, compare(previous.sensors, current.sensors)))
        return tuple(result)

    def count(self) -> int:
        """How many epochs have been recorded."""

        with self._lock:
            row = self._connection.execute("SELECT COUNT(*) FROM epochs").fetchone()
        return int(cast(tuple[Any, ...], row)[0])

    def backup(self, destination: str | Path) -> None:
        """Write a consistent snapshot, the same way the other journals do."""

        target = sqlite3.connect(str(destination))
        try:
            with self._lock:
                self._connection.backup(target)
        finally:
            target.close()

    def close(self) -> None:
        """Close the connection."""

        with self._lock:
            self._connection.close()

    def __enter__(self) -> SqliteProvenanceJournal:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def _hydrate(self, row: tuple[Any, ...]) -> ConfigurationEpoch:
        seq = int(row[0])
        with self._lock:
            sensors = self._connection.execute(
                "SELECT sensor_id, kind, reference, unit, scale, offset, inverted "
                "FROM epoch_sensors WHERE epoch_seq = ? ORDER BY sensor_id, kind",
                (seq,),
            ).fetchall()
        return ConfigurationEpoch(
            seq=seq,
            fingerprint=str(row[1]),
            recorded_at=_from_storage(int(row[2]), int(row[3])),
            sensors=tuple(
                SensorProvenance(
                    sensor_id=str(entry[0]),
                    kind=ProvenanceKind(str(entry[1])),
                    reference=str(entry[2]),
                    unit=str(entry[3]),
                    scale=float(entry[4]),
                    offset=float(entry[5]),
                    inverted=bool(entry[6]),
                )
                for entry in sensors
            ),
            note=str(row[4]),
        )

    def _initialize_schema(self) -> None:
        row = self._connection.execute("PRAGMA user_version").fetchone()
        version = int(cast(tuple[Any, ...], row)[0])
        if version == SCHEMA_VERSION:
            return
        if version != 0:
            raise ProvenanceStorageError(
                f"unsupported schema version {version}; this build expects {SCHEMA_VERSION}"
            )
        self._connection.executescript(_SCHEMA)
        self._connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        self._connection.commit()


def _to_storage(moment: datetime) -> tuple[int, int]:
    offset = moment.utcoffset()
    if offset is None:
        raise ProvenanceStorageError("an epoch must be stamped with an aware datetime")
    return (moment - _EPOCH) // _MICROSECOND, int(offset.total_seconds())


def _from_storage(microseconds: int, offset_seconds: int) -> datetime:
    zone = timezone(timedelta(seconds=offset_seconds))
    return (_EPOCH + timedelta(microseconds=microseconds)).astimezone(zone)


def provenance_path(database: str | Path) -> str:
    """Where the provenance journal lives, given the measurements database.

    Beside it, so a backup that sweeps the directory takes both and nobody has
    to remember a second path — the convention the command journal follows.

    An in-memory database gets an in-memory journal. Without this the sibling
    of `:memory:` is `provenance.sqlite3` in whatever directory the process
    happened to start in, and a library that litters the working directory is
    a library people stop trusting with paths.
    """

    location = str(database)
    if location == ":memory:" or location.startswith("file::memory:"):
        return ":memory:"
    return str(Path(location).with_name("provenance.sqlite3"))
