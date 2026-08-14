# GeoPilot Project Handoff

**Status:** active local-first product foundation with export and simulated
Modbus register acquisition
**Last integrated work commit:** pending local feature branch
**Audience:** Codex or any future contributor continuing GeoPilot work

## 1. Project idea

GeoPilot is an open, local-first platform for monitoring, diagnostics and
eventual intelligent optimization of residential geothermal HVAC systems.

The project comes from a practical homeowner problem:

> A homeowner can invest tens of thousands of dollars in a high-performance
> geothermal HVAC system, but once installed, it can be difficult to understand
> what the system is actually doing. Data is scattered across devices, hidden in
> proprietary apps, unavailable offline, hard to export, and rarely presented as
> a coherent operational view.

GeoPilot exists to give homeowners back control:

- own their HVAC data;
- understand system behavior;
- keep critical information available without vendor cloud dependency;
- use open interfaces and documented data models;
- support Home Assistant or other ecosystems later without making them required;
- build toward diagnostics and optimization only after trustworthy data
  foundations exist.

## 2. Product principles

These rules should guide every future task:

- Local-first.
- Homeowner owns the data.
- Works without Internet for critical local visibility.
- Read-only MVP.
- No active HVAC control in the MVP.
- No AI in the MVP.
- No geothermal optimization logic yet.
- No mandatory cloud service.
- No mandatory Home Assistant, ESPHome, MQTT or BACnet dependency.
- Protocol adapters translate into GeoPilot; GeoPilot does not depend on
  protocol-specific concepts.
- Keep the code simple, explicit and testable.
- Prefer small vertical slices over broad abstractions.

## 3. Current repository state

The project foundation is in place.

Implemented and merged into `main`:

- repository structure and governance files;
- product vision documentation;
- technical architecture documentation;
- internal API contract documentation;
- minimal HVAC data model documentation;
- Python domain model;
- in-memory ingestion pipeline;
- in-memory asset registry;
- simulated geothermal snapshot vertical slice;
- in-memory measurement historian;
- hardware reference documentation v0.2;
- JSON export helpers;
- Modbus adapter boundary documentation;
- real Modbus readiness review;
- Modbus transport boundary;
- optional pyserial Modbus transport;
- manual hardware bench runbook;
- local storage ADR;
- SQLite measurement historian;
- backup and restore procedure;
- retention policy, with measured storage growth;
- declarative installation configuration;
- continuous acquisition runtime;
- 1-Wire DS18B20 adapter;
- systemd deployment units;
- measurement identity ADR and implementation;
- manual Modbus smoke tool for bench work;
- hardware source reference packet;
- simulated register decoder harness;
- simulated Modbus register client port.

Current useful layers:

```text
RawMeasurement
        |
        v
MeasurementNormalizer
        |
        v
IngestionService
        |
        +---- InMemoryMeasurementHistorian
        |
        v
CurrentStateProjector
        |
        v
GeothermalSnapshot
```

GeoPilot currently has three useful local-only levels:

- individual normalized measurements;
- time-window history;
- current-state projected snapshot;
- deterministic JSON-safe exports;
- hardware-free Modbus-style acquisition tests.
- declarative simulated device profiles.
- structured acquisition success and failure results.
- deterministic acquisition run reports.
- deterministic simulated polling-cycle reports.
- hardware-free Modbus transport boundary.
- optional pyserial-backed Modbus RTU transport behind `ModbusTransport`.

## 4. Current code capabilities

### Domain model

Location:

- `backend/src/geopilot/domain.py`

Core concepts:

- `Residence`
- `HVACSystem`
- `Equipment`
- `Sensor`
- `Measurement`
- `EquipmentState`
- `Event`
- `Alert`
- `Unit`
- `ProtocolSource`

Important decisions:

- `Measurement.value` is numeric only.
- `bool`, `NaN` and infinite values are rejected.
- timestamps must be timezone-aware.
- dataclasses are immutable.
- `ProtocolSource.protocol` is metadata only.
- no Modbus, MQTT, BACnet, ESPHome or Home Assistant dependency exists in the
  domain.

### Ingestion

Location:

