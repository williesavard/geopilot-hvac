# Acquisition Runner

**Status:** Draft
**Scope:** deterministic in-memory acquisition run reports

The acquisition runner executes a declared acquisition plan once and returns a
local report. It is a step toward future polling, but it is not a scheduler,
poller, retry engine or hardware adapter.

This document does not add real Modbus RTU, serial ports, pyserial, hardware
I/O, alerts or HVAC control.

## Flow

```text
AcquisitionPlan
        |
        v
AcquisitionRequest[]
        |
        v
AcquisitionRunner.run()
        |
        v
AcquisitionRunReport
        |
        +---- successes
        +---- failures
        +---- started_at
        +---- completed_at
        +---- counts
```

Each request owns an executor callable. The runner only calls request executors
in order and combines their `AcquisitionResult` objects.

## Report Fields

`AcquisitionRunReport` includes:

- `plan_id`;
- `started_at`;
- `completed_at`;
- `results`;
- `success_count`;
- `failure_count`;
- `total_count`.

Timestamps must be timezone-aware. `completed_at` must be after or equal to
`started_at`.

## Constraints

- No hardware I/O.
- No real Modbus RTU.
- No pyserial.
- No serial ports.
- No async.
- No threads.
- No retry.
- No scheduler.
- No alerts.
- No HVAC control.
- No direct historian writes outside the existing acquisition pipeline.

## Determinism

The runner preserves request order. If a request returns multiple results, those
results stay together in the order returned by the request executor.

The report is JSON-compatible through `to_dict()`.
