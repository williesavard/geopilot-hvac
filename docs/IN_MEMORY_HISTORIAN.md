# In-Memory Measurement Historian

GeoPilot's in-memory historian stores normalized `Measurement` objects for
local, deterministic time-window queries during early development.

It is not persistent storage. It does not write to disk, synchronize with a
cloud service, calculate performance, diagnose equipment, generate alerts or
control HVAC equipment.

## Role

The historian sits after ingestion:

```text
RawMeasurement
        |
        v
MeasurementNormalizer
        |
        v
IngestionService
        |
        v
MeasurementHistorian
        |
        v
time-window queries
```

The historian keeps domain `Measurement` objects as the source of truth. It can
also be used by read models such as `CurrentStateProjector` because it exposes
the same append/read surface needed by the existing in-memory sink.

## Difference from the current snapshot

The historian answers historical questions:

- what measurements exist for this sensor?
- what measurements exist for this system?
- which measurements fall within this observed-time window?

The snapshot answers a current-state question:

- what is the latest observation for each measured sensor?

Neither component infers equipment health, efficiency or control decisions.

## Time-window semantics

Queries filter by `Measurement.observed_at`, not `received_at`.

Bounds use half-open interval semantics:

- `start` is inclusive;
- `end` is exclusive;
- `start == end` returns no results;
- `start > end` is rejected;
- provided timestamps must be timezone-aware.

## Deterministic ordering

Query results are sorted by:

```text
observed_at
→ received_at
→ measurement.id
```

`all()` preserves insertion order for debugging and simple inspection.

## Duplicate policy

Measurement ids represent logical measurement identity.

- appending the same id with identical content is idempotent;
- appending the same id with different content raises
  `DuplicateMeasurementConflictError`;
- duplicate handling does not depend on Python object identity.

## Limits

This implementation is deliberately simple:

- no database;
- no file persistence;
- no indexing beyond a uniqueness map by id;
- no retention policy;
- no aggregation;
- no min/max/average;
- no downsampling;
- no async or threads.

A later storage backend can implement the same historian contract without
changing the domain model.

## Run the example

From the repository root:

```bash
python examples/simulated_history.py
```

The example builds the simulated geothermal scenario, queries one sensor over a
time window, queries the whole system over the same window and prints JSON.
