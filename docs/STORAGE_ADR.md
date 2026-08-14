# ADR: Local Measurement Storage

**Status:** Accepted, implemented in `docs/SQLITE_HISTORIAN.md`
**Scope:** first durable local backend for normalized `Measurement` objects
**Supersedes:** nothing
**Blocks:** Phase 2 persistence work

This ADR decides which local storage technology GeoPilot adopts first, and
under which constraints. It does not implement storage, add a dependency,
change the domain model, define retention values, add an HTTP API, or introduce
a dashboard.

Future ADRs should follow the same `docs/<TOPIC>_ADR.md` naming so the existing
`docs/*.md` lint glob keeps covering them without a new validation command.

## Context

GeoPilot stores normalized measurements in
`InMemoryMeasurementHistorian`. Everything is lost when the process exits,
which is acceptable for simulation work and unacceptable for a homeowner
record.

The storage-independent contract already exists as the `MeasurementHistorian`
protocol in `backend/src/geopilot/historian.py`:

```text
append(measurement)
all()
count()
latest_for_sensor(sensor_id)
query_sensor(sensor_id, start=None, end=None)
query_system(system_id, registry, start=None, end=None)
```

A persistent backend is a second implementation of that protocol, not a new
concept. Nothing above the historian should change.

### Behavior That Must Survive The Change

These are current, tested guarantees. A persistent backend that breaks any of
them is wrong, regardless of how fast it is.

| Guarantee | Current rule |
| --- | --- |
| Time-window filter | on `observed_at`, never `received_at` |
| Interval semantics | `start` inclusive, `end` exclusive, `start == end` empty, `start > end` rejected |
| Timezone | bounds and stored timestamps are timezone-aware |
| Ordering | `observed_at`, then `received_at`, then `measurement.id` |
| Insertion order | `all()` preserves it |
| Duplicate, same content | idempotent |
| Duplicate, different content | raises `DuplicateMeasurementConflictError` |
| Value type | `int` or `float`; `bool`, `NaN` and infinity already rejected upstream |
| Immutability | `Measurement` is a frozen dataclass; storage never mutates one |

### Stored Shape

`Measurement` carries `id`, `sensor_id`, `observed_at`, `received_at`, `value`,
`unit`, `quality` and `source_id`. Storage must round-trip all eight fields
exactly, because the duplicate policy compares content.

### Expected Scale

Measured against the implemented schema, not estimated. See
[Retention Policy](RETENTION_POLICY.md) for the method and the full breakdown.

| Scenario | Sensors | Interval | Rows per year | Size per year |
| ---: | ---: | ---: | ---: | ---: |
| Minimal bench | 3 | 60 s | 1.6 million | 0.33 GB |
| Realistic pilot | 10 | 30 s | 10.5 million | 2.22 GB |
| Aggressive | 20 | 10 s | 63.1 million | 13.32 GB |

The measured cost is 211.2 bytes per row. This ADR originally estimated 100 to
150 bytes per row and 1 to 1.5 GB per year for the realistic pilot, which was
low even after [Measurement Id ADR](MEASUREMENT_ID_ADR.md) cut the measurement id
from 72 to 46 characters. The id is stored twice, once in the row and once in the
`UNIQUE` index, and still accounts for about 51% of stored bytes.

This is a single-home, single-writer, append-mostly workload. It is not a
fleet, not multi-tenant, and not concurrent across machines.

## Decision Drivers

Ranked. Earlier drivers beat later ones when they conflict.

1. **Local-first and offline.** No network service may be required to read
   local history.
2. **The homeowner owns the data.** Backup and export must be possible without
   vendor permission, ideally by copying one file.
3. **Zero operations.** A homeowner will not run, patch, tune or monitor a
   database server.
4. **No new mandatory dependency.** `pyproject.toml` currently declares
   `dependencies = []`. That is an asset, not an accident.
5. **Durability.** A power loss must not corrupt history.
6. **Exact semantic preservation.** The guarantees above are non-negotiable.
7. **Reversibility.** The first choice must not lock out a better one later.
8. **Adequate query performance** at the scale above, not maximum performance.

