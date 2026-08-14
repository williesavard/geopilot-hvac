# Real Modbus Readiness Review

**Status:** Draft
**Scope:** architecture readiness review before real Modbus RTU implementation

This review decides whether GeoPilot is ready for a first real Modbus RTU
adapter. It does not implement serial I/O, add `pyserial`, define real device
profiles, claim SDM120, SDM630 or XY-MD02 support, invent registers, or add HVAC
control.

## Current Simulated Chain

GeoPilot can now exercise a complete local acquisition simulation:

```text
DeviceProfile
        |
        v
RegisterDefinition
        |
        v
SimulatedModbusRegisterClient
        |
        v
RegisterDecoder
        |
        v
RawMeasurement
        |
        v
AcquisitionPipeline
        |
        v
AcquisitionRunner
        |
        v
SimulatedPollingRunner
        |
        +---- AcquisitionRunReport
        +---- SimulatedPollingReport
        |
        v
InMemoryMeasurementHistorian
        |
        +---- export_measurements()
        |
        v
CurrentStateProjector -> export_snapshot()
```

This is enough to validate the local software choreography before adding a real
RS485 transport.

## Existing Ports and Interfaces

Current useful boundaries:

| Boundary | Location | Current role |
| --- | --- | --- |
| `DeviceProfile` | `backend/src/geopilot/device_profiles.py` | Declares simulated register mappings |
| `RegisterDefinition` | `backend/src/geopilot/register_decoder.py` | Defines one decoded measurable register |
| `ModbusTransport` | `backend/src/geopilot/modbus_transport.py` | Defines hardware-free raw register transport |
| `PySerialModbusTransport` | `backend/src/geopilot/modbus_pyserial_transport.py` | Optional serial transport behind `ModbusTransport` |
| `ModbusRegisterClient` | `backend/src/geopilot/modbus_simulator.py` | Read-only register client protocol |
| `RegisterDecoder` | `backend/src/geopilot/register_decoder.py` | Converts register payloads to `RawMeasurement` |
| `AcquisitionPipeline` | `backend/src/geopilot/acquisition.py` | Converts raw measurements into structured results |
| `AcquisitionRunner` | `backend/src/geopilot/acquisition_runner.py` | Runs one acquisition plan once |
| `SimulatedPollingRunner` | `backend/src/geopilot/simulated_polling.py` | Runs several plans in deterministic cycles |
| `MeasurementHistorian` | `backend/src/geopilot/historian.py` | Stores normalized measurements |

The most important adapter port already exists:
`ModbusRegisterClient.read_register(definition)`.

The lower-level transport boundary is now also explicit:
`ModbusTransport.read_registers(request)`. It returns raw register words and
does not know about `RawMeasurement`, `Measurement`, historian storage,
snapshots or exports.

An optional pyserial-backed implementation now exists behind this boundary. It
is not active by default, is declared as an optional dependency extra and is
tested with injected fake serial objects rather than real ports.

## Where a Real Client Should Attach

A real Modbus RTU client should first implement the lower-level
`ModbusTransport` protocol behind a new adapter module. A register client can
then adapt that transport to the existing `ModbusRegisterClient` boundary:

```text
RealModbusTransport
        |
        v
ModbusTransport.read_registers()
        |
        v
Transport-backed ModbusRegisterClient
        |
        v
ModbusRegisterClient.read_register()
        |
        v
SimulatedModbusAcquisitionService or successor acquisition service
        |
        v
RegisterDecoder
        |
        v
AcquisitionPipeline
```

The real client may know about:

- serial device path;
- baud rate, parity, stop bits and timeout;
- slave id;
- Modbus function code;
- transport library errors;
- CRC or framing failures;
- response length validation;
- hardware-only bench commands.

The real client must not leak those details into:

- `Measurement`;
- `Sensor`;
- `InMemoryAssetRegistry`;
- `InMemoryMeasurementHistorian`;
- `GeothermalSnapshot`;
- JSON export helpers;
- dashboard, alert or control-facing code.

