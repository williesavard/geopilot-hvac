# Backup And Restore

**Status:** Draft
**Scope:** homeowner-facing backup and restore for the SQLite measurement
historian

This document describes how to copy, verify and restore GeoPilot's local
history. It applies to the backend described in
[SQLite Measurement Historian](SQLITE_HISTORIAN.md).

Every command below was executed against a real GeoPilot database before being
written down. Observed results are reported as observed.

It adds no cloud service, no scheduler, no encryption, no off-site
replication and no retention policy.

## Why This Needs A Procedure

The obvious approach is wrong. GeoPilot opens its database with write-ahead
logging, so a running system keeps recent committed data in a companion
`-wal` file:

```text
geopilot.sqlite3        main database
geopilot.sqlite3-wal    committed data not yet checkpointed
geopilot.sqlite3-shm    shared-memory index for the WAL
```

Copying only the main file while the system runs was tested. The result was not
a slightly stale database. It was an unusable one:

```text
$ cp geopilot.sqlite3 naive.sqlite3      # system still running
$ sqlite3 naive.sqlite3 "SELECT COUNT(*) FROM measurements"
Error: no such table: measurements
```

The table definition itself was still in the `-wal` file. A homeowner following
intuition would have produced an empty backup and never known until the day
they needed it.

## What To Back Up

One logical thing: the measurement database. The `-wal` and `-shm` files are
not separate assets to preserve; they are working state that a proper backup
already accounts for.

The asset registry, device profiles and configuration are still code and
documentation today, so they are covered by the git repository rather than by
this procedure.

## Method 1: The `sqlite3` Command, While Running

This is the recommended path. The `sqlite3` client ships with macOS and most
Linux distributions, so it needs nothing installed.

```bash
sqlite3 geopilot.sqlite3 ".backup 'geopilot-backup-2026-08-05.sqlite3'"
```

Observed: a complete copy, `PRAGMA integrity_check` returning `ok`,
`PRAGMA user_version` preserved, and the copy unaffected by writes that
happened after the backup started. It is a point-in-time snapshot, taken
without stopping acquisition.

## Method 2: From GeoPilot, For Automation

`SqliteMeasurementHistorian.backup()` wraps the same online backup API and is
safe to call while the historian is in use:

```python
with SqliteMeasurementHistorian("geopilot.sqlite3") as historian:
    historian.backup("geopilot-backup-2026-08-05.sqlite3")
```

Use this when a backup should be triggered by GeoPilot itself. No scheduler
exists yet, so today the caller decides when.

## Method 3: Plain File Copy, Stopped Only

A plain copy is correct only when nothing has the database open.

After a clean `close()`, the WAL is checkpointed and removed, leaving a single
self-sufficient file:

```text
$ ls geopilot.sqlite3*
geopilot.sqlite3
$ cp geopilot.sqlite3 stopped-backup.sqlite3     # correct: nothing running
```

Copying all three files while the system runs was also tested and happened to
produce a readable database, but three separate copies are not one atomic
operation. A write landing between them can produce an inconsistent set. Do not
rely on it.

## Method 4: Text Archive, For Format Independence

A `.dump` archive is plain SQL text. It survives SQLite file-format changes and
diffs readably, which makes it a good long-term archive companion to a binary
backup.

```bash
sqlite3 geopilot.sqlite3 ".dump" > geopilot-archive-2026-08-05.sql
sqlite3 restored.sqlite3 ".read geopilot-archive-2026-08-05.sql"
```

**One trap, verified:** a `.dump` archive does **not** carry
`PRAGMA user_version`. A database rebuilt from a dump comes back reporting
version `0`, not `1`. Set it explicitly after restoring:

```bash
sqlite3 restored.sqlite3 "PRAGMA user_version = 1"
```

Today the historian would silently adopt a version `0` database because the
schema happens to match. Once a second schema version exists, that silence
becomes a corruption risk. Set the version.

## Choosing A Method

| Method | System running | Preserves `user_version` | Notes |
| --- | --- | --- | --- |
| `sqlite3 ".backup"` | Yes | Yes | Recommended default |
| `historian.backup()` | Yes | Yes | For GeoPilot-triggered backups |
| Plain file copy | **No** | Yes | Only with nothing holding the database |
| `.dump` text archive | Yes | **No** | Set the version after restore |

## Verifying A Backup

A backup nobody verified is a guess. Three checks, all cheap:

```bash
sqlite3 geopilot-backup-2026-08-05.sqlite3 "PRAGMA integrity_check"
sqlite3 geopilot-backup-2026-08-05.sqlite3 "SELECT COUNT(*) FROM measurements"
sqlite3 geopilot-backup-2026-08-05.sqlite3 "PRAGMA user_version"
```

Expected: `ok`, a plausible row count, and `1`.

A row count lower than the live database is normal when writes continued after
the snapshot. A count of zero, a missing table, or an integrity result other
than `ok` means the backup is not usable. Take another one.

## Restoring

1. Stop whatever holds the database. A restore into a live database is not
   supported.
2. Move the damaged database aside rather than deleting it. It may still hold
   data the backup does not.
3. Put the backup in place under the expected filename.
4. Remove any leftover `-wal` and `-shm` files beside the restored file. In
   testing, SQLite correctly rejected an invalid leftover WAL and read the
   restored database anyway, but leaving stale working state next to a restored
   database serves no purpose.
5. Verify with the three checks above.
6. Start GeoPilot and confirm it opens the database without a schema error.

```bash
mv geopilot.sqlite3 geopilot.sqlite3.damaged
cp geopilot-backup-2026-08-05.sqlite3 geopilot.sqlite3
rm -f geopilot.sqlite3-wal geopilot.sqlite3-shm
sqlite3 geopilot.sqlite3 "PRAGMA integrity_check"
```

## What A Restore Must Preserve

A restore that loses any of these is a failed restore, not a partial one:

- every stored measurement id;
- exact observed and received instants, including microseconds;
- the original UTC offset of each timestamp;
- the `int` versus `float` distinction of each value;
- unit, quality and source attribution;
- the schema version.

The online backup methods preserve all of these, because they copy the database
rather than re-serializing its contents.

## Practical Rules

- Keep at least one backup on a different physical device. A copy beside the
  original does not survive the failure that destroys the original.
- Date the filename. `geopilot-backup-2026-08-05.sqlite3` beats
  `backup-final-2.sqlite3`.
- Test a restore before you need one. An untested backup is an assumption.
- Back up before any GeoPilot upgrade that could touch the schema.

## Limits

- No scheduling. Backups are manual or caller-driven.
- No retention or rotation policy for backup files.
- No encryption at rest.
- No off-site or cloud replication.
- No integrity monitoring between backups.
- No migration path if a backup carries an older schema version; the historian
  refuses unknown versions rather than upgrading them.

## Future Work

- Retention and rotation, once real data volume is observed rather than
  estimated.
- A scheduled backup, once GeoPilot has any scheduling at all.
- Restore verification that compares measurement counts and time coverage
  against the source rather than only checking integrity.