- `backend/src/geopilot/ingestion.py`

Supported MVP conversions:

- `degC` / `°C` -> `degC`
- `degF` / `°F` -> `degC`
- `%` -> `%`
- `W` -> `W`
- `kW` -> `W`

Important decisions:

- no silent correction of invalid data;
- no real protocol;
- no database;
- no async or threads;
- injectable clock for `received_at`;
- `Measurement.id` is `{source_id}:{sensor_id}:{observed_at_us}`, the
  coordinates of an observation. The value is deliberately absent, so a
  contradictory value at the same coordinates conflicts instead of being stored
  as an unrelated measurement. See `docs/MEASUREMENT_ID_ADR.md`.

### Asset registry

Location:

- `backend/src/geopilot/registry.py`

Responsibilities:

- store residences, systems, equipment and sensors in memory;
- validate hierarchy:
  - `Residence -> HVACSystem -> Equipment -> Sensor`;
- reject duplicate asset ids;
- expose deterministic read methods.

No update/delete exists yet.

### Snapshot

Locations:

- `backend/src/geopilot/snapshot.py`
- `backend/src/geopilot/scenarios.py`
- `examples/simulated_snapshot.py`

Responsibilities:

- build a current-state read model from registry + measurements;
- select the latest measurement per sensor;
- omit sensors with no measurements;
- keep equipment present even when it has no measured sensors;
- serialize deterministic JSON-compatible output.

Latest measurement order:

```text
observed_at
→ received_at
→ measurement.id
```

Snapshot is strictly observation-only:

- no COP;
- no diagnostic;
- no alert;
- no AI;
- no HVAC control.

### Historian

Locations:

- `backend/src/geopilot/historian.py`
- `examples/simulated_history.py`

Responsibilities:

- store normalized `Measurement` objects in memory;
- preserve insertion order in `all()`;
- query by sensor and time window;
- query by system using the asset registry;
- return immutable tuples.

Time-window semantics:

- `start` inclusive;
- `end` exclusive;
- `start == end` returns an empty tuple;
- `start > end` is rejected;
- bounds must be timezone-aware;
- filtering uses `Measurement.observed_at`, not `received_at`.

Duplicate policy, shared by both historians through
`historian.conflicts_with()`:

- same id, same observation: idempotent, even when `received_at` differs,
  because a repeated read is one observation arriving twice;
- same id, different observation: `DuplicateMeasurementConflictError`;
- `received_at` is the only excluded field, listed in
  `UNCOMPARED_IDENTITY_FIELDS`. Any field added to `Measurement` later is
  compared by default.

### SQLite historian

Locations:

- `backend/src/geopilot/sqlite_historian.py`
- `docs/SQLITE_HISTORIAN.md`
- `docs/STORAGE_ADR.md`

Responsibilities:

- implement `MeasurementHistorian` on a single local SQLite file;
- preserve every contract guarantee of the in-memory historian;
- round-trip timestamps exactly, including non-UTC offsets and microseconds;
- preserve the `int` versus `float` distinction of `Measurement.value`;
- refuse to open a database written by an unknown schema version;
- expose `backup(destination)` for consistent snapshots while in use.

Important decisions:

- standard-library `sqlite3` only, no new dependency and no server;
- `journal_mode=WAL` and `synchronous=FULL` by default;
- `seq` gives insertion order, `id` is `UNIQUE` for identity;
- schema revision in `PRAGMA user_version`, no migration framework;
- no retention, aggregation, backup helper or encryption yet;
- `tests/test_historian.py` is parametrized over both historians.

### JSON export

Locations:

- `backend/src/geopilot/export.py`
- `examples/export_simulated_history.py`

Responsibilities:

- export one normalized `Measurement` as JSON-safe data;
- export deterministic measurement collections;
- export current-state snapshots through an explicit wrapper;
- keep export file/network agnostic.

Important decisions:

- no persistence;
- no HTTP API;
- no cloud;
- no dashboard;
- no diagnostic or optimization output.

### Simulated register decoder

Locations:

- `backend/src/geopilot/register_decoder.py`
- `docs/SIMULATED_REGISTER_DECODER.md`

