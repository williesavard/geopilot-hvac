# GeoPilot Minimal HVAC Data Model

This document defines the first stable data concepts for GeoPilot. It is a
documentation contract, not an implementation. The model is intentionally small
so acquisition, local history, Home Assistant integration, and future analytics
can share the same vocabulary.

The model is HVAC-generic. It does not encode geothermal diagnostics,
recommendations, predictions, optimization, or equipment control.

## 1. Design Goals

- Represent where data came from.
- Preserve timestamps, units, and quality metadata.
- Support local storage and export.
- Keep device protocol details separate from normalized measurements.
- Allow future analytics to consume the data without owning the data model.
- Remain usable without internet access or a proprietary cloud service.

## 2. Non-Goals

The minimal model does not include:

- anomaly detection;
- failure prediction;
- optimization recommendations;
- AI-generated interpretations;
- geothermal-specific formulas;
- equipment control commands;
- billing or subscription concepts;
- multi-site fleet management.

These may be modeled later as derived outputs that consume base data, not as
requirements that shape the first acquisition model.

## 3. Entity Overview

```text
Residence
  └─ HvacSystem
       └─ Equipment
            └─ Sensor
                 └─ Measurement

Equipment
  ├─ OperationalState
  └─ Event or Alert

Source
  └─ identifies where data originated
```

## 4. Core Entities

### 4.1 Residence

A residence is the local installation boundary controlled by the homeowner.

Minimum fields:

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `id` | string | yes | Locally unique stable identifier |
| `name` | string | yes | Human-readable local name |
| `timezone` | IANA timezone string | yes | Used for display and local reporting |
| `created_at` | timestamp | yes | Creation time in UTC |

Privacy rule: precise address, occupant identity, and billing details are not
part of the minimal model.

### 4.2 HVAC System

An HVAC system groups related equipment that serves a residence.

Minimum fields:

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `id` | string | yes | Locally unique stable identifier |
| `residence_id` | string | yes | Parent residence |
| `name` | string | yes | Example: "Main HVAC system" |
| `system_type` | string | yes | Generic type, such as `forced_air`, `hydronic`, `hybrid`, or `unknown` |
| `created_at` | timestamp | yes | Creation time in UTC |

The model may describe a geothermal installation later, but the minimal type
system should not require geothermal assumptions.

### 4.3 Equipment

Equipment is a physical or logical device that produces readings, has state, or
emits events.

Minimum fields:

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `id` | string | yes | Locally unique stable identifier |
| `hvac_system_id` | string | yes | Parent HVAC system |
| `name` | string | yes | Human-readable name |
| `equipment_type` | string | yes | Generic type, such as `heat_pump`, `thermostat`, `meter`, `controller`, `sensor_hub`, or `unknown` |
| `manufacturer` | string | no | Optional sanitized metadata |
| `model` | string | no | Optional sanitized metadata |
| `created_at` | timestamp | yes | Creation time in UTC |

Serial numbers are not part of the minimal shared model. If stored locally later,
they should be treated as private installation metadata.

### 4.4 Sensor

A sensor describes a measurement point or logical signal.

Minimum fields:

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `id` | string | yes | Locally unique stable identifier |
| `equipment_id` | string | yes | Parent equipment |
| `name` | string | yes | Human-readable name |
| `measurement_kind` | string | yes | Generic kind, such as `temperature`, `power`, `energy`, `flow`, `pressure`, `humidity`, `runtime`, `mode`, or `unknown` |
| `sensor_kind` | string | yes for ingestion | MVP capability used for unit compatibility: `temperature`, `relative_humidity`, or `power` |
| `unit` | string | yes | Canonical unit for numeric measurements |
| `source_id` | string | yes | Origin of the signal |
| `created_at` | timestamp | yes | Creation time in UTC |

The sensor describes what is observed. It should not describe what the value
means diagnostically.

`sensor_kind` is intentionally narrower than `measurement_kind`. It exists so
the in-memory ingestion path can reject incompatible units before creating a
measurement. It is not a protocol field and does not imply Modbus, MQTT, BACnet,
ESPHome, Home Assistant, or vendor-specific behavior.

### 4.5 Measurement

A measurement is a timestamped value produced by a sensor.

Minimum fields:

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `id` | string | yes | Locally unique identifier or deterministic event id |
| `sensor_id` | string | yes | Parent sensor |
| `observed_at` | timestamp | yes | Time the value was observed, in UTC |
| `received_at` | timestamp | yes | Time GeoPilot received the value, in UTC |
| `value` | number, string, boolean, or null | yes | Raw normalized value |
| `unit` | string | yes for numeric | Unit used for this value |
| `quality` | data quality enum | yes | See data quality section |
| `source_id` | string | yes | Data source that delivered the value |

`observed_at` and `received_at` are separate because local devices may buffer or
delay readings.

### 4.6 Unit

Units describe how numeric measurements should be interpreted.

Minimum representation:

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `code` | string | yes | Canonical unit code |
| `quantity` | string | yes | Physical quantity, such as `temperature`, `power`, `energy`, `pressure`, or `flow` |
| `symbol` | string | yes | Display symbol |

Initial canonical unit examples:

| Quantity | Preferred Unit | Symbol |
| --- | --- | --- |
| temperature | degree Celsius | `degC` |
| power | watt | `W` |
| energy | watt hour | `Wh` |
| pressure | kilopascal | `kPa` |
| flow | liter per minute | `L/min` |
| humidity | percent relative humidity | `%RH` |
| runtime | second | `s` |

GeoPilot should store canonical units and convert only at presentation or import
boundaries.

### 4.7 Source

A source identifies where data originated before normalization.

Minimum fields:

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `id` | string | yes | Locally unique stable identifier |
| `name` | string | yes | Human-readable name |
| `source_type` | string | yes | `simulator`, `firmware`, `home_assistant`, `manual_import`, `api`, or `unknown` |
| `protocol` | string | no | `mqtt`, `modbus`, `bacnet`, `esphome`, `rest`, `file`, `manual`, `unknown` |
| `created_at` | timestamp | yes | Creation time in UTC |

Protocol details should stay at the edge. The normalized measurement model
should not require consumers to understand Modbus registers, MQTT topics, or
vendor-specific APIs.

### 4.8 Operational State

An operational state captures a plain equipment state at a point in time.

Minimum fields:

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `id` | string | yes | Locally unique identifier |
| `equipment_id` | string | yes | Equipment being described |
| `observed_at` | timestamp | yes | Time observed, in UTC |
| `state` | string | yes | Generic state value |
| `source_id` | string | yes | Data source |
| `quality` | data quality enum | yes | See data quality section |

Initial state values should remain generic, for example:

- `off`
- `idle`
- `heating`
- `cooling`
- `fan_only`
- `defrost`
- `unknown`

This model does not decide whether a state is good, bad, efficient, or faulty.

### 4.9 Event

An event records that something happened.

Minimum fields:

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `id` | string | yes | Locally unique identifier |
| `equipment_id` | string | no | Equipment involved, if known |
| `occurred_at` | timestamp | yes | Time of event, in UTC |
| `event_type` | string | yes | Generic event category |
| `severity` | string | yes | `info`, `warning`, `critical`, or `unknown` |
| `message` | string | yes | Human-readable summary |
| `source_id` | string | yes | Data source |

Events are observations. They are not recommendations.

### 4.10 Alert

An alert is a local rule result that may need homeowner attention.

Minimum fields:

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `id` | string | yes | Locally unique identifier |
| `triggered_at` | timestamp | yes | Time triggered, in UTC |
| `cleared_at` | timestamp | no | Time cleared, in UTC |
| `severity` | string | yes | `info`, `warning`, `critical`, or `unknown` |
| `summary` | string | yes | Plain-language local summary |
| `source_id` | string | yes | Rule or source that produced the alert |
| `related_measurement_ids` | string array | no | Measurements used by the rule |

MVP alerts should be simple and rule-based. Alerts must not imply AI diagnosis,
failure prediction, or equipment control.

## 5. Data Quality

Every measurement and operational state should carry a quality value.

Initial quality values:

| Value | Meaning |
| --- | --- |
| `good` | Value appears complete and usable |
| `estimated` | Value was estimated, interpolated, or calculated from another source |
| `missing` | Expected value was unavailable |
| `stale` | Value is older than expected |
| `invalid` | Value was rejected or cannot be interpreted safely |
| `unknown` | Quality was not supplied or cannot be determined |

Data quality describes trust in the reading, not system health.

## 6. Minimal JSON Examples

### Measurement

```json
{
  "id": "m_001",
  "sensor_id": "sensor_supply_air_temp",
  "observed_at": "2026-07-21T02:00:00Z",
  "received_at": "2026-07-21T02:00:03Z",
  "value": 18.7,
  "unit": "degC",
  "quality": "good",
  "source_id": "source_simulator"
}
```

### Operational State

```json
{
  "id": "state_001",
  "equipment_id": "equipment_main_hvac",
  "observed_at": "2026-07-21T02:00:00Z",
  "state": "cooling",
  "source_id": "source_simulator",
  "quality": "good"
}
```

### Alert

```json
{
  "id": "alert_001",
  "triggered_at": "2026-07-21T02:10:00Z",
  "cleared_at": null,
  "severity": "warning",
  "summary": "A local threshold rule was triggered.",
  "source_id": "rule_local_threshold",
  "related_measurement_ids": ["m_001"]
}
```

## 7. Local-First Storage Rules

- Store data locally by default.
- Preserve raw normalized measurements before derived values.
- Keep private installation metadata local unless explicitly exported.
- Make exports readable without a GeoPilot cloud account.
- Use UTC timestamps internally and local timezone only for display.
- Record enough source metadata to explain where each value came from.

## 8. Relationship to Future Analytics

Future analytics should consume this model. They should not redefine base
entities.

Derived outputs such as anomalies, recommendations, predictions, and
optimization suggestions should reference the measurements, states, events, and
alerts that caused them. They belong to later phases and must remain explainable.

## 9. Open Questions

- Which local storage engine should be used first?
- Should identifiers be UUIDs, stable slugs, or deterministic hashes?
- Which units must be canonical for the first vertical slice?
- Should Home Assistant entity names be derived directly from sensor ids?
- How much source protocol metadata should be stored locally?
- What export format should be supported first?
