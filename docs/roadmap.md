# GeoPilot Roadmap

This roadmap translates the product direction in `docs/PRODUCT.md` into a
sequence of buildable phases. It is intentionally conservative: GeoPilot should
first collect and preserve trustworthy local data before attempting
interpretation, diagnostics, artificial intelligence, optimization, or control.

## Roadmap Principles

- Documentation comes before implementation.
- Local operation is required for every core phase.
- Cloud services are optional extensions, not prerequisites.
- Homeowners control their data, exports, and retention.
- Each phase should produce a demonstrable, testable outcome.
- Intelligence is deferred until acquisition, history, and dashboards are
  reliable.
- Protocol adapters translate into GeoPilot concepts; the GeoPilot core must
  not depend on Modbus, MQTT, ESPHome, Home Assistant, BACnet or vendor-specific
  device concepts.

## Current Status

GeoPilot now has a merged local-first foundation on `main`.

Completed foundation work includes:

- product vision and MVP boundaries;
- architecture and ports-and-adapters principles;
- minimal HVAC data model;
- internal API contract documentation;
- Python domain model;
- in-memory asset registry;
- in-memory ingestion and unit normalization;
- simulated geothermal current-state snapshot;
- in-memory measurement historian;
- hardware reference documentation v0.2;
- real Modbus readiness review;
- hardware-free Modbus transport boundary;
- optional pyserial Modbus transport behind the transport boundary;
- repository-level validation with Markdown, YAML and Python checks.

The current implementation is still read-only and local-only. It has no
database, dashboard, Modbus adapter, Home Assistant integration, AI,
diagnostics, optimization or equipment control.

## Phase 0 - Foundation

**Status:** complete for the current local-first foundation.

Phase 0 established the repository, product definition, architecture, project
rules and first tested code path.

### Completed Deliverables

- `README.md`
- `docs/PRODUCT.md`
- `docs/ARCHITECTURE.md`
- `docs/DATA_MODEL.md`
- `docs/API.md`
- `docs/PROTOTYPES.md`
- `docs/SIMULATED_SNAPSHOT.md`
- `docs/IN_MEMORY_HISTORIAN.md`
- `docs/REAL_MODBUS_READINESS_REVIEW.md`
- `docs/MODBUS_TRANSPORT_BOUNDARY.md`
- `docs/PYSERIAL_MODBUS_TRANSPORT.md`
- `docs/HARDWARE_BENCH_RUNBOOK.md`
- `docs/STORAGE_ADR.md`
- `docs/SQLITE_HISTORIAN.md`
- `docs/BACKUP_AND_RESTORE.md`
- `docs/RETENTION_POLICY.md`
- `docs/CONTINUOUS_ACQUISITION_ADR.md`
- `docs/ACQUISITION_RUNTIME.md`
- `docs/ONEWIRE_ADAPTER.md`
- `docs/DEPLOYMENT.md`
- `docs/CONTROL_BOUNDARY_ADR.md`
- `docs/MODBUS_WRITE_BOUNDARY.md`
- `docs/COMMAND_GUARD.md`
- `docs/MODBUS_BIT_BOUNDARY.md`
- `docs/DISCRETE_STATE_ADR.md`
- `docs/MEASUREMENT_ID_ADR.md`
- `docs/MODBUS_SMOKE_TOOL.md`
- `docs/REPORTING.md`
- `docs/DASHBOARD.md`
- `docs/hardware.md`
- `docs/hardware/README.md`
- repository governance files
- GitHub issue and pull request templates
- Markdown and YAML validation
- Python linting, type checking and tests
- prototype inventory

### Implemented Code

- `backend/src/geopilot/domain.py`
- `backend/src/geopilot/registry.py`
- `backend/src/geopilot/ingestion.py`
- `backend/src/geopilot/snapshot.py`
- `backend/src/geopilot/scenarios.py`
- `backend/src/geopilot/historian.py`
- `backend/src/geopilot/sqlite_historian.py`
- `backend/src/geopilot/export.py`
- `backend/src/geopilot/register_decoder.py`
- `backend/src/geopilot/modbus_simulator.py`
- `backend/src/geopilot/modbus_transport.py`
- `backend/src/geopilot/modbus_pyserial_transport.py`
- `backend/src/geopilot/acquisition.py`
- `backend/src/geopilot/acquisition_runner.py`
- `backend/src/geopilot/simulated_polling.py`
- `examples/simulated_snapshot.py`
- `examples/simulated_history.py`
- `examples/export_simulated_history.py`
- `examples/simulated_polling_cycle.py`
- tests for the current in-memory behavior

### Remaining Foundation Rules

- Keep untracked prototypes excluded until reviewed and classified.
- Keep generated caches and local test artifacts out of commits.
- Continue making one focused branch and one focused commit per task unless a
  task explicitly needs different history.

