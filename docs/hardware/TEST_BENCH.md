# Test Bench

**Status:** Draft / Under evaluation
**Scope:** official GeoPilot hardware lab layout

## Objective

Define the first repeatable hardware bench for future read-only Modbus RTU
adapter development.

No adapter exists yet in GeoPilot. This bench prepares manual validation and
future automated tests.

## Starter bench topology

```text
Mac
 |
 | USB
 v
USB-RS485 adapter
 |
 | RS485 A/B
 v
SDM120 candidate
 |
 v
XY-MD02 candidate
 |
 v
XY-MD02 candidate
```

## Bench roles

| Component | Role | Status |
| --- | --- | --- |
| Mac | local development host | Existing user environment |
| USB-RS485 | serial bridge | Under evaluation |
| SDM120 | meter candidate | Under evaluation |
| XY-MD02 #1 | temperature/humidity candidate | Under evaluation |
| XY-MD02 #2 | second addressed sensor | Under evaluation |

## Safety boundary

The SDM120 candidate is an energy meter and may require connection to an AC
measurement circuit. Any mains-voltage wiring, panel work or live electrical
measurement must be performed by a qualified electrician.

GeoPilot bench validation should start without mains measurement whenever
possible:

- validate the USB-RS485 adapter alone;
- validate low-voltage RS485 communication with non-mains devices first;
- use vendor tools, simulators or captured frames for software development;
- add the SDM120 electrical measurement path only after a safe bench plan is
  reviewed.

The RS485 communication bus and the DC power distribution are separate from any
AC measurement wiring.

## Bring-up sequence

- [ ] Connect only the USB-RS485 adapter.
- [ ] Confirm serial device path on macOS.
- [ ] Connect one low-voltage Modbus device.
- [ ] Confirm device address and baud rate with a manual tool.
- [ ] Add the second device.
- [ ] Add the SDM120 communication connection only after the RS485 bus is
  stable.
- [ ] Have a qualified electrician handle any SDM120 mains measurement wiring.
- [ ] Add termination or biasing only when required by observed behavior.
- [ ] Record every confirmed setting in the bench notes.

## Expected future tests

Future software tests may use captured frames or a simulator before touching
real hardware. Do not make CI depend on physical devices.

## Future Work

- Add bench photos or SVG once hardware is assembled.
- Add a repeatable manual validation checklist.
- Add non-CI hardware test scripts in a future branch.
