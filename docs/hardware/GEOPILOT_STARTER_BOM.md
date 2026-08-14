# GeoPilot Starter BOM

**Status:** Draft / Under evaluation
**Scope:** read-only bench hardware for future Modbus RTU adapter work

## Objective

Define the smallest practical GeoPilot hardware bench for validating RS485
wiring, addressing conventions and read-only measurement acquisition.

This BOM is documentation only. It does not mean GeoPilot currently includes a
Modbus RTU adapter.

## Table of contents

- [Starter bill of materials](#starter-bill-of-materials)
- [Estimated total](#estimated-total)
- [Selection checklist](#selection-checklist)
- [Alternatives](#alternatives)
- [Future Work](#future-work)

## Starter bill of materials

| ID | Component | Manufacturer | Reference | Role | Qty | Estimated cost | Status |
| --- | --- | --- | --- | --- | ---: | ---: | --- |
| GP-COM-001 | USB to RS485 adapter | FTDI or equivalent | USB-RS485 cable or adapter | Connect Mac to RS485 bench bus | 1 | TBD | Under evaluation |
| GP-MET-001 | Single-phase energy meter | Eastron | SDM120 Modbus variant | Bench electrical measurement | 1 | TBD | Under evaluation |
| GP-SEN-001 | Temperature/humidity transmitter | Generic XY-MD02 vendor | XY-MD02 | Ambient temperature and humidity | 2 | TBD | Under evaluation |
| GP-PWR-001 | DIN rail DC power supply | MEAN WELL | HDR-30-24 or equivalent | 24 VDC bench power | 1 | TBD | Under evaluation |
| GP-ENC-001 | DIN enclosure | TBD | IP-rated DIN enclosure | Safe bench mounting | 1 | TBD | TBD |
| GP-TER-001 | Terminal blocks | WAGO, Phoenix Contact or equivalent | TBD | Field wiring termination | 10 | TBD | TBD |
| GP-CAB-001 | RS485 cable | Belden or equivalent | Shielded twisted pair | RS485 A/B bus | TBD | TBD | TBD |

## Estimated total

Total estimated cost: `TBD`.

Costs vary by supplier, certification, enclosure quality and region. Do not use
this table as a purchasing approval until [Procurement](PROCUREMENT.md) is
complete for the selected vendors.

## Selection checklist

- [ ] USB adapter identifies as a stable serial device on macOS.
- [ ] RS485 adapter supports two-wire half-duplex operation.
- [ ] SDM120 variant explicitly supports Modbus RTU.
- [ ] XY-MD02 devices expose RS485 terminals and documented addressing.
- [ ] Power supply output voltage matches selected field devices.
- [ ] Terminal blocks separate AC and low-voltage wiring.
- [ ] Shielded twisted-pair cable is available for the RS485 segment.

## Alternatives

| Component | Acceptable alternatives | Notes |
| --- | --- | --- |
| USB to RS485 | Industrial isolated USB-RS485 adapter | Isolation preferred for field work |
| SDM120 | SDM630 for three-phase bench work | Belongs in Pro BOM for most cases |
| XY-MD02 | Industrial PT1000 transmitter | Higher cost, better probe placement |
| MEAN WELL HDR-30-24 | Equivalent certified DIN 24 VDC supply | Verify local electrical certification |

## Future Work

- Add exact part numbers after procurement review.
- Add supplier links for Canada and Europe.
- Add measured compatibility results from the official test bench.