Responsibilities:

- decode explicit simulated 16-bit register words;
- support one-word `uint16` and `int16` fixtures;
- apply scale and offset;
- return `RawMeasurement`;
- require a non-empty `source_reference`.

Important decisions:

- no serial ports;
- no hardware polling;
- no real device register maps;
- no Modbus writes;
- no byte-order or multi-register decoding yet.

### Modbus RTU simulator port

Locations:

- `backend/src/geopilot/modbus_simulator.py`
- `docs/MODBUS_RTU_SIMULATOR_PORT.md`

Responsibilities:

- define a read-only `ModbusRegisterClient` protocol;
- provide an in-memory `SimulatedModbusRegisterClient`;
- decode register definitions through `SimulatedModbusAcquisitionService`;
- test the chain from simulated register payload to decoder, `RawMeasurement`,
  normalizer, historian, export and snapshot.

Important decisions:

- no serial ports;
- no pyserial or Modbus library dependency;
- no real bus scheduling, retry or timeout logic;
- no real device register maps;
- no Modbus writes.

### Modbus transport boundary

Locations:

- `backend/src/geopilot/modbus_transport.py`
- `docs/MODBUS_TRANSPORT_BOUNDARY.md`

Responsibilities:

- define a hardware-free `ModbusTransport` protocol;
- represent read-only register requests with `ModbusReadRequest`;
- represent raw register responses with `ModbusReadResponse`;
- expose structured transport errors;
- provide `FakeModbusTransport` for unit and integration tests;
- allow a transport-backed simulated register client to feed the existing
  acquisition pipeline.

Current transport error codes:

- `timeout`;
- `connection_failed`;
- `invalid_response`;
- `illegal_function`;
- `illegal_address`;
- `device_failure`;
- `unknown`.

Important decisions:

- no `pyserial`;
- no serial ports;
- no hardware I/O;
- no retry;
- no scheduler;
- no domain model dependency;
- no real device register maps.

### Optional pyserial Modbus transport

Locations:

- `backend/src/geopilot/modbus_pyserial_transport.py`
- `docs/PYSERIAL_MODBUS_TRANSPORT.md`

Responsibilities:

- implement `ModbusTransport` behind an optional pyserial-backed RTU transport;
- keep `pyserial` in the `modbus` optional dependency extra;
- build minimal read holding and read input register request frames;
- parse minimal RTU register responses into raw words;
- validate Modbus RTU CRC;
- map serial and Modbus response failures into `ModbusTransportError`;
- support unit tests through injected fake serial objects.

Important decisions:

- importing the module does not require `pyserial`;
- no serial port is opened in default tests;
- no hardware tests run in CI;
- no real device profiles;
- no invented registers;
- no Modbus writes;
- no retry, scheduler, async or threads;
- no domain model, historian, snapshot or export dependency.

### Device profiles

Locations:

- `backend/src/geopilot/device_profiles.py`
- `docs/DEVICE_PROFILES.md`

Responsibilities:

- define immutable declarative profile objects;
- expose simulated built-in profiles only;
- convert `DeviceRegisterProfile` entries into `RegisterDefinition` values;
- reject non-simulated profiles without confirmed register addresses.

Current built-ins:

- `simulated.power_meter.v1`
- `simulated.temp_humidity_sensor.v1`

Important decisions:

- no SDM120, SDM630, XY-MD02 or PT1000 real register profiles yet;
- no guessed register addresses;
- no external YAML/JSON loading yet;
- no hardware I/O.

### Acquisition results

Locations:

- `backend/src/geopilot/acquisition.py`
- `docs/ACQUISITION_RESULTS.md`

Responsibilities:

- represent acquisition success with a normalized `Measurement`;
- represent expected failures without leaking raw exceptions;
- carry source/profile/register/sensor context;
- carry a timezone-aware `acquired_at`;
- write to historian only on success.

Current failure mappings:

- missing simulated payload: `read_failed`;
- register decode error: `decode_failed`;
- unknown sensor: `sensor_not_found`;
- incompatible unit or invalid raw value: `normalization_failed`.

Important decisions:

