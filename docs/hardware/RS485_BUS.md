# RS485 Bus

**Status:** Draft / Planned
**Scope:** wiring guidance for future Modbus RTU acquisition

## Objective

Document the RS485 bus conventions GeoPilot intends to use for read-only
Modbus RTU bench and pilot hardware.

## Topology

Use a line topology, also called daisy chain.

```text
USB-RS485
   |
   +---- Device 1
          |
          +---- Device 2
                 |
                 +---- Device 3
```

Avoid star wiring.

```text
          +---- Device 1
USB-RS485 +---- Device 2      Not recommended
          +---- Device 3
```

## Termination

Install 120 ohm termination at the two physical ends of the RS485 trunk when
required by the bus length and speed.

```text
[120R] ---- Device 1 ---- Device 2 ---- Device 3 ---- [120R]
```

Bench wiring may work without termination at short lengths, but production
documentation should not rely on that behavior.

## Polarization

Biasing resistors may be required so the bus has a defined idle state. Whether
external bias is needed depends on the adapter, gateway and connected devices.

Status: `TBD`.

## Shielding

Use shielded twisted pair for field wiring.

```text
Pair 1: RS485 A / RS485 B
Shield: bonded according to cabinet grounding plan
```

Grounding details must be reviewed for the specific installation. Avoid
creating ground loops.

## Length and speed

| Parameter | Starter recommendation | Status |
| --- | --- | --- |
| Baud rate | 9600 baud first | Under evaluation |
| Alternative baud rate | 19200 baud after stable bench tests | Planned |
| Maximum length | TBD | À confirmer |
| Data format | 8 data bits, no parity, 1 stop bit when device docs match | Under evaluation |

Do not claim a maximum cable length until it is validated against the selected
adapter, cable and devices.

## Common errors

- Reversing A and B lines.
- Mixing star wiring with long cable runs.
- Missing common reference where the device requires one.
- Using unshielded cable in noisy electrical cabinets.
- Duplicate Modbus slave addresses.
- Mismatched baud rate, parity or stop bits.
- Assuming every vendor labels A/B polarity the same way.

## Bench checklist

- [ ] Confirm every device address before connecting all devices.
- [ ] Test one device at a time.
- [ ] Record baud rate and serial format.
- [ ] Add devices incrementally.
- [ ] Verify termination only after topology is known.
- [ ] Keep low-voltage RS485 wiring separated from mains wiring.

## Future Work

- Add validated cable length guidance.
- Add oscilloscope or analyzer examples after the bench exists.
- Add SVG diagrams after ASCII diagrams are reviewed.
