# ADR: Measurement Identity And Id Format

**Status:** Accepted and implemented
**Scope:** what makes a `Measurement` the same measurement, and how its id is
built
**Implemented in:** `ingestion.py`, `historian.py`, `sqlite_historian.py`,
`domain.py`

This ADR was opened to shorten an id that measured as most of GeoPilot's
storage. Measuring it surfaced a second, more important problem: the current id
encodes the wrong things, and the duplicate policy behaves backwards as a
result.

Every figure below was measured against a real GeoPilot database. The
re-ingestion behavior was reproduced, not inferred.

## Context

Ids are generated in one place, `MeasurementNormalizer._measurement_id` in
`backend/src/geopilot/ingestion.py`:

```python
f"measurement:{raw.source_id}:{raw.sensor_id}:{observed}:{normalized.unit}:{value}"
```

A real id, from the bench source name used in testing:

```text
measurement:source_modbus_bench:sensor_00:2026-01-02T00:00:00Z:degC:22
```

That is 70 to 72 characters. Nothing in the codebase parses it: there is no
`split`, no prefix check and no regular expression over `Measurement.id`
anywhere in `backend/src`, `examples` or `tests`. The format is therefore free
to change without touching any consumer.

The id matters in three places:

- `Measurement.id` is the identity used by the duplicate policy;
- it is the final tie-break in `measurement_sort_key`, after `observed_at` and
  `received_at`;
- it is stored twice in SQLite, once in the row and once in the `UNIQUE` index.

## Problem 1: The Id Is Most Of The Storage

Measured at 50,000 rows with real ingestion-generated ids:

| Structure | Bytes per row | Share |
| --- | ---: | ---: |
| `measurements` table | 146.7 | 54.7% |
| `sqlite_autoindex` on `id` | 91.9 | 34.3% |
| `idx_measurements_sensor_observed` | 29.5 | 11.0% |
| **Total** | **268.3** | |

Of those 268.3 bytes, about 72 are the id inside the row and about 92 are the id
inside its `UNIQUE` index. **Roughly 61% of stored bytes are the identifier**,
not the measurement.

The constant prefix `measurement:` alone is 12 bytes per row, stored twice, on
every row forever. It distinguishes a measurement id from nothing, because no
other id shares the column.

## Problem 2: The Id Encodes The Wrong Things

Current identity is `(source_id, sensor_id, observed_at, unit, value)`. The
duplicate policy compares full content, which additionally includes
`received_at` and `quality`.

That mismatch produces two wrong behaviors, both verified.

### Contradictory Readings Never Conflict

Because `value` is part of the id, two different values for the same sensor at
the same instant produce two different ids. They are stored as two unrelated
measurements. The `DuplicateMeasurementConflictError` branch, which exists
precisely to catch contradictory data, cannot fire for this case.

A bus that reports 20 °C and 400 °C for the same sensor at the same timestamp is
a real acquisition fault. Today GeoPilot records both without complaint.

### Identical Re-Reads Do Conflict

`received_at` comes from the clock and is compared, but is not part of the id.
So re-ingesting the exact same reading produces the same id with different
content:

```text
>>> service.ingest(raw)    # first time
>>> service.ingest(raw)    # same reading, real clock
DuplicateMeasurementConflictError: Measurement id already exists with
different content: measurement:source_modbus_bench:sensor_00:...
```

This is backwards. Re-reading a register that has not changed is normal on a
real Modbus bus, and the runbook's own procedure repeats reads deliberately.
The behavior that should be idempotent raises an error, and the behavior that
should raise an error is silently accepted.

## Decision Drivers

1. **Identity must mean "the same observation"**, so contradictions are caught
   and repeats are absorbed.
2. **Debuggability.** GeoPilot is about to start real bus work. An id a human
   can read in a log and correlate with a sensor and a time is worth real
   bytes.
3. **Storage**, which is measurable and currently dominated by the id.
4. **Determinism.** The same raw reading must always produce the same id, in any
   process, with no shared state.
5. **No new dependency.**

## Options Considered

Measured at 50,000 rows, ten sensors, one row per sensor per 30 s, with the same
schema. The annual column is a ten-sensor pilot.

| Option | Characters | Bytes per row | Saving | GB per year |
| --- | ---: | ---: | ---: | ---: |
| Current | 72 | 268.3 | — | 2.82 |
| Compact structured, value kept | 51 | 218.7 | 18% | 2.30 |
| **Compact structured, value dropped** | **46** | **211.2** | **21%** | **2.22** |
| BLAKE2b-128 hex | 32 | 179.2 | 33% | 1.88 |
| BLAKE2b-128 base32 | 26 | 166.1 | 38% | 1.75 |

### Why Not The Hash

