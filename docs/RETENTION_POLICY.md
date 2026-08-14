# Retention Policy

**Status:** Accepted
**Scope:** how long GeoPilot keeps measurement data, and what happens when it
does not

This document decides GeoPilot's retention behavior for the SQLite historian
described in [SQLite Measurement Historian](SQLITE_HISTORIAN.md).

Every figure below was measured against a real GeoPilot database rather than
estimated. The measurement procedure is included so the numbers can be
re-derived on real hardware.

It adds no scheduler, no downsampling, no aggregation, no cloud archive and no
automatic deletion.

## Decision

**GeoPilot never deletes measurement data.** Retention is opt-in, disabled by
default, and performed manually by the owner.

Three reasons, in order:

1. **The homeowner owns the data.** Software that silently discards its owner's
   history has decided something that was not its decision. A default that
   deletes is a default that surprises.
2. **The measured growth does not require it.** A realistic ten-sensor pilot
   produces 2.2 GB per year. Keeping a decade costs less disk than a phone's
   photo library.
3. **Deletion is irreversible and acquisition is not yet proven.** Discarding
   early data during the period when the acquisition chain is least trustworthy
   destroys exactly the evidence needed to debug it.

A retention duration is therefore not specified. There is no default cutoff to
tune, because there is no default deletion.

## Measured Growth

Measured with the current schema, ten sensors, one row per sensor per interval,
using ids in the format `MeasurementNormalizer` actually generates, after a WAL
checkpoint:

| Quantity | Measured |
| --- | ---: |
| Bytes per row, populated database | 211.2 |
| Rows written per second, `synchronous=FULL` | 19,470 |
| Rows written per second, `synchronous=NORMAL` | 41,393 |
| `query_sensor` over a 24-hour window, 2,120 rows returned | 7.0 ms |
| `latest_for_sensor` | 0.03 ms |

Where the bytes go, per row:

| Structure | Bytes per row | Share |
| --- | ---: | ---: |
| `measurements` table | 119.8 | 56.7% |
| `sqlite_autoindex` on `id` (the `UNIQUE` constraint) | 61.8 | 29.2% |
| `idx_measurements_sensor_observed` | 29.5 | 14.0% |

Projected annual volume, from the measured per-row cost:

| Configuration | Rows per year | Size per year |
| --- | ---: | ---: |
| 3 sensors, 60 s | 1.6 M | 0.33 GB |
| 10 sensors, 30 s | 10.5 M | 2.22 GB |
| 20 sensors, 10 s | 63.1 M | 13.32 GB |

### Revision History Of These Figures

| Revision | Bytes per row | Why it changed |
| --- | ---: | --- |
| First | 222 | Measured with a simplified 52-character id, not the one ingestion generates |
| Second | 268.3 | Corrected to the real 72-character id, which includes `source_id` and `unit` |
| Current | 211.2 | Id shortened to 46 characters by [Measurement Id ADR](MEASUREMENT_ID_ADR.md) |

[Storage ADR](STORAGE_ADR.md) originally estimated 100 to 150 bytes per row.
Even after the id was shortened, the measured figure is above that range.

### The Identifier Still Costs Half The Storage

Measurement ids now run about 46 characters, for example
`source_modbus_bench:sensor_00:1767225600000000`. Each id is stored twice, once
in the row and once in the `UNIQUE` index, which is about 108 of the 211.2 bytes
per row.

**Roughly 51% of GeoPilot's storage is still the identifier**, down from 61%. A
hash would take it to about 26 characters, and was rejected on debuggability
grounds in [Measurement Id ADR](MEASUREMENT_ID_ADR.md). That remains the largest
available storage lever, and it is still larger than any plausible retention
policy.

## When Retention Becomes Worth Considering

Not on a calendar. On one of these:

- the database approaches a meaningful fraction of available disk;
- backups become slow or awkward to move off-device;
- a query that matters becomes too slow, and an index cannot fix it;
- the owner asks for old data to be removed.

Until one of those is true, retention work is optimization without a problem.

## If The Owner Does Want Retention

### Archive Before Deleting

