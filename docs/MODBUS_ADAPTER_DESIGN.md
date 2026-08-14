# Modbus Adapter Design

**Status:** Draft
**Scope:** Future read-only Modbus RTU acquisition boundary

This document defines the intended boundary for a future Modbus RTU adapter. It
does not implement Modbus support, claim hardware compatibility, define register
addresses, or authorize live electrical testing.

## Goals

- Keep Modbus-specific code outside the GeoPilot domain model.
- Translate verified register reads into `RawMeasurement` objects.
- Support simulator and captured-frame tests before hardware polling.
- Preserve source ids, sensor ids, timestamps, units and quality metadata.
- Keep the MVP read-only.

## Non-Goals

- No serial-port implementation in this design document.
- No hardware polling in CI.
- No Modbus writes.
- No equipment control.
- No diagnostics, optimization, COP calculation or AI recommendations.
- No invented register maps, scale factors, endianess, ranges or precision.

## Adapter Boundary

The future adapter should sit before normalization:

```text
Modbus RTU transport
        |
        v
Device register reader
        |
        v
Register decoder
        |
        v
RawMeasurement
        |
        v
MeasurementNormalizer
        |
        v
GeoPilot Measurement
```

The adapter may know about:

- serial port settings;
- Modbus slave ids;
- function codes;
- register addresses;
- word order and byte order;
- device-specific scale factors;
- retry and timeout behavior;
- captured frames and simulator fixtures.

The adapter must not leak those details into:

- `Measurement`;
- `Sensor`;
- `AssetRegistry`;
- `InMemoryMeasurementHistorian`;
- `GeothermalSnapshot`;
- JSON export helpers;
- dashboard or alert consumers.

## Proposed Components

### ModbusSourceConfig

Configuration for one local Modbus source.

Expected fields:

| Field | Purpose |
| --- | --- |
| `source_id` | GeoPilot source id for all measurements from this bus or device |
| `port` | Local serial path, excluded from CI tests |
| `baud_rate` | Bus baud rate |
| `parity` | Serial parity setting |
| `stop_bits` | Serial stop-bit setting |
| `timeout_seconds` | Per-request timeout |
| `retries` | Bounded retry count |

This configuration should not include homeowner private installation metadata
unless required for local operation.

### ModbusDeviceConfig

Configuration for one Modbus device.

Expected fields:

| Field | Purpose |
| --- | --- |
| `device_id` | Local GeoPilot device/config id |
| `source_id` | Parent source id |
| `slave_id` | Modbus RTU slave id |
| `device_model` | Human-readable model label |
| `register_map_id` | Versioned register map reference |

`device_model` is metadata. Code should branch on an explicit register map id,
not on a loose display string.

### RegisterDefinition

Definition for one measurable value from an official or reviewed source.

Expected fields:

| Field | Purpose |
| --- | --- |
| `register_id` | Stable GeoPilot register definition id |
| `sensor_id` | Target GeoPilot sensor id |
| `address` | Modbus register address, `TBD` until verified |
| `function_code` | Read function code, `TBD` until verified |
| `quantity` | Generic quantity such as temperature, power or humidity |
| `unit` | Unit emitted to `RawMeasurement` |
| `data_type` | Raw register representation, `TBD` until verified |
| `word_order` | Multi-register word order, `TBD` until verified |
| `scale` | Scale factor, `TBD` until verified |
| `source_reference` | Official manual or datasheet reference |

No register definition should be marked usable until the source reference is
recorded and reviewed.

### RegisterDecoder

Pure decoding logic that converts a raw register payload into a `RawMeasurement`.

Responsibilities:

- validate the register definition;
- decode raw words according to the verified representation;
- apply verified scale factors;
- attach the target sensor id;
- preserve the observation timestamp;
- return `RawMeasurement`.

The decoder should be testable without serial ports, real devices or timing
dependencies.

The first simulated implementation is documented in
`docs/SIMULATED_REGISTER_DECODER.md`. It supports only one-word `uint16` and
`int16` fixtures and remains separate from real Modbus polling.

### ModbusPoller

Future I/O component that reads configured registers from real devices.

Responsibilities:

- open the serial transport;
- issue read-only Modbus requests;
- apply bounded retries and timeouts;
- return raw register responses to the decoder;
- report communication failures as local events or errors.

The poller should remain outside CI unless a simulator transport is used.

The first simulator transport boundary is documented in
`docs/MODBUS_RTU_SIMULATOR_PORT.md`. It introduces a hardware-free
`ModbusRegisterClient` protocol and an in-memory implementation for end-to-end
tests, but it does not implement serial communication.

## Error Handling

The adapter should distinguish these failure categories:

| Category | Meaning | Suggested handling |
| --- | --- | --- |
| Configuration error | Invalid source, device or register definition | Fail fast before polling |
| Communication timeout | Device did not answer in time | Retry within configured bounds |
| Protocol error | Malformed or exception response | Record local error event |
| Decode error | Payload cannot match definition | Reject the measurement |
| Mapping error | Register has no known sensor target | Fail fast before polling |
| Quality issue | Value is present but suspect | Emit explicit quality metadata later |

Invalid or ambiguous values must not be silently corrected.

## Testing Strategy

Testing should progress in this order:

1. Unit-test register definitions with no I/O.
2. Unit-test decoder behavior with simulated raw words.
3. Test captured frames from known devices after source review.
4. Test a simulator transport that behaves like a Modbus device.
5. Run manual non-CI bench tests with safe hardware procedures.
6. Add real serial polling only after the above layers are stable.

CI must not require:

- USB adapters;
- RS485 devices;
- mains wiring;
- network access;
- physical HVAC equipment.

## Hardware Safety Boundary

The software adapter design does not make physical bench work safe. Any
mains-voltage wiring, panel work or live electrical measurement must follow
`docs/hardware/TEST_BENCH.md` and be handled by a qualified electrician.

Early software work should use simulators, captured frames or low-voltage
devices before any energy meter is connected to a measurement circuit.

## Open Decisions

- Which Python Modbus library, if any, should be used?
- How should register maps be versioned in source control?
- Should device configs live in static files, local UI settings or another
  local configuration surface?
- How should future quality metadata represent communication failures versus
  stale values?
- What non-CI command should run manual bench validation?

These decisions should be resolved before implementing real Modbus RTU polling.
