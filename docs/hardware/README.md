# GeoPilot Hardware Reference

**Version:** 0.2.0
**Status:** Draft
**Scope:** Read-only GeoPilot MVP hardware planning

## Objective

This directory defines the first official GeoPilot hardware documentation set.
It prepares the future Modbus RTU acquisition layer without claiming that any
hardware adapter exists today.

GeoPilot hardware documentation follows the product principles:

- local-first operation;
- read-only MVP;
- protocol-agnostic domain model;
- no HVAC control;
- no AI, diagnostics or optimization in hardware docs;
- no mandatory Home Assistant, ESPHome, MQTT or BACnet dependency.

## Table of contents

- [Hardware philosophy](#hardware-philosophy)
- [Reference architecture](#reference-architecture)
- [Hardware levels](#hardware-levels)
- [Validation status](#validation-status)
- [Documents](#documents)
- [Conventions](#conventions)
- [Future Work](#future-work)

## Hardware philosophy

GeoPilot treats hardware as an acquisition boundary. Field devices, meters and
sensors may speak Modbus RTU, pulses, analog signals or other protocols later,
but they must translate into GeoPilot's normalized domain objects.

The hardware layer must not redefine:

- the data model;
- the internal API contracts;
- measurement ids;
- historian behavior;
- current-state projection rules.

For the MVP, hardware is read-only. Relays, writes to field devices, equipment
control and optimization loops are outside the supported scope.

## Reference architecture

```text
HVAC equipment and sensors
        |
        |  Planned: RS485 / Modbus RTU read-only acquisition
        v
Local acquisition node
        |
        |  Future adapter boundary
        v
GeoPilot domain model
        |
        +---- in-memory ingestion
        +---- in-memory historian
        +---- current-state snapshot
```

No document in this directory means that a production adapter has been
implemented. Hardware marked `Planned`, `Under evaluation` or `TBD` remains
documentation only.

## Hardware levels

| Level | Purpose | Status |
| --- | --- | --- |
| Starter | Bench validation with low-cost RS485 and Modbus devices | Under evaluation |
| Recommended | More complete pilot with energy, temperature, flow and pressure instrumentation | Planned |
| Industrial | Higher durability components for permanent installations | Future Work |

## Validation status

Use these status values consistently:

| Status | Meaning |
| --- | --- |
| Planned | intended direction, not implemented or validated yet |
| Under evaluation | candidate hardware or convention under review |
| Approved class | acceptable component class, exact part still unvalidated |
| Approved | exact component validated for the documented use case |
| TBD | intentionally unknown or not yet sourced |
| Not MVP | future work, not required for the read-only MVP |

At v0.2, no hardware component is marked `Approved`.

## Documents

### Bill of materials

- [GeoPilot Starter BOM](GEOPILOT_STARTER_BOM.md)
- [GeoPilot Pro BOM](GEOPILOT_PRO_BOM.md)
- [Procurement Guide](PROCUREMENT.md)

### RS485 and Modbus planning

- [RS485 Bus](RS485_BUS.md)
- [Modbus Addressing](MODBUS_ADDRESSING.md)
- [Register Maps](REGISTER_MAPS.md)

### Electrical and installation planning

- [Power Supply](POWER_SUPPLY.md)
- [Test Bench](TEST_BENCH.md)
- [Wiring Diagrams](WIRING_DIAGRAMS.md)
- [Sensor Placement](SENSOR_PLACEMENT.md)

### Device notes

- [Eastron SDM120](SDM120.md)
- [Eastron SDM630](SDM630.md)
- [XY-MD02](XY_MD02.md)
- [PT1000](PT1000.md)
- [Future Supported Devices](FUTURE_SUPPORTED_DEVICES.md)
- [Hardware Source References](SOURCE_REFERENCES.md)

### Legacy v0.1 references

The v0.1 documents remain available for traceability:

- [Core BOM](BOM-Core.md)
- [Development BOM](BOM-Development.md)
- [Installation BOM](BOM-Installation.md)
- [Approved Vendor List](Approved-Vendor-List.md)
- [Procurement Guide v0.1](Procurement-Guide.md)

## Untracked local records

Two files describe a specific residence rather than candidate hardware, and are
excluded by `.gitignore`:

| File | Contents |
| --- | --- |
| `docs/hardware/SITE.md` | The actual installation: equipment, loops, controls, measurements, symptoms |
| `docs/hardware/BENCH_NOTES.md` | Results of manual bench sessions, including adapter serial numbers |

`CONTRIBUTING.md` forbids committing precise locations, equipment serial numbers
or household telemetry. These files necessarily contain some of that, so they
stay on the owner's machine. Documents elsewhere in this repository may refer to
them by path; those references resolve only for someone who has the files.

## Conventions

- Use UTC timestamps in software-facing examples.
- Use Celsius as the canonical temperature unit in GeoPilot software.
- Use watts as the canonical power unit in GeoPilot software.
- Use RS485 address conventions from
  [Modbus Addressing](MODBUS_ADDRESSING.md) for examples.
- Mark every unverified technical value as `TBD` or `À confirmer`.
- Cite official manufacturer documentation when a register, range, accuracy or
  electrical limit is documented.

## Future Work

- Add validated SVG wiring diagrams.
- Attach official datasheets or stable manufacturer URLs for every device.
- Move component status from `Under evaluation` to `Approved` only after bench
  evidence exists.
- Create implementation cards for future Modbus RTU adapters after this
  documentation is reviewed.
