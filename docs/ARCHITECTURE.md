# GeoPilot Architecture

GeoPilot believes that homeowners should own their data, understand their HVAC
systems, and never depend on proprietary cloud services to access critical
operational information.

This document describes the target software architecture for the MVP. It is a
technical contract, not an implementation plan for geothermal logic.

## 1. Architectural Principles

- **Local-first operation.** Core acquisition, normalization, storage, display,
  alerting, and export must work without internet access.
- **Homeowner-owned data.** Operational data belongs to the homeowner. Storage,
  export, and deletion remain under local control.
- **Protocol independence.** The GeoPilot domain model never depends on Modbus,
  BACnet, MQTT, Home Assistant, ESPHome, Nordic, or any other protocol.
- **Ports and adapters.** Protocol-specific code lives at the edges. The core
  speaks only GeoPilot concepts and internal message contracts.
- **Open interfaces.** Components communicate through documented, portable data
  structures.
- **Explain before optimizing.** GeoPilot must make observations clear before it
  attempts diagnostics, recommendations, optimization, or control.
- **Safety by boundary.** GeoPilot is not a certified safety controller and must
  not replace manufacturer protections or qualified HVAC service.
- **Cloud optional.** A backend may exist later, but it must not become the
  required path between the homeowner and local operational data.

## 2. Architecture Style

GeoPilot follows a ports-and-adapters architecture.

```text
Protocols and devices
        |
        v
Acquisition adapters
        |
        v
GeoPilot normalization
        |
        v
Internal event bus
        |
        +----> Historian
        +----> Dashboard
        +----> Alert engine
        +----> Export and local API
        +----> Optional backend
        +----> Future analytics
```

The core rule is:

```text
The GeoPilot core knows HVAC concepts and internal contracts.
It does not know Modbus, MQTT, Home Assistant, ESPHome, Nordic, or vendor APIs.
```

Each external technology is an adapter that translates into the GeoPilot data
model and internal messages.

## 3. Main Modules

### 3.1 Domain Model

The domain model owns the concepts defined in `docs/DATA_MODEL.md`:

- residence;
- HVAC system;
- equipment;
- sensor;
- measurement;
- unit;
- source;
- operational state;
- event;
- alert;
- data quality.

The domain model does not own protocol parsing, persistence drivers, UI
rendering, cloud sync, analytics, or hardware control.

### 3.2 Acquisition Adapters

Acquisition adapters read source-specific data and pass it to normalization.

Candidate adapter categories:

- simulator;
- firmware or edge device;
- Home Assistant;
- file import;
- local API;
- future Modbus, BACnet, MQTT, ESPHome, Nordic, or vendor adapters.

Adapters may understand protocol details. They must not leak those details into
the core model.

The future Modbus RTU boundary is documented in
`docs/MODBUS_ADAPTER_DESIGN.md`. That document is a design contract only; it
does not mean a Modbus adapter or hardware support has been implemented.

### 3.3 Normalization

Normalization translates adapter output into GeoPilot messages from
`docs/API.md`.

Responsibilities:

- map source identifiers to GeoPilot ids;
- convert units into canonical units where practical;
- attach source metadata;
- preserve observed and received timestamps;
- assign data quality;
- reject or mark invalid data;
- emit normalized messages.

Normalization must not emit diagnostics, predictions, optimization suggestions,
or equipment commands.

### 3.4 Internal Event Bus

The internal event bus is a logical boundary between producers and consumers. It
may start as an in-process interface and evolve into a local queue, append-only
log, or broker if the product requires it.

The bus carries normalized messages:

- `Measurement`;
- `EquipmentState`;
- `Event`;
- `Alert`;
- reserved `Command` messages, not used in the MVP.

The bus must remain usable locally and offline.

### 3.5 Historian

The historian persists normalized messages locally.

Responsibilities:

- store measurements, states, events, alerts, and source metadata;
- preserve timestamps and quality values;
- support local historical queries;
- support export;
- avoid requiring a cloud account.

The historian should preserve normalized observations before storing derived
views.

### 3.6 Dashboard

The dashboard presents current and historical observations.

Responsibilities:

- show recent readings;
- show historical trends;
- expose equipment state;
- present alert status;
- make units and timestamps visible;
- avoid owning acquisition, normalization, or persistence logic.

The first dashboard may be Home Assistant, a local UI, or both. That decision is
deferred to the vertical slice.

### 3.7 Alert Engine

The alert engine consumes measurements and states and emits simple local alerts.

Responsibilities:

- evaluate explicit local rules;
- produce explainable `Alert` messages;
- avoid predictive claims;
- avoid AI diagnosis;
- avoid equipment control.

