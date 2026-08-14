# GeoPilot Internal API Contracts

This document defines GeoPilot's internal interface contracts before any runtime
API is implemented. It does not specify REST routes, MQTT topics, gRPC services,
or Python classes. Those transports can be designed later around the contracts
below.

The goal is to keep every module speaking the same domain language regardless of
how data arrives or where it is stored.

## 1. Core Rule

The GeoPilot data model never depends on the communication protocol.

Protocols translate into the GeoPilot model:

- Modbus translates into GeoPilot messages.
- BACnet translates into GeoPilot messages.
- MQTT translates into GeoPilot messages.
- Home Assistant translates into GeoPilot messages.
- ESPHome translates into GeoPilot messages.
- Nordic or other edge devices translate into GeoPilot messages.

The reverse should not happen. Core consumers should not need to understand
Modbus registers, BACnet object ids, MQTT topics, Home Assistant entity ids, or
device-specific packet formats to process HVAC data.

## 2. Internal Flow

```text
Acquisition
      |
      v
Normalize()
      |
      v
Internal Event Bus
      |
      +----> Historian
      +----> Dashboard
      +----> Alert Engine
      +----> Optional Backend
      +----> Future Analytics and AI
```

### 2.1 Acquisition

Acquisition adapters read from a source. A source may be a simulator, firmware,
Home Assistant, a file import, a local API, or a future equipment protocol.

Acquisition code owns protocol-specific details.

### 2.2 Normalize

Normalization converts source-specific data into GeoPilot messages. It should:

- map source identifiers to GeoPilot ids;
- convert units into canonical units where practical;
- attach source metadata;
- preserve observed and received timestamps;
- assign data quality;
- reject or mark values that cannot be interpreted safely.

Normalization must not create diagnostics, recommendations, or predictions.

### 2.3 Internal Event Bus

The event bus is a logical boundary. It may eventually be implemented as an
in-memory queue, local message broker, append-only log, function interface, or
another transport.

The contract is that consumers receive normalized GeoPilot messages.

### 2.4 Historian

The historian persists normalized messages locally. It should preserve enough
source, timestamp, unit, and quality metadata to support export and later
analysis.

### 2.5 Dashboard

The dashboard consumes normalized messages and historical queries. It presents
observations; it does not own acquisition, storage, or analytics rules.

### 2.6 Alert Engine

The alert engine consumes measurements and states, then emits simple rule-based
alerts. MVP alerts are local and explainable.

### 2.7 Optional Backend

The backend may consume or expose normalized data, but it must not be required
for core local monitoring, storage, or display.

### 2.8 Future Analytics and AI

Analytics, recommendations, anomaly detection, and AI are future consumers of
the normalized model. They should not redefine base message shapes.

## 3. Message Envelope

Every internal message should carry a small common envelope.

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `schema` | string | yes | Message schema name |
| `schema_version` | string | yes | Semantic version of this message shape |
| `message_id` | string | yes | Locally unique message id |
| `created_at` | timestamp | yes | Time GeoPilot created the message, in UTC |
| `source_id` | string | yes | Source that produced or delivered the message |
| `correlation_id` | string | no | Groups messages from one acquisition batch |

Envelope example:

```json
{
  "schema": "geopilot.measurement",
  "schema_version": "0.1.0",
  "message_id": "msg_001",
  "created_at": "2026-07-21T02:00:03Z",
  "source_id": "source_simulator",
  "correlation_id": "batch_20260721T020000Z"
}
```

## 4. Core Messages

### 4.1 Measurement

Purpose: represent a normalized value observed by a sensor.

Payload contract:

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `measurement` | object | yes | A `Measurement` from `docs/DATA_MODEL.md` |

Example:

```json
{
  "schema": "geopilot.measurement",
  "schema_version": "0.1.0",
  "message_id": "msg_measurement_001",
  "created_at": "2026-07-21T02:00:03Z",
  "source_id": "source_simulator",
  "measurement": {
    "id": "m_001",
    "sensor_id": "sensor_supply_air_temp",
    "observed_at": "2026-07-21T02:00:00Z",
    "received_at": "2026-07-21T02:00:03Z",
    "value": 18.7,
    "unit": "degC",
    "quality": "good",
    "source_id": "source_simulator"
  }
}
```

### 4.2 EquipmentState

Purpose: represent a normalized operational state for equipment.

Payload contract:

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `state` | object | yes | An `OperationalState` from `docs/DATA_MODEL.md` |

Example:

