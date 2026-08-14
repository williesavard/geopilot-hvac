# Acquisition Results

**Status:** Draft
**Scope:** structured success and failure results for acquisition pipelines

GeoPilot acquisition adapters should report expected read, decode and
normalization outcomes as data. This keeps future hardware adapters from
spreading protocol-specific `try`/`except` handling through the codebase.

This document does not add real Modbus RTU, serial ports, hardware I/O, alerts
or HVAC control.

## Result Model

```text
AcquisitionResult
        |
        +---- AcquisitionSuccess
        |          |
        |          v
        |       Measurement
        |
        +---- AcquisitionFailure
                   |
                   v
              AcquisitionErrorCode
```

Each result carries:

- `source_id`;
- optional `profile_id`;
- optional `register_id`;
- optional `sensor_id`;
- timezone-aware `acquired_at`.

Failures also carry:

- structured `code`;
- readable `message`.

## Current Error Codes

| Code | Meaning |
| --- | --- |
| `read_failed` | simulated or future transport read failed |
| `decode_failed` | register payload could not be decoded |
| `normalization_failed` | raw value could not become a valid measurement |
| `sensor_not_found` | raw measurement targets an unknown sensor |
| `profile_incomplete` | profile is missing required data |
| `partial_read` | only part of a requested read succeeded |
| `unknown_device` | profile or device id is unknown |
| `unknown` | fallback for unexpected adapter-local categories |

Not every code is emitted yet. Some are reserved for the real Modbus adapter
boundary so callers can depend on a stable vocabulary.

## Simulator Flow

The simulator can now run:

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
        +---- AcquisitionSuccess -> Measurement -> historian
        |
        +---- AcquisitionFailure -> structured code and message
```

Successful results write normalized measurements into the configured historian.
Failures do not write to the historian.

## Current Failure Sources

The simulator pipeline currently maps:

- missing simulated payloads to `read_failed`;
- register decode errors to `decode_failed`;
- unknown sensors to `sensor_not_found`;
- incompatible units or invalid raw values to `normalization_failed`.

## Constraints

- No changes to the domain model.
- No real Modbus RTU.
- No serial ports.
- No pyserial dependency.
- No hardware I/O.
- No alerts.
- No HVAC control.