- no domain model changes;
- no alerts;
- no hardware I/O;
- no true Modbus RTU behavior yet.

### Acquisition runner

Locations:

- `backend/src/geopilot/acquisition_runner.py`
- `docs/ACQUISITION_RUNNER.md`

Responsibilities:

- execute an `AcquisitionPlan` once;
- preserve declared request order;
- return all `AcquisitionResult` objects;
- count successes, failures and total results;
- expose `started_at` and `completed_at`;
- serialize reports to JSON-compatible data.

Important decisions:

- no scheduling;
- no retry;
- no async or threads;
- no direct historian writes outside `AcquisitionPipeline`;
- no hardware I/O.

### Simulated polling cycle

Locations:

- `backend/src/geopilot/simulated_polling.py`
- `docs/SIMULATED_POLLING_CYCLE.md`
- `examples/simulated_polling_cycle.py`

Responsibilities:

- execute several `AcquisitionPlan` objects in declared cycle order;
- delegate acquisition work to the existing `AcquisitionRunner`;
- return one `AcquisitionRunReport` per cycle;
- count global successes, failures, totals and cycles;
- serialize polling reports to JSON-compatible data;
- support final snapshot and measurement exports through the existing historian
  and projector.

Important decisions:

- no scheduler;
- no sleep;
- no retry;
- no async or threads;
- no direct historian writes outside `AcquisitionPipeline`;
- no hardware I/O.

## 5. Documentation already available

Core docs:

- `docs/PRODUCT.md`
- `docs/ARCHITECTURE.md`
- `docs/DATA_MODEL.md`
- `docs/API.md`
- `docs/roadmap.md`
- `docs/PROTOTYPES.md`
- `docs/SIMULATED_SNAPSHOT.md`
- `docs/IN_MEMORY_HISTORIAN.md`
- `docs/SIMULATED_REGISTER_DECODER.md`
- `docs/MODBUS_ADAPTER_DESIGN.md`
- `docs/MODBUS_TRANSPORT_BOUNDARY.md`
- `docs/PYSERIAL_MODBUS_TRANSPORT.md`
- `docs/HARDWARE_BENCH_RUNBOOK.md`
- `docs/STORAGE_ADR.md`
- `docs/SQLITE_HISTORIAN.md`
- `docs/BACKUP_AND_RESTORE.md`
- `docs/RETENTION_POLICY.md`
- `docs/MEASUREMENT_ID_ADR.md`
- `docs/CONTINUOUS_ACQUISITION_ADR.md`
- `docs/ACQUISITION_RUNTIME.md`
- `docs/ONEWIRE_ADAPTER.md`
- `docs/DEPLOYMENT.md`
- `docs/MODBUS_SMOKE_TOOL.md`
- `docs/MODBUS_RTU_SIMULATOR_PORT.md`
- `docs/REAL_MODBUS_READINESS_REVIEW.md`
- `docs/DEVICE_PROFILES.md`
- `docs/ACQUISITION_RESULTS.md`
- `docs/ACQUISITION_RUNNER.md`
- `docs/SIMULATED_POLLING_CYCLE.md`

Hardware docs:

- `docs/hardware.md`
- `docs/hardware/README.md`
- `docs/hardware/GEOPILOT_STARTER_BOM.md`
- `docs/hardware/GEOPILOT_PRO_BOM.md`
- `docs/hardware/RS485_BUS.md`
- `docs/hardware/MODBUS_ADDRESSING.md`
- `docs/hardware/POWER_SUPPLY.md`
- `docs/hardware/TEST_BENCH.md`
- `docs/hardware/WIRING_DIAGRAMS.md`
- `docs/hardware/SENSOR_PLACEMENT.md`
- `docs/hardware/REGISTER_MAPS.md`
- `docs/hardware/SDM120.md`
- `docs/hardware/SDM630.md`
- `docs/hardware/XY_MD02.md`
- `docs/hardware/PT1000.md`
- `docs/hardware/FUTURE_SUPPORTED_DEVICES.md`
- `docs/hardware/PROCUREMENT.md`
- `docs/hardware/SOURCE_REFERENCES.md`