## Options Considered

### Option 1: SQLite through the standard library

Python ships `sqlite3`. One file, ACID transactions, real indexes, real SQL.

- Zero new dependency, zero server, zero configuration.
- Backup is a file copy, or the online backup API while running.
- Handles tens of millions of rows with an appropriate index.
- Ubiquitous tooling; a homeowner can open the file in any SQLite browser.
- Not a purpose-built time-series engine: no native downsampling, no
  compression, no retention policy.
- Single-writer. Fine here, limiting if GeoPilot ever becomes multi-process.

### Option 2: Append-only JSONL files

One line per measurement, rotated by day.

- Trivially simple, human-readable, trivially appendable.
- Aligns with the existing deterministic JSON export helpers.
- No index. `latest_for_sensor` and any time window degrade to a full scan of
  every file in range.
- No atomic duplicate detection: enforcing the duplicate policy requires
  reading everything or holding a separate index that can drift from the data.
- A partial line from an interrupted write corrupts a record with no
  transaction to roll back.
- Rejected as a primary store. Still valuable as an export and archive format,
  which GeoPilot already has.

### Option 3: PostgreSQL or TimescaleDB

- Excellent time-series capability, mature retention and continuous
  aggregates in Timescale.
- Requires a running server, a data directory, users, backups, version
  upgrades and a network port on the homeowner's machine.
- Adds a mandatory dependency, or an optional one that fragments the product
  into two supported configurations.
- Violates drivers 3 and 4 outright for a single-residence MVP.
- Reasonable much later for a multi-site or hosted deployment.

### Option 4: InfluxDB

- Purpose-built for this data shape, with retention policies built in.
- Same server-operations burden as Option 3, plus a less familiar query model
  and a history of disruptive major-version changes.
- Its strengths address problems GeoPilot does not have yet.

### Option 5: Parquet or DuckDB

- Excellent columnar analytics and compression.
- Poor fit for a continuous single-row append workload; Parquet wants batches.
- DuckDB is a strong future analytics companion reading exported data. It is
  not the right primary writer for streaming appends today.

## Decision

**GeoPilot adopts SQLite through the Python standard library as its first
durable local backend, implemented as a new `MeasurementHistorian` behind the
existing protocol.**

Concretely:

- a new module, for example `backend/src/geopilot/sqlite_historian.py`;
- a `SqliteMeasurementHistorian` implementing the existing protocol;
- no change to `domain.py`, `ingestion.py`, `registry.py`, `snapshot.py`,
  `export.py`, `acquisition*.py` or any transport module;
- `InMemoryMeasurementHistorian` stays, for tests, simulation and examples;
- no ORM, no SQLAlchemy, no Alembic, no migration framework.

## Consequences

### Positive

- Durable history with no new dependency and no server.
- Backup and restore become a documented file operation the homeowner controls.
- Indexed queries replace linear scans, so query cost stops tracking total
  history size.
- Real transactions make the duplicate policy enforceable atomically instead of
  advisory.
- The in-memory and SQLite historians can share one contract test suite, which
  is the cheapest possible proof that semantics did not drift.

### Negative

- Retention, downsampling and compaction must be built by hand later. SQLite
  offers none of them.
- A deleted-rows workload eventually needs `VACUUM`, which is a documented
  maintenance step rather than an automatic one.
- Single-writer. A future multi-process design would need revisiting, though
  WAL mode allows concurrent readers.
- SQL and schema versioning become part of the codebase's surface area.

### Neutral

- The choice is reversible. Because storage sits behind the protocol and
  deterministic JSON exports already exist, migrating to Timescale or Influx
  later means writing a second adapter plus a one-shot exporter, not rewriting
  the application.

## Implementation Notes

Non-binding guidance for the future implementation branch. These are the
decisions most likely to be made badly under time pressure.

### Timestamp Storage

Do not store a naive datetime, and do not store only an instant.

`Measurement` requires timezone-aware timestamps but does not require UTC. If a
measurement observed at `-04:00` is written and read back as UTC, its content
changes, and the duplicate policy then reports a false conflict against itself.

