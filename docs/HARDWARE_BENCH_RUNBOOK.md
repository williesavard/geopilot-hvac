# Hardware Bench Runbook

**Status:** Draft
**Scope:** manual, non-CI Modbus RTU bench procedure for a local macOS host

This runbook describes how a human operator validates the optional pyserial
Modbus RTU transport against real hardware, step by step, outside continuous
integration.

It is a procedure, not a feature. It does not add code, tests, real device
profiles or register maps. It does not authorize Modbus writes, HVAC control,
alerts or automated polling. Nothing in this document runs from `pytest`.

Read [PySerial Modbus Transport](PYSERIAL_MODBUS_TRANSPORT.md),
[Real Modbus Readiness Review](REAL_MODBUS_READINESS_REVIEW.md) and
[Test Bench](hardware/TEST_BENCH.md) before starting.

## Safety Rules

These rules apply to every step and override convenience.

- Any mains-voltage wiring, panel work or live electrical measurement must be
  performed by a qualified electrician. GeoPilot documentation does not
  authorize a homeowner or developer to open an electrical panel or wire an
  energy meter to a live circuit.
- Start at the lowest possible energy level. Validate the USB-RS485 adapter
  alone, then low-voltage devices, and only then consider an energy meter.
- Keep the RS485 communication bus and the DC power distribution physically
  separate from any AC measurement wiring, as stated in
  [Test Bench](hardware/TEST_BENCH.md).
- De-energize the bench before changing any wiring. Do not hot-swap RS485
  conductors on a powered bus.
- Never touch SDM120 voltage terminals, and do not assume a meter is
  de-energized because its display is off.
- Work with one device at a time. A bench failure with two unknown devices on
  the bus is not diagnosable.
- Stop the session if anything is unexpected: smoke, heat, a device that
  resets, a bus that only works intermittently, or a reading that changes when
  you touch the wiring. Record the observation and stop.
- If you are unsure whether a step is safe, it is not. Escalate instead of
  improvising.

## Prerequisites

### Hardware Prerequisites

| Item | Purpose | Status |
| --- | --- | --- |
| macOS development host | runs GeoPilot and the bench session | Existing user environment |
| USB-RS485 adapter | serial bridge between host and bus | Under evaluation |
| Low-voltage Modbus RTU device | first live read target | Under evaluation |
| Regulated DC supply for the device | powers the low-voltage device | Under evaluation |
| Twisted-pair conductors for A/B | RS485 signalling | Under evaluation |
| Labels and a bench notebook | records confirmed settings | Required |
| Multimeter | verifies supply polarity and voltage before connection | Recommended |
| SDM120 candidate and qualified electrician | later mains step only | Under evaluation |

No device in this table is `Approved`. Candidate selection follows
[Hardware Reference](hardware/README.md) and
[Hardware Source References](hardware/SOURCE_REFERENCES.md).

### Software Prerequisites

- A local GeoPilot working copy on a task branch.
- Python 3.11 or newer, matching `pyproject.toml`.
- A virtual environment dedicated to bench work, so the optional extra never
  leaks into the default development environment.
- The official manual for every device on the bench, obtained before the
  session. Register addresses used during the bench come from that manual and
  are recorded only in bench notes.

### Information To Collect Before Powering Anything

Record these values first. Do not guess them during the session.

- exact device model and suffix;
- factory default slave id;
- factory default baud rate, parity, stop bits and byte size;
- register family used by the read: holding or input;
- register address and address base convention used by the manual;
- register quantity;
- documented supply voltage and polarity.

If any of these is unknown, mark it `TBD` and stop before connecting the
device.

## Where PySerial Is Actually Required

The `modbus` extra is required to open a real serial port, not to import
GeoPilot code. The transport imports `serial` lazily, inside the code path that
opens the port, so three distinct levels exist.

| Level | Needs the `modbus` extra | Why |
| --- | --- | --- |
| Importing any GeoPilot module, including `modbus_pyserial_transport` | No | `serial` is imported lazily, only when a port is opened |
| Constructing `PySerialModbusTransport` with an injected `serial_factory` | No | the injected fake replaces pyserial entirely; this is what unit tests use |
| Constructing `PySerialModbusTransport` without a factory | Yes | the transport imports `serial` and opens the configured port |

Consequences for bench work:

- Step 1 proves the first level and must pass in an environment without the
  extra.
- CI stays at the first two levels, so no CI job installs pyserial or touches a
  port.
- Only Step 4 onward reaches the third level, and only on the bench.

If a change ever makes a plain GeoPilot import fail without pyserial, the
optional dependency has become mandatory. Treat that as a regression, not as a
bench problem.

## Step 1 - Confirm GeoPilot Works Without The Modbus Extra

The core package must remain installable and importable without serial
dependencies. Verify this in a clean environment before installing anything.

