# GeoPilot Pro BOM

**Status:** Planned / Under evaluation
**Scope:** expanded pilot hardware for permanent-readiness research

## Objective

Define a more complete hardware set for future GeoPilot pilots that need
three-phase power, industrial temperature probes, flow and pressure signals.

This BOM is not required for the MVP and does not imply that any adapter has
been implemented.

## Pro bill of materials

| ID | Component | Manufacturer | Reference | Role | Qty | Estimated cost | Status |
| --- | --- | --- | --- | --- | ---: | ---: | --- |
| GP-MET-010 | Three-phase energy meter | Eastron | SDM630 Modbus variant | Electrical power and energy | 1 | TBD | Under evaluation |
| GP-SEN-010 | Temperature probe | TBD | PT1000 probe | Loop or pipe temperature | 2-6 | TBD | Planned |
| GP-TXM-010 | Modbus temperature transmitter | TBD | PT1000 to Modbus transmitter | Convert RTD readings to RS485 | 1-3 | TBD | Planned |
| GP-FLO-010 | Flow meter | TBD | Modbus or pulse output | Loop flow observation | 1 | TBD | Planned |
| GP-PRS-010 | Pressure sensor | TBD | Modbus or 4-20 mA via transmitter | Loop pressure observation | 2 | TBD | Planned |
| GP-GWY-010 | Modbus TCP gateway | Moxa, Advantech, ICP DAS or equivalent | TBD | Optional RS485 to Ethernet bridge | 1 | TBD | Planned |
| GP-ENC-010 | Larger DIN enclosure | TBD | TBD | Permanent pilot cabinet | 1 | TBD | Planned |

## Recommended boundaries

- Keep acquisition read-only.
- Prefer passive observation over inline control components.
- Use isolated gateways for field buses where practical.
- Keep Modbus TCP gateways optional; the local-first core must not require
  external cloud services.

## Pro vs Starter

| Area | Starter | Pro |
| --- | --- | --- |
| Power metering | SDM120 candidate | SDM630 candidate |
| Temperature | XY-MD02 ambient module | PT1000 probes with transmitters |
| Flow | Not included | Planned |
| Pressure | Not included | Planned |
| Gateway | USB-RS485 | Optional Modbus TCP gateway |
| Installation | Bench | Pilot cabinet |

## Future Work

- Select candidate PT1000 transmitters.
- Select candidate flow and pressure sensors.
- Define approval tests before marking any component `Approved`.
