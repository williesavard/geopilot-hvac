# Modbus Write Boundary

**Status:** Draft
**Scope:** the coil write path, implementing tier 3 of
[Control Boundary ADR](CONTROL_BOUNDARY_ADR.md)
**Not wired into the runtime.** Nothing in GeoPilot calls this yet.

This is the first piece of actuation the project has ever had. It exists so that
relay modules on the existing RS485 bus can be operated, and it is deliberately
smaller than what Modbus allows.

## What it can do

One operation: **write a single coil**, function code `0x05`.

That is what a DIN-rail relay module needs. There is no register write, no
multi-coil write, no setpoint write, and no path to a heat pump's own
controller. Tier 4 of the ADR is excluded by the absence of the code that would
implement it, not by a check.

## Read and write are different protocols

```text
geopilot.modbus_transport        ModbusTransport         read_registers()
geopilot.modbus_write            ModbusWriteTransport    write_coil()
```

Two modules, two protocols, no shared object. A build, a deployment or a test
that never constructs a `ModbusWriteTransport` **has no capability to write**.

That is stronger than a configuration flag: there is nothing to turn on. A test
asserts that `modbus_transport.py` neither imports the write module nor contains
the string `write_coil`, so the read path cannot acquire the ability by
accident.

## A write is not confirmed until the device echoes it

Modbus answers a write-single-coil by returning the request byte for byte. This
implementation compares the full response to the frame it sent, and raises
`not_acknowledged` on any difference.

A relay module that answers with a state it did not adopt therefore reads as a
failure rather than as success. For an actuator, believing a write that did not
happen is worse than knowing it failed.

## Error vocabulary

Mirrors the read transport, so a relay that does not answer fails the same way a
sensor that does not answer fails.

| Code | Meaning |
| --- | --- |
| `timeout` | no response before the deadline |
| `connection_failed` | port could not be written or read |
| `invalid_response` | wrong length, or CRC mismatch |
| `not_acknowledged` | device echoed a different state |
| `illegal_function` | Modbus exception `0x01` |
| `illegal_address` | Modbus exception `0x02` |
| `device_failure` | Modbus exception `0x04` |
| `unknown` | any other Modbus exception |

## Sharing one bus

`PySerialModbusWriteTransport` accepts an already-open serial port. Two objects
opening the same device would conflict, and an RS485 segment permits one
transaction at a time regardless, so read and write share a port rather than
competing for one.

`open_serial_port()` in the read transport module is public for that reason.

## Relay state is expressed physically

A request carries `closed: bool`, not a raw value, because the safety rule in
the ADR is stated in physical terms: **the de-energised state must be the
building's existing behaviour**. Code that talks about coil values invites
wiring that talks about something else.

## What is deliberately missing

- **No guard.** Enablement, target whitelist, rate limiting and the command
  audit record are a separate concern and a separate branch. This module
  decides nothing;
- **No runtime wiring.** `runtime.py` does not import this. Acquisition is
  unchanged;
- **No retry.** A failed write is reported, not repeated. Repeating a command to
  a contactor without a policy is how relays chatter.

## Testing

`tests/test_modbus_write.py` injects a fake serial object. No test opens a real
port and no test operates hardware.

Covered: frame construction for both states, successful echo, timeout, wrong
echo, CRC failure, every Modbus exception mapping, short response, port failure,
field validation, and the two structural boundary assertions.

`FakeModbusWriteTransport` records the **sequence** of writes, not only the
final state, because for a relay the order and the count are what matter.

## Before this is ever used on real equipment

1. The wiring must be normally-closed pass-through, per the ADR. Without it,
   nothing else here provides safety.
2. The guard must exist. This module will happily write as fast as it is called.
3. Enough recording must exist to know what the system does unattended.