The hash wins on bytes and loses on everything else that matters right now. An
id like `k4mzq7x2...` cannot be read in a log, cannot be correlated with a
sensor by eye, and cannot be reconstructed by hand when debugging a bus that is
returning something unexpected. It also makes the sort tie-break arbitrary
rather than meaningful.

The extra 17% it would save is 0.47 GB per year on a pilot that produces 2.2 GB.
Storage is not the constraint that hurts; debugging a first real RS485 bus is.
This option should be revisited only if measured storage ever becomes a real
problem.

### Why Drop `unit`

`unit` is already a column, and a sensor declares its unit in the registry.
Normalization canonicalizes to that unit before the measurement exists, so the
unit cannot vary for a given sensor and source. It carries no identity
information.

### Why Drop `value`

Dropping `value` is what fixes Problem 2. Identity becomes the coordinates of
an observation rather than the observation itself, so a second, different value
at the same coordinates is a conflict, which is what it actually is.

## Decision

**Identity is `(source_id, sensor_id, observed_at)`. The id is:**

```text
{source_id}:{sensor_id}:{observed_at_us}
```

where `observed_at_us` is microseconds since the epoch, UTC.

```text
source_modbus_bench:sensor_00:1767312000000000
```

46 characters, 211.2 bytes per row, 21% smaller than today, still readable and
greppable.

### Required Companion Change

**The duplicate policy must stop comparing `received_at`.**

Without this, dropping `value` from the id makes Problem 2 worse rather than
better: every repeated reading would collide on id and differ on `received_at`.

`received_at` records when GeoPilot learned of a measurement, not what was
measured. Two ingestions of the same observation are the same observation
arriving twice. The same argument applies to `quality` only if quality can be
recomputed differently for identical input; today it cannot, so it stays
compared.

The resulting semantics:

| Case | Today | Proposed |
| --- | --- | --- |
| Same observation re-ingested | conflict error | idempotent |
| Different value, same coordinates | two rows stored | conflict error |
| Different sensor or instant | two rows | two rows |

This is a change to the historian contract, so it belongs in the same branch as
the id change, with the contract tests updated to assert the new table.

## Consequences

### Positive

- Contradictory acquisition data is detected instead of silently stored.
- Repeated reads are idempotent, which a real polling loop needs.
- 21% less storage, measured.
- Ids stay human-readable and sort meaningfully.
- The identity rule becomes explainable in one sentence: one sensor, one source,
  one instant, one measurement.

### Negative

- `Measurement.value` no longer appears in the id, so a log line carrying only
  an id no longer reveals the value.
- The sort tie-break changes for measurements sharing `observed_at` and
  `received_at`, because ids change. Ordering stays deterministic.
- Exported JSON payloads carry the new id format. No parser exists, but any
  external consumer holding old ids would not match new ones.
- Changing the duplicate comparison touches a tested contract, so it is not a
  cosmetic edit.

## Migration

**Do this before real acquisition starts and no migration is needed.**

Every database that exists today holds bench or simulation data. There is no
production history, so there is nothing to preserve. Once real Modbus data is
being recorded, the same change requires rewriting every stored id and
reconciling the duplicate policy against existing rows.

The window is open now precisely because the hardware has not arrived yet. That
is the strongest argument for deciding this before the bench session rather than
after.

If a database must be kept, the migration is a single `UPDATE` computing the new
id from existing columns, followed by `VACUUM`. It should be written and tested
only if a database worth keeping actually exists.

## Out Of Scope

- Hashing or compressing ids.
- Changing `sensor_id`, `source_id` or any registry identifier format.
- Changing the schema beyond the values stored in the `id` column.
- Retention, downsampling and aggregation.
- Any change to what `observed_at` means.

## Acceptance Criteria

Accept when a reviewer confirms:

- identity as observation coordinates is the intended semantics;
- trading 17% more storage for readable ids is the intended trade;
- the companion change to the duplicate comparison is acceptable;
- doing this before real acquisition, rather than after, is agreed.

## Implementation Result

Measured after implementation, using ids from the real generator rather than
synthetic ones:

| Quantity | Before | After |
| --- | ---: | ---: |
| Id length | 72 characters | 46 characters |
| Bytes per row | 268.3 | 211.2 |
| GB per year, ten-sensor pilot | 2.82 | 2.22 |
| Id share of stored bytes | 61% | 51% |

The predicted 21% saving was confirmed at 21.3%.

`epoch_microseconds()` moved to `domain.py`, so ingestion and storage share one
exact instant-to-integer conversion instead of each keeping its own.

The duplicate comparison lives in `historian.conflicts_with()` and is driven by
`dataclasses.fields(Measurement)` minus `UNCOMPARED_IDENTITY_FIELDS`, so a field
added to `Measurement` later is compared by default rather than silently
ignored.

## Follow-Up Work

1. Re-measure bytes per row once real acquisition is producing real source and
   sensor names, since id length depends on them.
2. Revisit hashing only if measured storage becomes a real constraint.
