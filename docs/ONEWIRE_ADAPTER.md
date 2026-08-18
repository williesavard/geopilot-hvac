# 1-Wire Adapter

**Status:** Draft
**Scope:** DS18B20 temperature probes through the Linux 1-Wire sysfs interface

This is GeoPilot's second acquisition adapter, alongside Modbus RTU. It exists
because pipe temperatures are the measurement this project most needs, and a
DS18B20 costs a tenth of a Modbus RTD transmitter while sitting a metre from the
pipe.

It reads probes. It writes nothing, schedules nothing, and does not import the
historian, the snapshot or any read model. A test enforces that on the import
graph rather than on the text.

## Why sysfs rather than bit-banging GPIO

The kernel already owns the 1-Wire timing, the CRC and the bus enumeration.
Reimplementing that in Python, on a machine that is also running a database,
would be slower, less correct, and pointless.

Probes appear as directories under `/sys/bus/w1/devices`, named by their ROM
id:

```text
/sys/bus/w1/devices/28-0000075b2c3f/w1_slave
```

That id is unique and stable per probe, which makes it a natural key. It maps
directly onto a GeoPilot sensor in configuration.

## What it validates

The kernel exposes two lines:

```text
5b 01 4b 46 7f ff 0c 10 4f : crc=4f YES
5b 01 4b 46 7f ff 0c 10 4f t=21687
```

| Condition | Result |
| --- | --- |
| First line ends in `YES` | Reading accepted |
| First line ends in `NO` | `crc_failed`, mapped to `decode_failed` |
| `t=85000` exactly | `power_on_reset`, rejected |
| No `t=` field | `invalid_response` |
| Fewer than two lines | `invalid_response` |
| Device directory absent | `device_not_found`, mapped to `read_failed` |

### The 85 degree sentinel

A DS18B20 reports **exactly 85.0 C** after a power-on reset when no conversion
has completed. It is a sentinel, not a temperature. Storing it as data is how a
mechanical room acquires a fictional heat wave in its history, months before
anyone notices.

Only the exact value is rejected. A genuine 84.999 C is accepted, because
rejecting a range would discard real readings from a system that can legitimately
run hot.

## Calibration is the point

`offset_celsius` carries a per-probe correction, and it is not optional in
practice.

A ground loop delta T is a few degrees. Two probes each accurate to ±0.5 C can
therefore be wrong by ±1 C on a 4 C delta, which is a 25 % error on the single
most informative number in a geothermal system.

The fix costs nothing: put every probe in the same glass of water, record what
each one reads, and enter the difference as its offset. The probes become
excellent **relative to each other**, which is exactly what a delta T needs.

Do this before installation, and again once a year.

## Configuration

```toml
[[onewire_source]]
id = "source_probes"
root = "/sys/bus/w1/devices"

[[onewire_read]]
id = "read_loop_in"
source_id = "source_probes"
sensor_id = "sensor_loop_in_probe"
device_id = "28-0000075b2c3f"
unit = "degC"
offset_celsius = -0.12
source_reference = "same-bath calibration 2026-08-11"
```

A source id cannot be shared between a serial source and a 1-Wire source, and
that collision is rejected at load time.

`source_reference` is required, as it is for Modbus reads. For a probe it
records which calibration produced the offset.

## Running Both Protocols

One acquisition cycle reads every configured source, Modbus and 1-Wire alike.
Each source contributes one request to the plan, and a failure in one does not
prevent the others from being read.

```bash
python3 tools/geopilot_poll.py --config installation.toml --interval 30
```

## Discovering Probes

`SysfsOneWireBus.available_devices()` lists probe ids present on the bus, which
is what a bench session needs before writing any configuration. It returns an
empty tuple when no bus exists, rather than raising, so it is safe to call on a
machine that has no 1-Wire hardware.

## Testing

The sysfs root is injectable. `tests/test_onewire.py` builds a fixture tree in
`tmp_path`, so the suite runs on macOS with no Raspberry Pi, no probe and no
kernel module.

Covered: normal and negative readings, CRC failure, the 85 C sentinel and the
value just below it, malformed payloads, absent devices, probe discovery, offset
application, and the import boundary.

## Limits

- Linux only. The sysfs interface does not exist elsewhere, which is correct
  since the target is a Raspberry Pi;
- no parasite-power handling, no bus scanning, no probe resolution configuration;
- no conversion triggering. Reading `w1_slave` blocks while the kernel performs
  the conversion, roughly 750 ms at 12-bit resolution. With several probes on
  one bus, a cycle takes that long per probe;
- reads are sequential. A bus with many probes will want batching before the
  cycle time matters.

## Future Work

- Measure real cycle time with several probes before choosing a polling
  interval.
- Consider lowering resolution if 750 ms per probe becomes the constraint.
- Record calibration offsets in the bench notes, alongside the date.

## Measuring the offset

`offset_celsius` is measured, not guessed: put every probe in one stirred
bath and run `tools/geopilot_calibrate.py`. Two DS18B20 probes can sit a
full degree apart and both be within specification, which would make half
of a two-degree loop delta noise. See [Calibration](CALIBRATION.md).