Hardware v0.2 is documentation only. It prepares future Modbus RTU work but
does not implement an adapter.

## 6. Known untracked prototypes

These files/directories exist locally and must not be added blindly:

```text
.github/workflows/esphome.yml
ai/
custom_components/
esphome/
examples/home-assistant/
```

Treat them as prototypes. Review and classify before integrating anything from
them.

## 7. Standard validation commands

Continuous integration runs Markdown, YAML, ruff, mypy, pytest and the
simulated examples, on Python 3.11, 3.12 and 3.13. The optional `modbus` extra
is deliberately not installed there, so CI also proves the core works without
`pyserial`.

Run the relevant subset locally after every change; CI is the gate, local runs
are the fast pre-check.

Full current validation set:

```bash
git diff --check
npx --yes markdownlint-cli2@0.18.1 README.md docs/*.md docs/hardware/*.md
yamllint .github/ISSUE_TEMPLATE/bug.yml .github/ISSUE_TEMPLATE/config.yml .github/ISSUE_TEMPLATE/feature.yml .github/dependabot.yml .github/workflows/ci.yml .markdownlint-cli2.yaml .pre-commit-config.yaml .yamllint.yml
ruff check backend/src/geopilot examples tests tools
mypy backend/src/geopilot examples tests tools
pytest
python3 examples/simulated_snapshot.py
python3 examples/simulated_history.py
python3 examples/export_simulated_history.py
python3 examples/simulated_polling_cycle.py
```

For documentation-only branches:

```bash
npx --yes markdownlint-cli2@0.18.1 README.md docs/*.md docs/hardware/*.md
git diff --check
```

## 8. Recommended next work

### Keep `main` published

The local history was pushed to `origin/main` after the hardware bench runbook
merged. Keep it that way rather than letting dozens of commits accumulate on
one machine again:

```bash
git push origin main
```

Push when a branch merges, not months later.

### Option A: run the hardware bench

Not a branch. Execute `docs/HARDWARE_BENCH_RUNBOOK.md` steps 1 through 6 once
the USB-RS485 adapter and a low-voltage Modbus device arrive, and record the
results in bench notes.

Why:

- Phase 2 is complete. Every remaining Phase 1 item depends on evidence from a
  real bus rather than on more code. Real device profiles and captured fixtures
  are gated on that session.
- `tools/modbus_smoke.py` makes steps 4 and 6 one command, but it has never met
  real hardware. Expect to revise it after the session.

### Option B: register decoder expansion

Branch:

```text
feature/register-decoder-fixtures
```

Goal:

- add source-reviewed captured-frame fixtures after exact manuals are selected;
- add multi-register decoding only when a verified register requires it;
- keep all fixtures hardware-free in CI.

Constraints:

- no database;
- no HTTP API;
- no cloud;
- no serial port access;
- no copied register maps without source review.

Possible deliverables:

- expanded `RegisterDataType`;
- fixture files under `tests/fixtures/`;
- tests that prove decoded `RawMeasurement` objects normalize correctly.

### Option C: real Modbus readiness review

Branch:

```text
docs/real-modbus-readiness-review
```

Goal:

- review whether the current ports, errors, profiles, decoder, runner and
  simulated polling flow are ready for a first real Modbus RTU adapter;
- identify missing transport error mappings before coding hardware I/O;
- keep SDM120, SDM630 and XY-MD02 profiles out of runtime code until exact
  official sources are reviewed.

Constraints:

- documentation only;
- no serial port access;
- no `pyserial`;
- no real register profiles;
- no invented registers;
- no hardware tests in CI.

### Option D: Modbus adapter implementation spike

Branch:

```text
feature/modbus-transport-spike
```

Goal:

- choose and isolate a Python Modbus transport library;
- keep the adapter behind the documented boundary;
- prove read-only polling against a simulator transport before hardware.

Constraints:

- no production hardware claim;
- no CI dependency on USB or RS485 devices;
- no invented registers;
- no Modbus writes.

### Option E: local dashboard specification

Branch:

```text
docs/local-dashboard-spec
```

Goal:

- define the first local dashboard read model;
- decide whether the first UI is Home Assistant-facing, a local static page, or
  a small local app;
- avoid adding a UI before the read model is clear.

## 9. Suggested implementation order

Recommended sequence from here:

1. Push or PR current `main`.
2. Complete the real Modbus readiness review.
3. Run the hardware bench runbook once the adapter arrives, and record results.
4. Expand register decoding only with source-reviewed fixtures.
5. Choose a Modbus transport library behind the adapter boundary.
6. Add simulator-backed Modbus transport tests.
7. Add non-CI hardware test scripts after safe bench procedures are reviewed.
   The manual procedure now exists in `docs/HARDWARE_BENCH_RUNBOOK.md`; a
   script may follow only if that runbook proves clear in practice.
8. Add local persistent storage.
9. Specify and build the first local dashboard.

Do not jump directly to real hardware polling without adapter design and source
verified register maps.

## 10. Future product direction

### Phase 0: foundation

Status: mostly complete.

Includes:

- product vision;
- architecture;
- data model;
- API contracts;
- local domain model;
- in-memory ingestion;
- in-memory registry;
- in-memory historian;
- simulated snapshot;
- hardware documentation;
- JSON export helpers;
- simulated register decoding.

### Phase 1: acquisition

Goal:

GeoPilot can read values from simulated and then real local devices without
interpreting system performance.

Started:

- simulated register decoding.

Planned:

- Modbus RTU adapter;
- hardware test bench;
- explicit device mapping;
- error events for failed reads.

Still out of scope:

- control;
- optimization;
- AI;
- cloud dependency.

### Phase 2: history

Goal:

GeoPilot can keep and query local historical data.

In-memory historian exists. Future work:

- local persistence;
- retention policy;
- export;
- backup/restore;
- migration strategy.

Potential storage candidates must be evaluated later. Do not add SQLite,
PostgreSQL, InfluxDB or TimescaleDB without an ADR.

### Phase 3: understanding

Goal:

GeoPilot helps homeowners understand what is happening.

Future features:

- local dashboard;
- charts;
- basic summaries;
- equipment state timeline;
- simple configurable alerts.

Still avoid:

- predictive claims;
- diagnostic conclusions without evidence;
- automatic control.

### Phase 4: intelligence

Goal:

Only after reliable acquisition and history exist, GeoPilot can explore:

- anomaly detection;
- recommendations;
- performance analysis;
- geothermal-specific calculations;
- optimization suggestions.

This phase is explicitly future work.

## 11. Rules for future Codex work

When giving work to Codex, include these constraints:

- inspect the repository first;
- check `git status --short`;
- do not touch untracked prototypes unless explicitly instructed;
- create one branch per task;
- create one focused commit per completed task;
- do not merge unless explicitly asked;
- do not push unless explicitly asked;
- run validations before declaring completion;
- never claim hardware support exists before it is implemented and tested;
- never invent Modbus registers, endianess, ranges or precision;
- mark unverified technical details as `TBD` or `À confirmer`.

## 12. Good next prompt for Codex

Use this when ready:

```text
Tu travailles dans le dépôt GeoPilot.

État actuel :
- main est à 26bfa09 Merge branch 'docs/hardware-reference-v0.2'
- les validations sont vertes;
- les prototypes non suivis doivent rester exclus.

Objectif :
Créer une branche docs/project-roadmap-refresh.

Travail :
- inspecter docs/roadmap.md, docs/PRODUCT.md, docs/ARCHITECTURE.md,
  docs/DATA_MODEL.md, docs/API.md, docs/SIMULATED_SNAPSHOT.md,
  docs/IN_MEMORY_HISTORIAN.md et docs/hardware/README.md;
- mettre à jour docs/roadmap.md pour refléter ce qui est déjà terminé;
- définir les prochaines phases : export JSON, design Modbus, sources
  matérielles officielles, simulation register decoder, futur adapter Modbus;
- ne modifier aucun code;
- ne toucher aucun prototype non suivi;
- exécuter markdownlint et git diff --check;
- créer un commit unique : Refresh GeoPilot roadmap.

Ne pas fusionner.
Ne pas pousser.
```