```bash
python3 -m venv .venv-bench-core
source .venv-bench-core/bin/activate
pip install --editable .
python3 -c "import geopilot.modbus_pyserial_transport as t; print(t.calculate_crc(b'\x01\x03\x00\x00\x00\x01'))"
python3 -c "import serial" ; echo "exit status: $?"
deactivate
```

**Expected result:** the GeoPilot import succeeds and prints a CRC value, while
`import serial` fails with `ModuleNotFoundError` and a non-zero exit status.
Importing the transport module does not require pyserial and does not open a
port.

**If the GeoPilot import fails:** the core package has gained a hard serial
dependency. That is a regression. Stop and fix it before any bench work.

## Step 2 - Install The Optional Modbus Extra

Use a separate bench environment.

```bash
python3 -m venv .venv-bench-modbus
source .venv-bench-modbus/bin/activate
pip install --editable ".[modbus]"
python3 -c "import serial; print(serial.__version__)"
```

The extra declares `pyserial>=3.5,<4`. Keep it out of the default development
environment and out of CI.

## Step 3 - Identify The Serial Port On macOS

Connect only the USB-RS485 adapter. No device on the bus yet.

List candidate ports before and after plugging the adapter in, and compare.

```bash
ls /dev/tty.* /dev/cu.*
```

```bash
python3 -m serial.tools.list_ports -v
```

**Expected result:** a new pair of entries appears, typically
`/dev/tty.usbserial-*` and `/dev/cu.usbserial-*`, with a matching vendor and
product id.

Use the `/dev/cu.*` device for GeoPilot bench work. On macOS, `/dev/tty.*`
blocks on carrier detect and is intended for incoming connections.

Record the exact port path, the vendor id, the product id and the adapter's
chipset in the bench notes. The path can change between reboots and between USB
ports; re-confirm it at the start of every session.

**If no new port appears:** the adapter is unpowered, the cable is charge-only,
or the chipset needs a driver. Resolve this before continuing. Do not proceed
with a guessed port path.

## A Faster Path For Steps 4 And 6

`tools/modbus_smoke.py` performs the reads in steps 4 and 6 as one command. See
[Modbus Smoke Tool](MODBUS_SMOKE_TOOL.md).

```bash
python3 tools/modbus_smoke.py --port /dev/cu.usbserial-XXXX \
    --unit-id 1 --register input --address 0 --quantity 1
```

The inline snippets below remain the explicit reference. Use them when the tool
disagrees with expectations, or when you want to see exactly what is being sent.
The tool has never been run against real hardware, so treat the snippets as the
authority until a bench session says otherwise.

## Step 4 - Verify The Transport Without Any Device Connected

This step exercises the framing and error paths against an unpopulated bus. The
adapter is connected to the host; nothing is connected to A/B.

Build a request frame first. This requires no port at all.

```bash
python3 - <<'PY'
from geopilot.modbus_transport import ModbusReadRequest, ModbusRegisterKind
from geopilot.modbus_pyserial_transport import build_read_request_frame

request = ModbusReadRequest(
    request_id="bench-frame-1",
    source_id="bench",
    unit_id=1,
    register_kind=ModbusRegisterKind.INPUT,
    address=0,
    quantity=2,
)
print(build_read_request_frame(request).hex(" "))
PY
```

**Expected result:** a hex frame is printed. Nothing is transmitted.

Then attempt one read against the real, empty bus. Replace the port path with
the value recorded in Step 3. Replace the unit id, register family, address and
quantity with values that will later come from the device manual; for an empty
bus, any valid request is acceptable because no device should answer.

```bash
python3 - <<'PY'
from geopilot.modbus_transport import (
    ModbusReadRequest,
    ModbusRegisterKind,
    ModbusTransportError,
)
from geopilot.modbus_pyserial_transport import (
    PySerialModbusConfig,
    PySerialModbusTransport,
)

config = PySerialModbusConfig(
    port="/dev/cu.usbserial-REPLACE",
    baudrate=9600,
    parity="N",
    stopbits=1,
    bytesize=8,
    timeout=1.0,
)
transport = PySerialModbusTransport(config)
request = ModbusReadRequest(
    request_id="bench-empty-bus-1",
    source_id="bench",
    unit_id=1,
    register_kind=ModbusRegisterKind.INPUT,
    address=0,
    quantity=1,
)
try:
    print(transport.read_registers(request))
except ModbusTransportError as error:
    print("transport error:", error.code, "-", error.message)
PY
```

**Expected result:** a `timeout` transport error. An empty bus has nothing to
answer, and a clean timeout proves the port opens, the frame is written and the
read deadline is honoured.

**If a `connection_failed` error appears instead:** the port path is wrong, the
adapter was unplugged, or another process holds the port. Return to Step 3.

**If any register words are returned:** something is answering on a bus you
believe is empty. Stop and identify it before continuing.