MVP alerts are rule-based observations, not recommendations.

### 3.8 Export and Local API

Export and local API surfaces allow the homeowner to retrieve data without a
proprietary service.

Responsibilities:

- expose documented projections of normalized messages;
- support local diagnostic packages;
- preserve source, unit, timestamp, and quality metadata;
- avoid leaking private installation data by default.

Transport details are deferred. The interface may become files, HTTP, MQTT, or
another local mechanism, but the contracts must remain GeoPilot messages.

### 3.9 Optional Backend

The backend is optional infrastructure.

Possible future responsibilities:

- remote access;
- backup;
- sync;
- fleet-style views for users who explicitly opt in;
- collaborative diagnostics with homeowner approval.

The backend must not be required for:

- acquisition;
- local storage;
- local display;
- local export;
- basic alerts.

### 3.10 Future Analytics

Future analytics consume normalized data after the acquisition, history, and
understanding phases are stable.

Potential future responsibilities:

- data-quality scoring;
- anomaly detection;
- recommendations;
- explainable diagnostics;
- optimization suggestions.

These are explicitly outside the MVP. They must not define the base data model
or internal message bus.

## 4. Allowed Dependencies

Dependencies should point inward toward stable contracts.

```text
adapters -> normalization -> domain contracts
historian -> domain contracts
dashboard -> domain contracts
alert engine -> domain contracts
export/local API -> domain contracts
optional backend -> domain contracts
future analytics -> domain contracts
```

Allowed:

- adapters depend on protocol libraries and GeoPilot contracts;
- normalization depends on the data model and API contracts;
- consumers depend on normalized messages;
- infrastructure implements storage, transport, and runtime concerns behind
  module boundaries.

Not allowed:

- the domain model importing protocol-specific code;
- the historian knowing Modbus registers or Home Assistant entity ids;
- the dashboard parsing raw protocol payloads;
- the alert engine bypassing normalized measurements;
- the optional backend becoming required for local operation;
- analytics redefining measurement, equipment, or alert structures.

## 5. Data Flow

The local MVP data flow is:

1. A source emits raw data.
2. An acquisition adapter reads the raw data.
3. Normalization maps it into a GeoPilot message.
4. The event bus distributes the message.
5. The historian stores it locally.
6. The dashboard reads current or historical views.
7. The alert engine may emit local rule-based alerts.
8. Export or local API surfaces make data available to the homeowner.

No internet connection is required for this flow.

## 6. Persistence

Persistence must support:

- local writes;
- local reads;
- historical queries;
- export;
- source metadata;
- UTC timestamps;
- data quality values;
- schema versioning.

The storage engine is not selected yet. Options may include files, SQLite,
embedded time-series storage, or another local store. The choice should follow
from the first vertical slice and data volume assumptions.

The persistence layer should store normalized data. Raw protocol payload storage
is optional and should be treated as diagnostic evidence, not the primary data
model.

## 7. Offline Behavior

GeoPilot should remain useful when the internet is unavailable.

Required offline behavior:

- acquisition from local or simulated sources;
- normalization;
- local persistence;
- local dashboard reads;
- local alert evaluation;
- local export.

Allowed degradation:

- optional backend sync pauses;
- remote access pauses;
- external integrations pause;
- cloud-hosted analytics pause.

## 8. Boundary With Prototypes

Existing prototypes are documented in `docs/PROTOTYPES.md`. They are learning
assets, not product architecture.

Current stance:

- analytics prototype: future Phase 4 reference only;
- Home Assistant scaffold: candidate dashboard/integration adapter;
- ESPHome scaffold: candidate acquisition/firmware adapter;
- Home Assistant automation example: documentation example only;
- generated artifacts: not source.

No prototype should be promoted until its responsibilities match this
architecture and its contract is explicit.

## 9. Out of MVP Scope

The MVP excludes:

- geothermal-specific diagnostics;
- anomaly detection;
- predictive failure detection;
- AI recommendations;
- optimization;
- equipment control;
- mandatory cloud services;
- multi-site fleet management.

These features may become consumers of the core data later. They should not be
allowed to shape the minimal architecture prematurely.

## 10. Open Decisions

- Which storage engine should be selected for the first vertical slice?
- Should the first bus be in-process or persisted?
- Should the first dashboard be Home Assistant only or include a local web UI?
- How should Home Assistant entity ids map to GeoPilot sensor ids?
- Which simulator shape best validates acquisition without hardware?
- Which hardware protocol deserves the first real adapter?
- What schema validation format should be used first?