Deletion is irreversible. Take and **verify** a backup first, per
[Backup And Restore](BACKUP_AND_RESTORE.md). A retention step whose backup was
never verified is data loss with extra steps.

### Delete By Observed Time

Retention operates on `observed_at`, matching every query in the historian.
Cutoffs are expressed in microseconds since the epoch, UTC:

```sql
DELETE FROM measurements WHERE observed_at_us < :cutoff_us;
```

### `VACUUM` Is Mandatory, Not Optional

Measured on a 50,000-row database, deleting 28,800 rows. The absolute sizes come
from the earlier simplified-id measurement; the reclamation behavior does not
depend on id length:

| Step | File size | Reclaimed |
| --- | ---: | ---: |
| Before | 11,083,776 | — |
| After `DELETE` | 11,083,776 | **0** |
| After `VACUUM` | 4,538,368 | 6,545,408 |

`DELETE` reclaimed **nothing**. It marks pages free for reuse inside the same
file; the file does not shrink. Retention without `VACUUM` frees no disk at all,
which defeats the only reason to delete.

```sql
VACUUM;
```

`VACUUM` caveats:

- it rewrites the entire database, so it needs transient free space roughly
  equal to the database size;
- it takes an exclusive lock, so acquisition must be stopped;
- it took 0.01 s at 50,000 rows, but the cost scales with database size, so
  measure before running it on a multi-gigabyte file.

### Downsampling Is Deferred

Keeping hourly averages instead of raw samples is the better long-term answer,
because it preserves shape while discarding volume. It requires aggregation,
which GeoPilot does not have, and a decision about which statistic is
authoritative once raw data is gone.

That belongs to Phase 3 or later, alongside metric definitions. Deleting raw
data before aggregation exists would discard the input to a calculation that has
not been designed yet.

## Durability Is Not A Retention Trade

The Storage ADR chose `synchronous=FULL` and noted a write-throughput cost.
Measured, that cost is 19,470 versus 41,393 rows per second.

GeoPilot's most aggressive documented configuration writes 2 rows per second.
`FULL` therefore uses about 0.01% of measured write capacity. The durability
setting is free at this scale and should not be relaxed to buy performance
nobody needs.

## Reproducing These Measurements

Run this against a scratch database, never a live one. Replace the row count to
match the scale being tested.

```python
from geopilot.sqlite_historian import SqliteMeasurementHistorian

with SqliteMeasurementHistorian("scratch.sqlite3") as historian:
    for measurement in generated_measurements:
        historian.append(measurement)
```

Then measure:

```bash
sqlite3 scratch.sqlite3 "PRAGMA wal_checkpoint(TRUNCATE)"
ls -l scratch.sqlite3
sqlite3 scratch.sqlite3 \
  "SELECT name, SUM(pgsize) FROM dbstat GROUP BY name ORDER BY 2 DESC"
sqlite3 scratch.sqlite3 "SELECT AVG(LENGTH(id)) FROM measurements"
```

Divide file size by row count for bytes per row. The `dbstat` breakdown shows
whether the table, the `UNIQUE` autoindex or the explicit index dominates.

Re-run this once real acquisition is producing real ids and real sensor counts.
The per-row cost depends on the id format, so it will change if ids change.

## What Is Forbidden

- No automatic deletion of measurement data.
- No deletion without a verified backup.
- No deletion as a side effect of an upgrade, a migration or a restore.
- No `VACUUM` while acquisition is running.
- No retention duration written into runtime code as a default.
- No downsampling before aggregation is designed.
- No claim that older data was preserved when it was aggregated away.

## Limits

- Retention is manual. Nothing schedules it, because GeoPilot has no scheduler.
- No tooling exists to preview what a cutoff would delete.
- No partial retention per sensor, per system or per measurement kind.
- No archive format for deleted ranges beyond the existing JSON export and
  SQLite backup.

## Future Work

- A dry-run helper that reports what a cutoff would remove, before any
  deletion exists in code.
- Downsampling, once aggregation and metric definitions exist.
- Re-measure per-row cost against real acquisition data.
