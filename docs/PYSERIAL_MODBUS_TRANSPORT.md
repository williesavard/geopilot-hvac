# PySerial Modbus Transport

**Status:** Draft
**Scope:** optional Modbus RTU transport implementation behind `ModbusTransport`

This document describes the first real serial transport implementation boundary.
It is optional, read-only and confined to
`backend/src/geopilot/modbus_pyserial_transport.py`.

It does not add real device profiles, invent SDM120, SDM630 or XY-MD02
registers, run hardware tests in CI, retry automatically, schedule polling,
emit alerts or control HVAC equipment.

## Installation

The core GeoPilot package remains installable without serial dependencies.

Install the optional Modbus extra only when local serial transport work is
needed:

```bash
pip install "geopilot[modbus]"
```

The extra declares:

```text
pyserial>=3.5,<4
```

Importing the pyserial transport module does not require `pyserial`. A serial
port is opened only when `PySerialModbusTransport` is instantiated without an
injected serial factory.

## Configuration

`PySerialModbusConfig` requires explicit serial settings:

- `port`;
- `baudrate`;
- `parity`;
- `stopbits`;
- `bytesize`;
- `timeout`.

No defaults are read from the environment, no port is guessed and no test opens
a real port.

## Transport Flow

```text
ModbusReadRequest
        |
        v
PySerialModbusTransport
        |
        v
Modbus RTU request frame
        |
        v
serial.write() / serial.read()
        |
        v
ModbusReadResponse
```

The transport returns raw register words only. It does not know about
`Measurement`, `RawMeasurement`, sensors, device profiles, historian storage,
snapshots or exports.

## Supported Reads

The implementation supports minimal read-only RTU frames for:

- holding registers through function code `0x03`;
- input registers through function code `0x04`.

It builds request frames from:

- unit id;
- register family;
- register address;
- register quantity.

It parses responses into raw 16-bit register words.

## CRC

The transport calculates and validates Modbus RTU CRC-16. Tests include known
request-frame vectors and response CRC validation.

## Error Mapping

Serial and Modbus failures become `ModbusTransportError` values:

| Case | Error code |
| --- | --- |
| missing response bytes | `timeout` |
| serial read/write exception | `connection_failed` |
| short response | `invalid_response` |
| wrong unit id | `invalid_response` |
| wrong function code | `invalid_response` |
| wrong byte count | `invalid_response` |
| CRC mismatch | `invalid_response` |
| Modbus exception `0x01` | `illegal_function` |
| Modbus exception `0x02` | `illegal_address` |
| Modbus exception `0x04` | `device_failure` |
| other Modbus exception | `unknown` |

The acquisition layer can map these transport errors to `AcquisitionFailure`
through the existing transport-backed register client.

## Testing Boundary

Unit tests inject a fake serial object. They do not open `/dev/*`, `COM*` or any
other real port.

CI tests cover:

- import without `pyserial` installed;
- explicit config validation;
- request frame construction;
- normal holding-register response parsing;
- normal input-register response parsing;
- timeout mapping;
- connection failure mapping;
- invalid response mapping;
- Modbus exception mapping;
- CRC calculation and validation;
- absence of domain, historian and snapshot dependencies.

Hardware-only tests are still out of scope for default CI.

Manual validation against a real RS485 bus follows
[Hardware Bench Runbook](HARDWARE_BENCH_RUNBOOK.md). That procedure is operator
driven, runs outside CI and adds no code, tests or real device profiles.

## Constraints

- No real device profiles.
- No invented registers.
- No SDM120, SDM630 or XY-MD02 support claim.
- No Modbus writes.
- No retries.
- No scheduler.
- No async.
- No threads.
- No alerts.
- No HVAC control.
