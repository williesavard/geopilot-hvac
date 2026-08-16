# Modbus Bit Boundary

**Status:** Draft
**Scope:** reading discrete inputs and coils, read-only
**Not wired into the runtime.** See the domain gap below, which blocks it.

Register reads answer "how warm is the loop". Bit reads answer "is zone 1
calling", which is the measurement that tests whether zoning is behind the
high-pressure lockouts.

## Two tables, one boundary

| Kind | Function | What it is |
| --- | --- | --- |
| `discrete_input` | `0x02` | A signal the device only reports, such as a thermostat call |
| `coil` | `0x01` | A state the device can also be told to adopt |

Reading **coils** matters more than it looks. The command guard deliberately
never caches where a relay is, because assuming a contact is where you left it
is how a controller and a building drift apart. Reading the coil back is the
answer to that: ask the device instead of remembering.

## Bit unpacking

Modbus packs eight bits per byte, **least significant bit first**, and pads the
final byte with zeros.

```text
payload 0x05, quantity 4  ->  (True, False, True, False)
```

The padding is not data. Requesting three bits returns three, not eight, so a
padded zero never reads as an input that is off.

## Where this fits

`ModbusBitTransport` is a **third read protocol**, alongside the register
transport and separate from the write transport:

```text
ModbusTransport         read_registers()   16-bit words
ModbusBitTransport      read_bits()        booleans
ModbusWriteTransport    write_coil()       separate module, separate capability
```

Adding `read_bits()` to the existing `ModbusTransport` protocol would have
broken every implementation that satisfies it today, so bits got their own
protocol. Reads staying in one module while writes stay in another preserves the
separation that matters: capability, not shape.

The pyserial implementation accepts an already-open serial port, so all three
share one physical bus.

## The domain gap that blocks ingestion

GeoPilot cannot yet store the fact that zone 1 is calling. Four things stand
in the way:

- `Measurement.value` is numeric and **explicitly rejects booleans**;
- `SensorMeasurementKind` knows temperature, relative humidity and power. There
  is no discrete or state kind;
- the normalizer accepts `degC`, `°C`, `degF`, `°F`, `%`, `W` and `kW`. There is
  no unit for a state;
- `EquipmentState` exists but describes equipment operational states, not an
  arbitrary binary signal from a thermostat.

Encoding a zone call as `1.0 W`, or inventing a `bool` unit inside this adapter,
would be exactly the improvisation this project forbids elsewhere for register
addresses. So the transport stops at the boundary and the decision is left
where it belongs.

**This needs a domain decision before bits can be ingested**, most likely a new
sensor kind and a canonical unit for discrete states, with pass-through
normalization. That is a change to `domain.py` and `ingestion.py`, which is an
ADR, not an adapter detail.

## Testing

`tests/test_modbus_bits.py` injects a fake serial object. No test opens a real
port.

Covered: bit order, padding, byte boundaries, both function codes, a four-zone
read, reading coils back, timeout, wrong byte count, wrong unit, wrong function,
CRC failure, every Modbus exception mapping, quantity limits, non-boolean
rejection, and the fake transport.

## Limits

- read-only. Writing coils lives in `modbus_write.py` and is a separate
  capability;
- no register-and-bit batching. Each request is its own transaction, which is
  what a half-duplex RS485 segment permits anyway;
- no ingestion, pending the domain decision above.