## Errors Already Covered

The acquisition result vocabulary already includes:

| Code | Current meaning |
| --- | --- |
| `read_failed` | read failed before a raw measurement exists |
| `decode_failed` | register payload could not be decoded |
| `sensor_not_found` | raw measurement targets an unknown sensor |
| `normalization_failed` | raw value or unit could not become a measurement |
| `profile_incomplete` | profile lacks required data |
| `partial_read` | only part of an expected read succeeded |
| `unknown_device` | device or profile id is unknown |
| `unknown` | final fallback for adapter-local failures |

The simulator currently emits the first four categories in tests. The transport
boundary also models timeout, connection failure, invalid response, illegal
function, illegal address, device failure and unknown transport failures without
using a serial port.

## Errors Still Missing or Underspecified

Before real RS485 work, decide how these cases map to `AcquisitionFailure`:

| Real-world case | Likely mapping | Decision needed |
| --- | --- | --- |
| Serial port cannot open | `read_failed` | Include port id in message but not domain |
| Timeout waiting for response | `read_failed` | Decide whether timeout deserves a dedicated code later |
| CRC or framing error | `read_failed` or `decode_failed` | Separate transport framing from register decoding |
| Device absent on bus | `read_failed` or `unknown_device` | Use `unknown_device` only for config/profile absence |
| Modbus exception response | `read_failed` | Preserve function and exception code in adapter context |
| Invalid register address | `read_failed` or `profile_incomplete` | Depends whether address came from config or device response |
| Short response | `partial_read` | Define expected word count checks |
| Wrong word count | `partial_read` or `decode_failed` | Decide where length validation lives |
| Unsupported data type | `profile_incomplete` | Fail before polling when possible |
| Unit incompatible with sensor | `normalization_failed` | Already handled by ingestion |
| Duplicate measurement id | `normalization_failed` or `unknown` | Decide whether historian conflict should become acquisition failure |

No new acquisition error code is required before the first adapter, but the
adapter design must consistently map these cases from structured transport
errors.

## Simulator Limits

The current simulator proves software flow, not electrical or protocol
behavior. It does not cover:

- serial-port open and close lifecycle;
- baud rate, parity or stop-bit configuration;
- RS485 direction control;
- real slave-id discovery or validation;
- real function-code execution;
- CRC calculation or validation;
- Modbus exception responses;
- response timing;
- bus contention;
- retries;
- multi-register word and byte order beyond current simulated decoder support;
- real device quirks.

These limits are intentional. They keep CI hardware-free and keep the domain
model clear.

## Device Profile Status

Only simulated built-in profiles exist today:

- `simulated.power_meter.v1`;
- `simulated.temp_humidity_sensor.v1`.

There are no real profiles for:

- SDM120;
- SDM630;
- XY-MD02;
- PT1000 transmitters.

Do not add real profile objects until exact model variants and source documents
are reviewed. Unknown addresses, units, data types, scale factors, word order,
function codes and precision must stay out of code.

## Official Source Requirements

Before any real SDM120, SDM630 or XY-MD02 profile is added, collect and review:

- exact manufacturer and model identifier;
- exact hardware revision or model suffix if relevant;
- official register map or manufacturer datasheet;
- register address base convention;
- Modbus function code per measurement;
- register quantity per measurement;
- data type;
- byte and word order;
- unit and scale factor;
- valid range and invalid sentinel values if documented;
- citation or file reference stored in GeoPilot docs.

If a value cannot be verified, keep it `TBD` in documentation and out of runtime
profile code.

## Requirements Before Real RS485 Bench Testing

Minimum readiness work before live RS485 bench testing:

- define a `RealModbusSourceConfig` shape outside the domain model;
- add captured-frame fixtures only after source review;
- document the hardware-only command and keep it out of CI;
- confirm no Modbus writes or HVAC control paths are introduced.

