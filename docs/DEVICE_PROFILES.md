# Device Profiles

**Status:** Draft
**Scope:** declarative simulated profiles for acquisition architecture

Device profiles describe register-like measurement mappings without performing
I/O. They are used to stabilize GeoPilot acquisition architecture before adding
real RS485 hardware.

## Current Boundary

```text
DeviceProfile
        |
        v
DeviceRegisterProfile
        |
        v
RegisterDefinition
        |
        v
ModbusRegisterClient
        |
        v
RegisterDecoder
        |
        v
RawMeasurement
```

Profiles are declarations. They do not open serial ports, poll hardware, write
registers, control HVAC equipment or claim device compatibility.

## Current Built-In Profiles

The first built-in profiles are simulated internal profiles only:

- `simulated.power_meter.v1`
- `simulated.temp_humidity_sensor.v1`

They use `address: None` because they are not real Modbus maps. Their
`source_reference` is `GeoPilot simulated profile`.

## Status Values

| Status | Meaning |
| --- | --- |
| `simulated` | Internal GeoPilot profile for tests and examples |
| `under_evaluation` | Real device profile candidate; source review incomplete |
| `verified` | Real device profile reviewed against exact source and bench evidence |

Only simulated profiles are present in code today.

## Real Device Rule

Do not add SDM120, SDM630, XY-MD02 or PT1000 transmitter register profiles until
the exact model suffix and source document are reviewed.

For real devices:

- unknown addresses stay out of code, not as guessed numbers;
- source references must identify the exact official or reviewed document;
- `under_evaluation` and `verified` profiles require confirmed register
  addresses;
- no register map should imply hardware support until adapter and bench
  validation exist.

## Future Work

- Add source-reviewed fixture profiles after exact manuals are selected.
- Add profile loading from local files only after the in-code profile shape is
  stable.
- Add schema validation if profiles move to external YAML or JSON.
- Keep real Modbus transport behind `ModbusRegisterClient`.
