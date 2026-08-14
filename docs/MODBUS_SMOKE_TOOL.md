# Modbus Smoke Tool

**Status:** Draft
**Scope:** manual, non-CI read-only Modbus RTU check for bench work
**Location:** `tools/modbus_smoke.py`

This tool turns steps 4 and 6 of [Hardware Bench Runbook](HARDWARE_BENCH_RUNBOOK.md)
into one command instead of a pasted snippet. The runbook remains the
procedure; this is only the instrument.

It performs read-only register reads and prints raw words. It does not write
registers, decode values, apply scale factors, name measurements, consult device
profiles, touch the historian, or control HVAC equipment.

## Requirements

The optional `modbus` extra, and a bench prepared per the runbook:

```bash
pip install --editable ".[modbus]"
```

Without the extra the tool refuses cleanly rather than failing obscurely:

```text
error: connection_failed - pyserial is not installed; install geopilot[modbus]
```

## Usage

```bash
python3 tools/modbus_smoke.py \
    --port /dev/cu.usbserial-XXXX \
    --unit-id 1 \
    --register input \
    --address 1 \
    --quantity 2
```

Every bus coordinate is required: `--port`, `--unit-id`, `--register` and
`--address` have no defaults. The runbook forbids guessing any of them, so the
tool refuses to invent one. Serial framing options carry the documented
defaults, 9600 8N1 with a 1 second timeout, and can be overridden.

`--register` accepts only `holding` and `input`. There is no way to express a
write, because the transport boundary defines no write.

`--repeat N` performs N attempts. A failed attempt does not abort the run, so an
intermittent bus shows up as a ratio rather than as a single stack trace, which
is what the runbook asks operators to record.

## Output

```text
request frame : 01 04 00 01 00 02 20 0b
attempt   1 : OK   raw hex [0x00d2 0x0141] raw decimal [210 321] (2.4 ms)
summary       : 1 succeeded, 0 failed, 1 attempted
raw words only. Do not interpret them without a source-reviewed register map.
```

The safety banner goes to standard error, and the report to standard output, so
the report can be redirected into bench notes without the banner.

Failures name the structured transport error code, which maps directly onto the
interpretation table in the runbook:

```text
attempt   1 : FAILED timeout - timed out reading 3 byte(s) (1001.2 ms)
```

Exit codes: `0` all attempts succeeded, `1` a usage or configuration problem,
`2` at least one transport error, including a port that could not be opened.

## Why It Cannot Run In CI

Three independent reasons, by construction rather than by convention:

- `pyproject.toml` restricts pytest collection to `tests/`, and this file lives
  in `tools/`;
- it is not a test module, so nothing collects it;
- every bus coordinate is a required argument, so it cannot run with defaults.

Its testable core accepts an injected serial factory.
`tests/test_modbus_smoke.py` exercises success, timeout, Modbus exception
responses, repeat behavior, usage errors and argument requirements with a fake
serial object. No test opens a real port.

## What Is Not Verified

The one path automated tests cannot cover is the line that opens a real serial
port. Everything above it and below it is tested; the port itself needs
hardware.

This tool was written before the first bench session, so its ergonomics are
unproven against real hardware. Expect to revise it after the session rather than
to trust it.

## Limits

- No scanning. It reads what it is told to read, once or N times.
- No device profiles, no decoding, no units.
- No writes, no configuration changes, no address changes.
- No retry logic, no backoff, no scheduling.
- No mains-side guidance beyond the banner. The runbook owns safety.
