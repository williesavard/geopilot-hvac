# Modbus Addressing

**Status:** Draft / Planned
**Scope:** GeoPilot convention for future read-only Modbus RTU examples

## Objective

Define a stable address convention so GeoPilot examples, wiring diagrams and
future adapter tests use consistent Modbus slave ids.

This convention is not an implementation and does not configure devices by
itself.

## Address ranges

| Range | Purpose | Example |
| --- | --- | --- |
| 1-9 | meters and gateways | SDM120, SDM630 |
| 10-19 | temperature sensors | loop and air temperature |
| 20-29 | humidity sensors | indoor or return-air humidity |
| 30-39 | flow devices | loop flow meter |
| 40-49 | pressure devices | loop pressure sensors |
| 50-99 | reserved for future read-only devices | TBD |
| 100-247 | site-specific expansion | TBD |

## Starter convention

| Address | Device role | Candidate device | Status |
| ---: | --- | --- | --- |
| 1 | single-phase energy meter | SDM120 | Under evaluation |
| 2 | three-phase energy meter | SDM630 | Planned |
| 10 | loop entering temperature | XY-MD02 or PT1000 transmitter | Planned |
| 11 | loop leaving temperature | XY-MD02 or PT1000 transmitter | Planned |
| 20 | humidity | XY-MD02 | Under evaluation |
| 30 | flow meter | TBD | Planned |
| 40 | pressure sensor | TBD | Planned |

## Rationale

- Low addresses are easy to inspect during bench work.
- Meters are separated from environmental sensors.
- Temperature sensors get a contiguous range because they are likely to be the
  most common sensor type.
- Future flow and pressure devices have stable reserved ranges.

## Checklist

- [ ] Assign one unique address per RS485 device.
- [ ] Label the physical device with its configured address.
- [ ] Record the address in the installation notes.
- [ ] Keep factory defaults documented before changing them.
- [ ] Do not assume address changes are applied until the device manual confirms
  the process.

## Future Work

- Add a site address sheet template.
- Add adapter test fixtures after Modbus RTU code exists.
