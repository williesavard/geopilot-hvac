# Simulated Polling Cycle

**Status:** Draft
**Scope:** deterministic multi-cycle acquisition simulation

The simulated polling cycle runs several acquisition plans in order and returns
a local report. It models repeated polling behavior without adding a real
scheduler, wall-clock waiting, threads, async execution or hardware I/O.

This document does not add real Modbus RTU, serial ports, pyserial, retry
logic, alerts or HVAC control.

## Flow

```text
SimulatedPollingPlan
        |
        v
SimulatedPollingCycle[]
        |
        v
SimulatedPollingRunner.run()
        |
        v
SimulatedPollingReport
        |
        +---- SimulatedPollingCycleReport[]
        |             |
        |             v
        |      AcquisitionRunReport
        |
        +---- started_at
        +---- completed_at
        +---- cycle_count
        +---- success_count
        +---- failure_count
        +---- total_count
```

Each cycle owns one `AcquisitionPlan`. The simulated polling runner delegates
the actual acquisition work to the existing `AcquisitionRunner`, so historian
writes still happen only through the existing acquisition pipeline.

## Report Fields

`SimulatedPollingReport` includes:

- `plan_id`;
- `started_at`;
- `completed_at`;
- `cycle_reports`;
- `cycle_count`;
- `success_count`;
- `failure_count`;
- `total_count`.

Each `SimulatedPollingCycleReport` includes:

- `cycle_id`;
- `run_report`;
- `success_count`;
- `failure_count`;
- `total_count`.

Timestamps must be timezone-aware. `completed_at` must be after or equal to
`started_at`.

## Snapshot and Export

The polling runner does not build snapshots directly. A caller can build the
final current-state snapshot from the same historian using
`CurrentStateProjector`, then export it with `export_snapshot()`.

The demonstration example also exports the accumulated historian with
`export_measurements()`.

```text
cycle 1 -> AcquisitionRunReport
cycle 2 -> AcquisitionRunReport
cycle 3 -> AcquisitionRunReport
        |
        v
InMemoryMeasurementHistorian
        |
        +---- export_measurements()
        |
        v
CurrentStateProjector -> export_snapshot()
```

## Constraints

- No hardware I/O.
- No real Modbus RTU.
- No pyserial.
- No serial ports.
- No async.
- No threads.
- No sleep.
- No retry.
- No scheduler.
- No alerts.
- No HVAC control.
- No direct historian writes outside the existing acquisition pipeline.

## Determinism

The polling runner preserves cycle order. Each cycle preserves its
`AcquisitionPlan` request order through `AcquisitionRunner`.

The report is JSON-compatible through `to_dict()`.