```json
{
  "schema": "geopilot.equipment_state",
  "schema_version": "0.1.0",
  "message_id": "msg_state_001",
  "created_at": "2026-07-21T02:00:03Z",
  "source_id": "source_simulator",
  "state": {
    "id": "state_001",
    "equipment_id": "equipment_main_hvac",
    "observed_at": "2026-07-21T02:00:00Z",
    "state": "cooling",
    "source_id": "source_simulator",
    "quality": "good"
  }
}
```

### 4.3 Event

Purpose: represent a normalized observation that something happened.

Payload contract:

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `event` | object | yes | An `Event` from `docs/DATA_MODEL.md` |

Example:

```json
{
  "schema": "geopilot.event",
  "schema_version": "0.1.0",
  "message_id": "msg_event_001",
  "created_at": "2026-07-21T02:00:03Z",
  "source_id": "source_simulator",
  "event": {
    "id": "event_001",
    "equipment_id": "equipment_main_hvac",
    "occurred_at": "2026-07-21T02:00:00Z",
    "event_type": "mode_changed",
    "severity": "info",
    "message": "Operating mode changed.",
    "source_id": "source_simulator"
  }
}
```

### 4.4 Alert

Purpose: represent a local rule result that may need homeowner attention.

Payload contract:

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `alert` | object | yes | An `Alert` from `docs/DATA_MODEL.md` |

Example:

```json
{
  "schema": "geopilot.alert",
  "schema_version": "0.1.0",
  "message_id": "msg_alert_001",
  "created_at": "2026-07-21T02:10:00Z",
  "source_id": "rule_local_threshold",
  "alert": {
    "id": "alert_001",
    "triggered_at": "2026-07-21T02:10:00Z",
    "cleared_at": null,
    "severity": "warning",
    "summary": "A local threshold rule was triggered.",
    "source_id": "rule_local_threshold",
    "related_measurement_ids": ["m_001"]
  }
}
```

### 4.5 Command

Purpose: reserve a future message shape for user-approved actions.

Commands are not part of the MVP runtime. The message name is reserved so future
design can distinguish observations from actions.

Rules:

- No equipment command is implemented in the MVP.
- No module may infer a command from an alert.
- Any future command must require explicit safety review, authorization, audit,
  and a threat model.
- Read-only acquisition must remain the default architecture.

Reserved payload contract:

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `command` | object | yes | Reserved; not implemented |
| `requested_by` | string | yes | Reserved user or actor id |
| `reason` | string | yes | Reserved human-readable reason |

## 5. Compatibility Rules

- Message schemas use semantic versions.
- Additive optional fields may be introduced in a minor version.
- Removing or changing required fields requires a major version.
- Consumers should ignore unknown optional fields.
- Producers must keep required fields stable for their declared schema version.
- Timestamp fields are UTC ISO 8601 strings.
- Units should use the canonical unit codes from `docs/DATA_MODEL.md`.

## 6. Error Handling

Normalization should not hide bad input. It should return or emit structured
errors that can be stored locally and inspected.

Initial error categories:

| Category | Meaning |
| --- | --- |
| `invalid_value` | Value cannot be parsed or safely represented |
| `unknown_unit` | Source unit cannot be mapped to a canonical unit |
| `missing_timestamp` | Source did not provide a usable observed time |
| `unknown_sensor` | Source signal cannot be mapped to a known sensor |
| `stale_value` | Source value is older than expected |
| `source_unavailable` | Adapter cannot reach the source |

Errors may become `Event` messages when they are relevant to homeowners or
service collaborators.

## 7. Local-First Constraints

- Internal messages must be usable without internet access.
- Source adapters must not require cloud credentials for the MVP flow.
- The historian must be able to persist messages locally.
- The dashboard must be able to read local history.
- Exports must contain documented message shapes or documented projections.
- Optional backend integrations must consume the same contracts as local
  modules.

## 8. Transport Guidance

Transport decisions are deferred. A future implementation may use:

- direct in-process interfaces;
- local files;
- an embedded database;
- MQTT;
- HTTP;
- WebSocket;
- another local event mechanism.

The transport must adapt to the message contracts. The message contracts must
not be rewritten to fit one protocol.

## 9. Open Questions

- Should the first event bus be in-process or persisted?
- Should messages be stored exactly as emitted, projected into tables, or both?
- Which schema format should be used first: JSON Schema, Pydantic models, or
  another contract format?
- How should Home Assistant entity ids map to `sensor_id`?
- Which normalization errors should become homeowner-visible events?
- How should optional backend sync handle conflicts and offline gaps?