Already satisfied by the transport-boundary branch:

- `ModbusReadRequest` carries unit id, register family, address and quantity;
- `ModbusReadResponse` carries raw register words;
- `FakeModbusTransport` covers timeout, invalid response and Modbus-style
  exception categories without hardware;
- transport errors map into `AcquisitionFailure` through the existing
  acquisition service.

Already satisfied by the optional pyserial transport branch:

- `pyserial` is isolated as the `modbus` optional dependency extra;
- import does not require pyserial and does not open a port;
- request frame construction, response parsing and CRC validation are unit
  tested with a fake serial object;
- serial timeout, connection failure, invalid response and Modbus exception
  mappings are covered without hardware.

## Testing Strategy

### Unit Tests Without Hardware

These should remain in CI:

- config validation;
- real client behavior with fake transport objects;
- transport exception to `AcquisitionFailure` mapping;
- register response length validation;
- decoder behavior from explicit register payloads;
- profile-to-register-definition conversion;
- runner and polling behavior with fake or simulated clients.

### Simulated Fixtures

Simulator fixtures should continue to cover:

- successful register reads;
- missing payloads;
- decode failures;
- unknown sensors;
- incompatible units;
- multi-cycle polling reports;
- historian accumulation;
- final snapshot and JSON export.

Captured binary or word fixtures can be added only when the source document
defines how to interpret them.

### Hardware-Only Tests

Hardware-only tests must stay out of default CI. They may cover:

- serial port open and close;
- read-only request to a bench device;
- configured timeout behavior;
- absent-device behavior;
- verified register read against a known bench fixture;
- no-write enforcement.

Hardware tests should require an explicit local command and documented
environment variables. They must not run from `pytest -q` by default.

## Core Boundary

The GeoPilot core stops at normalized, source-attributed measurements and local
read models.

Core may own:

- `Measurement`;
- `Sensor`;
- `RawMeasurement`;
- `MeasurementNormalizer`;
- `AcquisitionResult`;
- `AcquisitionRunner`;
- historian queries;
- snapshot and export read models.

The real Modbus adapter owns:

- serial library selection;
- serial connection lifecycle;
- slave id;
- function code;
- register address;
- timeout and retry behavior;
- Modbus exception responses;
- transport-level diagnostics.

The adapter translates those details into `AcquisitionResult` and
`RawMeasurement`. It must not require the domain model to know Modbus.

## Go Criteria

It is reasonable to start a first real adapter branch when:

- the transport library choice is documented;
- a fake transport can simulate timeout, short response and Modbus exception
  behavior;
- every expected transport failure maps to a structured acquisition failure;
- no real device profile is needed to test the adapter boundary;
- hardware-only tests are explicitly excluded from CI;
- a reviewed hardware bench procedure exists;
- all production paths remain read-only.

## No-Go Criteria

Do not start real adapter implementation if:

- register maps are still guessed;
- real SDM120, SDM630 or XY-MD02 profiles are being added without official
  source review;
- the adapter would require domain model changes for Modbus-specific fields;
- CI would require a USB adapter, RS485 device or serial port;
- write functions or HVAC control are part of the branch;
- timeout, CRC/framing and short-response behavior have no structured failure
  mapping.

## Explicitly Out of Scope

- Real Modbus RTU implementation in this review.
- Mandatory `pyserial` dependency.
- Serial port access in default tests.
- Hardware polling.
- Real SDM120, SDM630 or XY-MD02 register profiles.
- Invented register addresses.
- Modbus writes.
- HVAC control.
- Alerts.
- Scheduler, sleep, async or threads.
- Database or persistence changes.

## Recommendation

GeoPilot now has an optional serial transport isolated behind `ModbusTransport`,
but it is still not ready for direct hardware polling. The next implementation
step should add hardware-only bench commands and source-reviewed fixtures, with
no real device profiles and no CI hardware dependency.