## Step 5 - Validate The USB-RS485 Adapter Alone

Before adding a device, confirm the adapter itself behaves.

- Confirm the adapter enumerates consistently across two unplug/replug cycles.
- Confirm the port path is stable within the session.
- Confirm no other application, terminal or serial monitor holds the port.
- Confirm A, B and ground terminals are identified and labelled.
- Confirm whether the adapter has automatic direction control, or requires
  RTS-based control. Record the answer; a half-duplex adapter that needs manual
  direction control is a known source of unexplained timeouts.
- Confirm whether the adapter provides termination or bias resistors, and
  whether they are switchable.

Record every answer. Add termination or biasing only when observed behavior
requires it, per [RS485 Bus](hardware/RS485_BUS.md).

## Step 6 - Read One Low-Voltage Device

Add exactly one low-voltage Modbus RTU device. No mains device is present at
this step.

Wiring and power sequence:

1. Keep the bench de-energized.
2. Verify the DC supply voltage and polarity with a multimeter, before
   connecting it to the device.
3. Wire A to A, B to B, and the common reference if the device documents one.
4. Power the device.
5. Connect the USB-RS485 adapter to the host last.

Then read the register documented by the device manual, using the values
collected in the prerequisites.

```bash
python3 - <<'PY'
from geopilot.modbus_transport import (
    ModbusReadRequest,
    ModbusRegisterKind,
    ModbusTransportError,
)
from geopilot.modbus_pyserial_transport import (
    PySerialModbusConfig,
    PySerialModbusTransport,
)

config = PySerialModbusConfig(
    port="/dev/cu.usbserial-REPLACE",
    baudrate=9600,
    parity="N",
    stopbits=1,
    bytesize=8,
    timeout=1.0,
)
transport = PySerialModbusTransport(config)
request = ModbusReadRequest(
    request_id="bench-device-1",
    source_id="bench",
    unit_id=1,                                   # from the device manual
    register_kind=ModbusRegisterKind.INPUT,      # from the device manual
    address=0,                                   # from the device manual
    quantity=1,                                  # from the device manual
)
try:
    response = transport.read_registers(request)
    print("words:", [hex(word) for word in response.words])
    print("observed_at:", response.observed_at)
except ModbusTransportError as error:
    print("transport error:", error.code, "-", error.message)
PY
```

**Expected result:** raw 16-bit register words and a timezone-aware
`observed_at`. The transport returns raw words only. It does not decode,
normalize, scale, name or store anything.

Do not interpret the words yet. Do not add a scale factor, a unit or a data
type to GeoPilot based on what the number looks like. Interpretation requires
source review, which is the subject of the go/no-go criteria below.

Repeat the read several times and record whether the values are stable, drift
plausibly, or jump. Then repeat with the documented baud rate and parity
alternatives if the first attempt fails, changing one setting at a time.

## Step 7 - SDM120 Procedure

This step is different from every step above, because the SDM120 is an energy
meter intended for a mains circuit.

**Mains warning:** the SDM120 measurement path involves line voltage. Any
mains-voltage wiring, panel work or live electrical measurement must be
performed by a qualified electrician. Do not wire an SDM120 to a live circuit
yourself, and do not treat this runbook as an electrical procedure.

Separate the two connections explicitly:

| Connection | Nature | Who performs it |
| --- | --- | --- |
| RS485 A/B communication | low-voltage signalling | Bench operator |
| Auxiliary or measurement supply | mains voltage | Qualified electrician |
| Current and voltage measurement path | mains voltage | Qualified electrician |

Sequence:

1. Complete Steps 1 through 6 with a low-voltage device first. Do not start
   here.
2. Confirm the exact SDM120 model suffix and its official protocol document.
   [Hardware Source References](hardware/SOURCE_REFERENCES.md) still lists this
   as unresolved.
3. Have the qualified electrician perform all mains-side work, including any
   supply and measurement wiring, and confirm the installation is safe before
   the bench session resumes.
4. Perform only the RS485 read with the same procedure as Step 6, using the
   slave id and register values from the official protocol document.
5. Do not write any register. Do not attempt configuration changes, address
   changes or counter resets through GeoPilot.

If the electrician is not available, the SDM120 step does not happen. There is
no reduced-scope version of this step that a non-electrician may perform on a
live circuit.

## What To Record

Record the following for every session, in the bench notes, not in GeoPilot
runtime code.

### Session Identification

- date and time, with timezone;
- operator name;
- GeoPilot branch and commit;
- Python version and whether the `modbus` extra was installed.

### Bench Configuration

- adapter chipset, vendor id and product id;
- serial port path used;
- baud rate, parity, stop bits, byte size and timeout;
- termination and biasing state;
- cable type and approximate length;
- every device on the bus, with model, suffix and configured slave id.