Store both the instant and the offset:

```text
observed_at_us       INTEGER NOT NULL   -- microseconds since epoch, UTC
observed_at_offset_s INTEGER NOT NULL   -- original UTC offset, seconds
received_at_us       INTEGER NOT NULL
received_at_offset_s INTEGER NOT NULL
```

The `_us` columns sort and index correctly. The `_offset_s` columns restore the
exact original object. A round-trip test asserting `stored == original` for a
non-UTC measurement should exist from the first commit.

### Value Storage

Declare the value column `NUMERIC`. SQLite preserves the integer and real
storage classes under that affinity, so `sqlite3` returns `int` for an `int`
and `float` for a `float`, and the domain's `int | float` distinction survives
the round trip. IEEE-754 doubles round-trip exactly.

### Duplicate Policy

Enforce identity with a `UNIQUE` constraint on `id`. The implementation uses a
separate `seq INTEGER PRIMARY KEY AUTOINCREMENT` column so insertion order
stays monotonic even after future deletions; a table has only one primary key,
and ordering is worth more here than saving a column. On conflict, read the
stored row, rebuild the
`Measurement`, compare it to the incoming one, then either return silently or
raise the existing `DuplicateMeasurementConflictError`. Reuse that exception
type; do not introduce a storage-specific one.

### Ordering And Insertion Order

`all()` must preserve insertion order, which the implicit `rowid` provides for
free. Query ordering must be an explicit
`ORDER BY observed_at_us, received_at_us, id`, never an accident of the query
plan.

### Indexing

One composite index on `(sensor_id, observed_at_us)` serves `query_sensor` and
`latest_for_sensor`. `query_system` resolves sensor ids through the registry
first, then queries by those ids; the registry stays the authority on hierarchy
and the storage layer stays ignorant of it.

### Durability Settings

Use `journal_mode=WAL` and `synchronous=FULL` by default. `NORMAL` is faster
and can lose the last transactions on power loss. For a homeowner's only copy
of their operational history, that trade is not ours to make silently. Document
the setting and make it explicit rather than implicit.

Measured, the cost of that choice is 19,470 rows per second versus 41,393. The
most aggressive documented configuration writes 2 rows per second, so `FULL`
consumes about 0.01% of available write capacity. The durability setting is
effectively free at GeoPilot's scale.

### Schema Versioning

Use `PRAGMA user_version`. It is one integer, it needs no dependency, and it is
sufficient until a second schema exists. Write the version check before the
first release, not after the first migration is needed.

### Testing

Contract tests should run against both historians through the protocol, so any
semantic drift fails immediately. Use `:memory:` and `tmp_path`. No test writes
to a user directory. CI stays fast and hardware-free.

## Out Of Scope

- Retention policy values.
- Downsampling, rollups and aggregation.
- Backup scheduling and automation.
- Encryption at rest.
- HTTP API and dashboards.
- Cloud synchronization or off-site replication.
- Multi-process or multi-site access.
- Alerts, diagnostics, AI and HVAC control.

## Acceptance Criteria

This ADR is accepted when a reviewer confirms:

- the ranked drivers reflect the product principles in `docs/PRODUCT.md`;
- no rejected option was dismissed for a reason that does not hold at
  single-residence scale;
- the behavior table matches the current tested historian guarantees;
- the decision adds no mandatory dependency;
- the decision remains reversible behind the existing protocol.

## Follow-Up Work

In order, after acceptance:

1. ~~`feature/sqlite-historian`~~ — done. See
   [SQLite Measurement Historian](SQLITE_HISTORIAN.md).
2. ~~`docs/backup-and-restore`~~ — done. See
   [Backup And Restore](BACKUP_AND_RESTORE.md).
3. ~~`docs/retention-policy`~~ — done. See
   [Retention Policy](RETENTION_POLICY.md). Retention is opt-in and disabled by
   default; GeoPilot does not delete measurement data.
4. Revisit this ADR only if the single-writer or single-residence assumption
   stops holding.