## Phase 1 - Acquisition

**Status:** started with simulated acquisition; real hardware acquisition is not
implemented.

Phase 1 proves that GeoPilot can acquire HVAC-related data without interpreting
it.

### Completed Phase 1 Work

- Minimal measurement model exists.
- `RawMeasurement` is normalized into immutable domain `Measurement` objects.
- The in-memory ingestion path supports the first MVP unit conversions:
  - `degC` / `°C` to `degC`;
  - `degF` / `°F` to `degC`;
  - `%` to `%`;
  - `W` to `W`;
  - `kW` to `W`.
- Asset hierarchy validation exists for residence, system, equipment and
  sensor relationships.
- The simulated geothermal scenario proves a complete local read path without
  protocols or hardware.
- Hardware reference documentation v0.2 defines candidate devices, RS485
  planning, Modbus addressing conventions and bench safety boundaries.
- The simulated register decoder converts hardware-free 16-bit register
  payloads into `RawMeasurement`.
- The Modbus RTU simulator port tests the chain from simulated register payload
  through decoder, normalizer, historian, export and snapshot.
- Simulated device profiles declare internal profile-driven register mappings
  without adding real device register maps.
- Acquisition results now distinguish successful measurements from structured
  read, decode, sensor and normalization failures.
- Acquisition runner reports now execute declared requests once and produce
  deterministic success/failure counts.
- Simulated polling cycles now execute several acquisition plans in order and
  produce deterministic multi-cycle reports.
- The real Modbus readiness review defines go/no-go criteria before any serial
  adapter work starts.
- The Modbus transport boundary defines read requests, raw responses, fake
  transport behavior and structured transport errors without `pyserial`.
- The optional pyserial transport implements minimal read-only RTU framing
  behind `ModbusTransport` and is tested only with fake serial objects.
- The hardware bench runbook defines the manual, non-CI RS485 bring-up
  procedure, the expected transport errors, the safety boundary and the
  go/no-go criteria before real device profiles.
- `tools/modbus_smoke.py` performs the runbook's reads as one command. It is
  read-only, requires explicit bus coordinates and the `modbus` extra, is tested
  with a fake serial object, and cannot run in CI.

### Next Phase 1 Work

1. Expand simulated profiles only when architecture tests need them.
2. Add real device profile candidates only after exact source review.
3. Expand acquisition result mappings as simulator coverage reveals expected
   adapter failures.
4. Add runner-level examples for multi-profile acquisition passes.
5. Add simulated polling scenarios only when they clarify future poller
   behavior.
6. Expand register decoding only when source-reviewed fixtures require it.
7. Add captured-frame fixtures only after source-reviewed register maps exist.
8. Execute the manual bench runbook against real hardware and record the
   results, using `tools/modbus_smoke.py` for the reads.
9. Add real device profiles only after exact source review and bench evidence.

### Phase 1 Constraints

- Keep acquisition read-only.
- Do not open serial ports in tests.
- Do not invent Modbus registers, byte order, scale factors, ranges or
  precision.
- Keep register values `TBD` until verified against official manufacturer
  documentation.
- Do not claim hardware support until an adapter exists and has test evidence.
- Avoid geothermal diagnostics, optimization and recommendations.

### Phase 1 Exit Criteria

- A measurement can be produced by a simulator or documented local source.
- The measurement has a timestamp, unit, source and equipment context.
- The data can be consumed locally without a cloud service.
- Protocol-specific details remain outside the GeoPilot domain model.
- No interpretation or recommendations are presented as product behavior.

## Phase 2 - History and Export

**Status:** durable local persistence exists; retention, backup tooling and
dashboards remain future work.

Phase 2 turns incoming data into a local operational record that the homeowner
can inspect and export.

### Completed Phase 2 Work

- `InMemoryMeasurementHistorian` stores normalized `Measurement` objects.
- Queries support sensor-level and system-level time windows.
- Query bounds use `observed_at` with half-open interval semantics.
- Duplicate measurement ids are idempotent only when content matches.
- Query results are deterministic.
- The current historian is tested and documented.
- `SqliteMeasurementHistorian` stores measurements durably in one local file,
  with no new dependency and no server.
- Both historians run against one parametrized contract test suite.
- Timestamps, UTC offsets, microseconds and the `int` versus `float` value
  distinction round-trip exactly.
- The schema revision is tracked in `PRAGMA user_version`, and an unknown
  version is refused rather than opened.
- `backup(destination)` snapshots the database through SQLite's online backup
  API while the historian is in use.
- The backup and restore procedure is documented and was verified against a
  real database, including the WAL trap that makes a plain file copy unsafe on
  a running system.
- Storage growth is measured rather than estimated: 211.2 bytes per row, 2.22 GB
  per year for a realistic ten-sensor pilot, of which about 51% is the
  measurement id.