### Per-Read Results

- request id, unit id, register family, address and quantity;
- the manual reference the address came from;
- raw words returned, in hex;
- `observed_at`;
- transport error code and message when the read failed;
- number of attempts and how many succeeded;
- observed response latency, if measured.

### Interpretation Status

Every recorded value stays `TBD` until source review confirms the data type,
scale factor, word order and unit. Record the raw evidence, not a conclusion.

## Expected Errors And Interpretation

The transport raises `ModbusTransportError` with a structured code. Use this
table during the session.

| Code | Bench meaning | First things to check |
| --- | --- | --- |
| `connection_failed` | the port could not be opened, written or read | port path, adapter unplugged, another process holding the port, missing pyserial |
| `timeout` | nothing answered before the deadline | slave id, baud rate, parity, A/B polarity, device power, empty bus |
| `invalid_response` | something answered, but the frame did not validate | wrong unit id echoed, wrong function code, wrong byte count, CRC mismatch, bus noise, two devices sharing an address |
| `illegal_function` | Modbus exception `0x01` | the device does not support the requested function code |
| `illegal_address` | Modbus exception `0x02` | wrong register address or address base convention |
| `device_failure` | Modbus exception `0x04` | the device reported an internal failure |
| `unknown` | an unmapped Modbus exception code | consult the device manual for the exception code |

Additional interpretation notes:

- A `timeout` on a bus that previously worked usually means power, wiring or
  contention, not software.
- Swapped A/B is the single most common cause of a permanent `timeout` on a
  first bring-up.
- A CRC mismatch reported as `invalid_response` on an otherwise stable bus
  suggests noise, missing termination, or an excessive baud rate for the cable
  length.
- `illegal_address` frequently means an address base mismatch: manuals differ
  on whether addresses are documented one-based or zero-based. Record which
  convention the manual uses, per
  [Modbus Addressing](hardware/MODBUS_ADDRESSING.md).
- A transport error is a bench observation. It is not an
  `AcquisitionFailure`, and it must not be turned into an alert.

## What Is Forbidden

During and after a bench session:

- no Modbus write of any kind, including address or configuration changes
  through GeoPilot;
- no HVAC control;
- no mains wiring by a non-electrician;
- no hardware test in CI, and no bench step reachable from `pytest`;
- no serial port opened by a unit test;
- no `pyserial` dependency added to the mandatory core;
- no real device profile added to `device_profiles.py`;
- no register address, endianess, scale factor, precision or measurement range
  written into GeoPilot from a bench observation alone;
- no claim that a device is supported because one bench read succeeded;
- no untracked prototype directory added or modified as part of bench work;
- no bench-only helper beyond the reviewed `tools/modbus_smoke.py`, and no
  change to it that adds writes, decoding, profiles or scanning.

## Go / No-Go Criteria Before Real Device Profiles

These criteria gate the addition of real SDM120, SDM630 or XY-MD02 profiles to
GeoPilot. They extend the go criteria in
[Real Modbus Readiness Review](REAL_MODBUS_READINESS_REVIEW.md).

### Go

A real profile may be proposed when all of the following are true.

- The exact manufacturer, model and hardware suffix are identified.
- The official protocol document is obtained, versioned and cited in
  [Hardware Source References](hardware/SOURCE_REFERENCES.md).
- Register address, address base convention, function code, register quantity,
  data type, word and byte order, unit and scale factor all come from that
  document, not from a bench guess.
- At least two independent bench sessions read the register successfully and
  produced consistent raw words.
- The decoded value is plausible against an independent reference, such as a
  calibrated instrument or a known load.
- Documented invalid or sentinel values are known, or their absence is
  documented.
- Every bench observation is recorded with the fields listed above.
- The read path remains read-only end to end.
- CI remains hardware-free.

### No-Go

Do not add a real profile if any of the following is true.

- The exact model suffix is unknown.
- The source is a mirror, a forum post or a vendor listing rather than an
  official document, and no official document has been reviewed.
- Word order, byte order or scale factor was inferred by making the number look
  correct.
- Only one bench read succeeded, or the readings were not reproducible.
- The register was found by scanning the address space rather than by reading
  the manual.
- The profile would require a domain model change to carry Modbus-specific
  fields.
- The bench required mains work performed by a non-electrician.

Until the go criteria are met, keep candidate values in
[Register Maps](hardware/REGISTER_MAPS.md) as `TBD` and out of runtime code.

## Future Work

- Recorded sessions live in `docs/hardware/BENCH_NOTES.md`, which also carries
  the session template. That file is deliberately untracked; see below.
- Revise `tools/modbus_smoke.py` after the first bench session. It was written
  before any real hardware existed, so its ergonomics are unproven.
- Add captured-frame fixtures only after source-reviewed register maps exist.
- Add bench photos once the hardware is assembled.
