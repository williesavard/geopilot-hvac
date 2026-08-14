# Modbus RTU Simulator Port

**Status:** Draft
**Scope:** hardware-free client port for simulated Modbus register acquisition

This document describes the first clean client boundary for Modbus-style
acquisition. It does not open serial ports, implement wire-level Modbus RTU,
poll real devices, write registers, or claim hardware support.

## Objective

The simulator port lets GeoPilot test the acquisition chain:

```text
DeviceProfile
        |
        v
simulated register payload
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
MeasurementNormalizer
        |
        v
InMemoryMeasurementHistorian
        |
        +---- JSON export
        |
        v
CurrentStateProjector
```

## Components

### ModbusRegisterClient

`ModbusRegisterClient` is a protocol for read-only register access. The current
implementation has one method:

```text
read_register(definition) -> SimulatedRegisterPayload
```

Future real transports can implement the same boundary behind explicit adapter
configuration. The domain model still never depends on Modbus concepts.

### SimulatedModbusRegisterClient

`SimulatedModbusRegisterClient` is an in-memory implementation used by tests. It
stores `SimulatedRegisterPayload` objects by `register_id` and returns them when
the acquisition service asks for the corresponding `RegisterDefinition`.

It rejects duplicate simulated payloads and missing payloads.

### SimulatedModbusAcquisitionService

The acquisition service reads definitions through a `ModbusRegisterClient`,
decodes each payload through `RegisterDecoder`, and returns `RawMeasurement`
objects.

It preserves definition order so tests can verify deterministic behavior.

It can also run through `AcquisitionPipeline` and return structured
`AcquisitionResult` objects. In that mode, expected read, decode and
normalization failures are returned as `AcquisitionFailure` rather than raw
exceptions.

### DeviceProfile

`DeviceProfile` and `DeviceRegisterProfile` are declarative profile objects that
can produce `RegisterDefinition` values for the simulator port. The current
built-in profiles are simulated only and are documented in
`docs/DEVICE_PROFILES.md`.

## Current Limits

- No serial-port path.
- No pyserial or Modbus library dependency.
- No slave id, function code, retry, timeout or bus scheduling behavior.
- No real register maps.
- No Modbus writes.
- No hardware in CI.

These limits are intentional. The simulator port is a test boundary, not a
production adapter.

## Validation Coverage

The current tests verify:

- simulated reads by register definition;
- duplicate and missing payload rejection;
- deterministic acquisition order;
- full chain from simulated payload to decoder, raw measurement, normalizer,
  historian, JSON export and snapshot.
- structured success and failure results for missing reads, decode errors,
  unknown sensors and incompatible units.
