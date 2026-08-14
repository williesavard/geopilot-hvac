# SQLite Measurement Historian

**Status:** Draft
**Scope:** durable local measurement storage behind `MeasurementHistorian`

This document describes the first persistent historian, implementing the
decision recorded in [Storage ADR](STORAGE_ADR.md).

It adds no third-party dependency, no server, no HTTP API, no dashboard, no
retention policy, no aggregation, no cloud synchronization, no alerts and no
HVAC control.

## Role

```text
IngestionService
        |
        v
MeasurementHistorian  (protocol)
        |
        +---- InMemoryMeasurementHistorian   simulation, tests, examples
        |
        +---- SqliteMeasurementHistorian     durable local file
```

Both implementations satisfy the same contract. Code above the historian, such
as `CurrentStateProjector` and the export helpers, does not know which one it
is talking to.

## Usage

```python
from geopilot.sqlite_historian import SqliteMeasurementHistorian

with SqliteMeasurementHistorian("geopilot.sqlite3") as historian:
    historian.append(measurement)
    recent = historian.query_sensor("sensor_a", start=start, end=end)
```

The default database is `:memory:`, so tests and examples never touch the
filesystem unless a path is given. The class is also usable without the context
manager; call `close()` when finished.

## Schema

```sql
CREATE TABLE measurements (
    seq                  INTEGER PRIMARY KEY AUTOINCREMENT,
    id                   TEXT    NOT NULL UNIQUE,
    sensor_id            TEXT    NOT NULL,
    observed_at_us       INTEGER NOT NULL,
    observed_at_offset_s INTEGER NOT NULL,
    received_at_us       INTEGER NOT NULL,
    received_at_offset_s INTEGER NOT NULL,
    value                NUMERIC NOT NULL,
    unit                 TEXT    NOT NULL,
    quality              TEXT    NOT NULL,
    source_id            TEXT    NOT NULL
);

CREATE INDEX idx_measurements_sensor_observed
    ON measurements (sensor_id, observed_at_us);
```

`seq` provides insertion order for `all()`. `id` carries logical measurement
identity and its `UNIQUE` constraint backs the duplicate policy. The ADR
originally proposed making `id` the primary key; a table needs one primary key,
and monotonic insertion order is worth more than saving a column.

## Timestamps

Each timestamp is stored twice, as an exact instant and as its UTC offset.

`Measurement` requires timezone-aware timestamps but does not require UTC. A
measurement observed at `-04:00` that came back as UTC would compare unequal to
itself, and the duplicate policy would then report a conflict between a
measurement and its own stored copy.

Microseconds come from `domain.epoch_microseconds()`, which uses `timedelta`
arithmetic rather than `datetime.timestamp()`, because the float returned by
`timestamp()` cannot represent microsecond resolution exactly at current epoch
values. Ingestion uses the same helper to build measurement ids, so storage and
identity cannot drift apart.

What round-trips exactly:

- the instant;
- the UTC offset;
- microsecond precision.

What does not round-trip:

- the zone name. A `ZoneInfo("America/Toronto")` timestamp returns as a fixed
  `-04:00` offset. Aware datetimes compare by instant, so the measurement is
  still equal to the original; only the printed zone identity is lost.

## Values

The value column uses `NUMERIC` affinity, which preserves SQLite's INTEGER and
REAL storage classes, so an `int` returns as an `int` and a `float` returns as
a `float`.

This is asserted with `isinstance`, not equality: `20 == 20.0` is true in
Python, so an equality check would not notice the type changing.

## Durability

The connection opens with `journal_mode=WAL` and `synchronous=FULL`.

`FULL` is slower than `NORMAL` on write-heavy workloads but does not lose
committed transactions on power loss. For a homeowner's only copy of their
operational history, that is the correct default. The mode is a constructor
argument for callers who knowingly want a different trade-off; invalid values
are rejected rather than passed through to SQLite.

## Schema Versioning

The schema revision lives in `PRAGMA user_version`.

- version `0`: empty or new database, schema is created and the version set;
- version equal to `SCHEMA_VERSION`: opened as-is;
- any other version: `HistorianStorageError`, because no migration exists yet.

Refusing to open an unknown schema is deliberate. Silently operating on a
database written by a different build is how history gets corrupted.

## Query Behavior

Identical to the in-memory historian, and enforced by the shared contract
tests:

- windows filter on `observed_at`, `start` inclusive and `end` exclusive;
- ordering is an explicit `ORDER BY observed_at_us, received_at_us, id`, never
  an accident of the query plan;
- `query_system` resolves sensor ids through the asset registry first, so the
  storage layer stays ignorant of the asset hierarchy;
- results are immutable tuples;
- duplicate detection uses `historian.conflicts_with()`, which excludes
  `received_at`, so a repeated read is idempotent and a contradictory value at
  the same coordinates is a conflict.

## Testing

`tests/test_historian.py` is parametrized over both implementations through the
protocol, so any semantic drift between them fails immediately.
`tests/test_sqlite_historian.py` covers what only this backend can get wrong:
durability across connections, exact value and timestamp round-trips, WAL mode,
and schema version handling.

No test writes outside `tmp_path`. CI stays fast and hardware-free.

## Limits

- no retention, expiry or downsampling. GeoPilot does not delete measurement
  data; see [Retention Policy](RETENTION_POLICY.md);
- no `VACUUM` helper. Measured, `DELETE` alone reclaims zero bytes, so any
  future deletion workload must pair with `VACUUM`;
- single writer;
- no encryption at rest;
- no schema migration path, only version refusal.

## Backup

`backup(destination)` writes a consistent snapshot through SQLite's online
backup API, and is safe to call while the historian is in use. A plain file copy
is not equivalent under WAL journalling.

The full procedure, including verification and restore, is in
[Backup And Restore](BACKUP_AND_RESTORE.md).

## Future Work

- Nothing pending. The measurement id was shortened by
  [Measurement Id ADR](MEASUREMENT_ID_ADR.md); a further reduction would require
  hashing, which that ADR rejected on debuggability grounds.
- A migration path when a second schema version becomes necessary.