- Measurement identity is the coordinates of an observation,
  `{source_id}:{sensor_id}:{observed_at_us}`, so a repeated read is idempotent
  and a contradictory value at the same coordinates is a conflict.
- Retention is decided: opt-in, disabled by default. GeoPilot does not delete
  measurement data.

### Next Phase 2 Work

1. Add explicit JSON export utilities.
2. Define deterministic JSON-safe serializers for:
   - measurements;
   - historian query results;
   - current-state snapshots.
3. Add an export example script.
4. Run the hardware bench runbook once the adapter arrives. Phase 2 is complete;
   the remaining work needs evidence from a real bus, not more code.

### Phase 2 Constraints

- No database before a storage ADR.
- No HTTP API before export contracts are stable.
- No cloud dependency.
- No automatic deletion of measurement data.
- Preserve source, timestamp, unit and quality metadata in exports.

### Phase 2 Exit Criteria

- A homeowner can inspect recent and historical data locally.
- Data can be exported without vendor permission.
- A local backup can preserve operational history.
- Internet access is not required for the core workflow.

## Phase 3 - Understanding

**Status:** future work.

Phase 3 helps the homeowner understand system behavior, still without advanced
automation.

### Phase 3 Goals

- Provide dashboards that explain current and historical operation.
- Surface basic equipment state and operating modes.
- Calculate transparent metrics such as runtime, consumption and candidate COP
  only when required inputs are present and documented.
- Add simple threshold-style alerts.
- Keep every metric explainable.

### Phase 3 Deliverables

- dashboard specification;
- metric definitions;
- alert rules;
- diagnostic export package;
- test fixtures covering normal and abnormal sample data.

### Phase 3 Exit Criteria

- The homeowner can see what the system has been doing.
- Metrics show inputs, units and calculation assumptions.
- Alerts are simple and rule-based.
- The product does not claim predictive or AI-driven diagnostics.

## Phase 4 - Intelligence

**Status:** future work.

Phase 4 is the first phase where intelligent assistance may be considered. It
starts only after acquisition, history and understanding are stable.

### Candidate Capabilities

- data-quality scoring;
- anomaly detection;
- recommendations;
- explainable diagnostics;
- optimization suggestions;
- optional AI-assisted summaries.

### Guardrails

- No equipment control without a safety model and threat model.
- No opaque recommendation without evidence.
- No mandatory cloud inference.
- No geothermal-specific claims until validated against real data and domain
  review.
- Human-readable explanations remain required.

### Phase 4 Exit Criteria

- Recommendations are explainable and tied to underlying observations.
- False-positive and safety risks are documented.
- The homeowner remains in control.
- Local operation remains possible without a proprietary cloud dependency.

## Recommended Next Branches

Work should continue in small branches, in this order unless a specific need
changes the priority.

### 1. Register Decoder Fixtures

Branch:

```text
feature/register-decoder-fixtures
```

Goal:

- add source-reviewed captured-frame fixtures after exact manuals are selected;
- add multi-register decoding only when a verified register requires it;
- keep all fixtures hardware-free in CI.

### 2. Modbus Transport Spike

Branch:

```text
feature/modbus-transport-spike
```

Goal:

- choose and isolate a Python Modbus transport library;
- keep the adapter behind the documented `ModbusRegisterClient` boundary;
- prove read-only polling against a simulator transport before hardware.

### 3. Real Modbus RTU Adapter

Branch:

```text
feature/modbus-rtu-adapter
```

Goal:

- add a read-only adapter behind the documented acquisition boundary;
- keep protocol details out of the domain model;
- keep CI hardware-free;
- add non-CI hardware bench scripts only after safe bench procedures are
  documented.

### 4. Hardware Bench Session

Not a branch. Execute `docs/HARDWARE_BENCH_RUNBOOK.md` steps 1 through 6 with a
real USB-RS485 adapter and one low-voltage Modbus device, and record the
results.

Use `tools/modbus_smoke.py` for the reads; see `docs/MODBUS_SMOKE_TOOL.md`.

Phase 2 is complete. Storage, backup, retention and measurement identity are
decided and implemented; see `docs/SQLITE_HISTORIAN.md`,
`docs/BACKUP_AND_RESTORE.md`, `docs/RETENTION_POLICY.md` and
`docs/MEASUREMENT_ID_ADR.md`. Every remaining Phase 1 item is gated on bench
evidence.

## Explicit Non-Goals Before Phase 4

- AI recommendations.
- Predictive failure detection.
- Energy optimization.
- Geothermal-specific diagnostics.
- Equipment control.
- Cloud-required monitoring.
- Multi-site fleet management.

These capabilities may become valuable later, but adding them before reliable
local acquisition and history would weaken the product foundation.
