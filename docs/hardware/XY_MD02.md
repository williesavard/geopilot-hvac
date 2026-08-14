# XY-MD02

**Status:** Under evaluation
**Scope:** candidate RS485 temperature and humidity transmitter

## Objective

Document the XY-MD02 as a low-cost candidate for bench temperature and humidity
testing.

## Source status

The XY-MD02 is sold by multiple vendors and documentation quality varies.

| Source | Status |
| --- | --- |
| Official manufacturer document | TBD |
| Vendor manual mirror | Recognized technical source, not official |
| GeoPilot bench confirmation | TBD |

Recognized technical references:

- <https://manuals.plus/ae/1005001475675808>
- <https://industrialmonitordirect.com/blogs/knowledgebase/c-more-hmi-modbus-rtu-polling-and-xy-md02-sensor-setup>

The XY-MD02 remains a source-risk candidate because the manufacturer and exact
hardware revision are not yet clear. Prefer replacing it with a device that has
a stable official datasheet if bench sourcing cannot resolve this.

## Candidate measurements

Do not treat these register rows as implemented. Register details remain
`À confirmer` until an exact device manual and bench device are selected.

| Measurement | Register | Function | Type | Unit | Scaling | Status |
| --- | --- | --- | --- | --- | --- | --- |
| Temperature | TBD | TBD | TBD | °C | TBD | À confirmer |
| Relative humidity | TBD | TBD | TBD | %RH | TBD | À confirmer |

## Expected GeoPilot mapping

| Device value | GeoPilot sensor kind | Canonical unit |
| --- | --- | --- |
| Temperature | temperature | degC |
| Humidity | relative_humidity | % |

## Installation notes

- Keep away from direct sunlight.
- Avoid drafts that do not represent the measured zone.
- Avoid condensation.
- Confirm supply voltage before wiring.
- Confirm address and baud rate before adding multiple units to the bus.

## Checklist

- [ ] Identify exact vendor and hardware revision.
- [ ] Locate official or bundled manual.
- [ ] Record source status in
  [Hardware Source References](SOURCE_REFERENCES.md).
- [ ] Confirm default address.
- [ ] Confirm baud rate and serial format.
- [ ] Confirm temperature register.
- [ ] Confirm humidity register.
- [ ] Validate signed temperature behavior.

## Future Work

- Add confirmed register table after bench validation.
- Decide whether XY-MD02 remains Starter-only or is replaced by PT1000 for
  pilot installations.
