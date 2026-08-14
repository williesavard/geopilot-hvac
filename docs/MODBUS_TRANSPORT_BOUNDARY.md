# Modbus Transport Boundary

**Status:** Draft
**Scope:** hardware-free Modbus RTU transport port

This document defines the first transport boundary for future Modbus RTU
support. It does not add `pyserial`, open serial ports, perform hardware I/O,
define real device profiles, invent registers, retry, schedule work, emit
alerts or control HVAC equipment.

## Purpose

GeoPilot already has a simulated register client and acquisition pipeline. The
transport boundary isolates the future wire-level read before any real serial
library is introduced.

```text
ModbusReadRequest
        |
        v
ModbusTransport.read_registers()
        |
        v
ModbusReadResponse
        |
        v
TransportBackedSimulatedModbusRegisterClient
        |
        v
RegisterDecoder
        |
        v
AcquisitionPipeline
```

The transport returns raw register words only. It does not produce
`RawMeasurement`, `Measurement`, historian entries, snapshots or exports.

## Types

### ModbusTransport

`ModbusTransport` is a read-only protocol:

```text
read_registers(request) -> ModbusReadResponse
```

Future serial implementations should implement this protocol behind an adapter.

The first optional serial implementation is documented in
`docs/PYSERIAL_MODBUS_TRANSPORT.md`. It remains isolated behind this protocol
and is not used by default tests.

### ModbusReadRequest

`ModbusReadRequest` represents one read-only request:

- `request_id`;
- `source_id`;
- `unit_id`;
- `register_kind`;
- `address`;
- `quantity`.

`register_kind` is either:

- `holding`;
- `input`.

The request is transport-level data. It must not include GeoPilot domain objects
or normalized measurement fields.

### ModbusReadResponse

`ModbusReadResponse` contains:

- `request_id`;
- raw 16-bit `words`;
- timezone-aware `observed_at`.

The response does not apply scale factors, units, normalization or sensor
mapping.

### ModbusTransportError

`ModbusTransportError` contains:

- structured `code`;
- readable `message`;
- optional `request_id`.

Current transport error codes:

| Code | Meaning |
| --- | --- |
| `timeout` | device did not respond in the expected time |
| `connection_failed` | transport could not connect or initialize |
| `invalid_response` | response shape was malformed or too short |
| `illegal_function` | Modbus exception for unsupported function |
| `illegal_address` | register address was rejected or unavailable |
| `device_failure` | Modbus device failure response |
| `unknown` | fallback for uncategorized transport failures |

## Fake Transport

`FakeModbusTransport` is an in-memory implementation used for tests. It stores
responses and errors by `request_id`, preserves read order and validates that
response word count matches the request quantity.

It is not a serial emulator. It intentionally does not model timing, CRC,
framing, bus contention or retry behavior.

## Acquisition Mapping

`TransportBackedSimulatedModbusRegisterClient` adapts the transport boundary
back into the existing `ModbusRegisterClient` protocol. This allows tests to
run:

```text
FakeModbusTransport
        |
        v
TransportBackedSimulatedModbusRegisterClient
        |
        v
SimulatedModbusAcquisitionService
        |
        v
AcquisitionPipeline
```

Transport failures become `AcquisitionFailure` through the existing acquisition
service:

| Transport code | Acquisition code |
| --- | --- |
| `invalid_response` | `partial_read` |
| `timeout` | `read_failed` |
| `connection_failed` | `read_failed` |
| `illegal_function` | `read_failed` |
| `illegal_address` | `read_failed` |
| `device_failure` | `read_failed` |
| `unknown` | `read_failed` |

This mapping can be refined later without changing the GeoPilot domain model.

## Boundaries

The transport may know about:

- request ids;
- source ids;
- unit ids;
- holding or input register family;
- register address;
- register quantity;
- raw 16-bit words;
- transport-local error categories.

The transport must not know about:

- `Measurement`;
- `RawMeasurement`;
- `Sensor`;
- `DeviceProfile`;
- historian storage;
- snapshots;
- exports;
- alerts;
- HVAC control.

## Constraints

- No mandatory real Modbus RTU implementation.
- No mandatory `pyserial`.
- No serial ports in default tests.
- No hardware I/O in default tests.
- No real SDM120, SDM630 or XY-MD02 profiles.
- No invented register maps.
- No async.
- No threads.
- No retry.
- No scheduler.
- No alerts.
- No HVAC control.

## Validation Coverage

Current tests cover:

- valid read request construction;
- valid raw response construction;
- missing fake response;
- timeout-style absent device;
- short response validation;
- simulated Modbus exception categories;
- no domain dependency in `modbus_transport.py`;
- fake transport integration through acquisition pipeline.

The optional pyserial implementation is tested with an injected fake serial
object only. Those tests do not open a real port.
