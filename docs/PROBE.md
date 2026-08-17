# Live Probe

**Status:** Implemented
**Scope:** reading configured sensors from the hardware on demand, recording nothing

[Connectivity](CONNECTIVITY.md) infers what is connected from the recording. That
makes it free and makes it a poll interval stale, which is the wrong loop for
somebody holding a screwdriver: strip, connect, wait, refresh, guess again.

A probe goes to the device instead.

```bash
python3 tools/geopilot_probe.py --config /etc/geopilot/installation.toml
```

```text
what                           kind           reading  reference / note
 sensor_tank                   onewire      21.1 degC  28-0119a1b2c3d4
 28-0119aabbccdd               onewire      4.25 degC  on the bus, not in the configuration
!28-0119eeff0011               onewire              —  the probe answered with its 85 C power-on
                                                       reset value: check the pull-up and the supply
!sensor_loop_in                onewire              —  28-0119deadbeef · device_not_found

1 device(s) are on the bus but not in the configuration:
  28-0119aabbccdd
copy the ids into [[onewire_read]] entries to start recording them

2 of 4 did not answer cleanly (marked !)
```

Exit 0 when everything answered cleanly, 2 when anything did not. That makes it
usable from a script as well as by eye.

There is a button on the served page too — see [Control Surface](CONTROL_SURFACE_ADR.md) —
which works whether or not control is enabled. Probing is a read.

## 1-Wire discovers; Modbus verifies

These are genuinely different, and the difference is not an inconsistency.

**1-Wire lists every probe the kernel can see**, whether the configuration
mentions it or not. That is the answer to the question every 1-Wire installation
starts with: three identical probes on one cable and no way to tell which id is
which. Probe, warm one in your hand, probe again — **the one that moved is the
one you are holding.** Then copy its id into the configuration.

**Modbus reads what the configuration claims is there.** Nothing sweeps the bus
looking for devices. A sweep means addressing units nobody has confirmed exist,
on a segment shared with equipment that controls a house, and that is a different
tool with different risks — not a side effect of a refresh button.

## What it tells you that a reading alone does not

**85.000 °C exactly is not a temperature.** It is a DS18B20 that powered up and
was read before it finished converting, and it almost always means a data line
without a proper pull-up or parasite power that cannot supply the conversion. The
1-Wire adapter already refuses to record it — which is right — and the probe adds
the half that matters with a screwdriver in hand: what to go and check.

**A device that is present but not ready is a different fault from one that is
absent.** Both fail; they are marked differently, because they send you to
different places.

**Negative register values are decoded as signed.** A loop at −5 °C reads as
0xFFCE, which unsigned is 6553.4 °C. Getting `int16` versus `uint16` wrong in the
configuration is a mistake that only shows up in winter, and this shows it now.

**A configured quantity the declared type cannot hold is refused, not guessed.**
Two words presented as an `int16` produce no value and say so.

**Offsets and inversion are applied exactly as the runtime applies them**, so a
probe and a recorded reading never disagree about the same sensor.

## Port contention, and what is not done about it

The acquisition timer opens the same serial port every minute. So does the
control surface, per command. Now so does this.

**Nothing here retries.** A probe that reports a busy bus is a probe you press
again, which is more honest than a loop that hides how often the port was taken.
At a one-minute poll taking a fraction of a second, a collision is rare.

An advisory lock — `flock` on a file keyed to the port — would make the three
serialise properly instead of one of them failing. It is not here because it
would mean changing the acquisition path, which is the one thing that must not
break and the one thing that cannot be tested without the real hardware. It is
the right fix if collisions turn out to be more than a nuisance, and it should be
made deliberately rather than smuggled in behind a button.

## What it does not do

**It records nothing.** A probe is not a measurement; it never reaches the
historian, so probing cannot pollute the record you are building.

**It does not judge plausibility, beyond the reset sentinel.** A probe reading
4 °C when it is sitting on a warm bench is connected and wrong, and nothing here
will say so.

**It does not sweep, scan or discover Modbus devices.** See above.

## Testing

`tests/test_probe.py`.

No test opens a serial port, and the 1-Wire tests point at a fixture directory
tree rather than a Raspberry Pi, so none of them needs Linux.

Covered: every probe on the bus listed whether configured or not, readings coming
back keyed by id so the hand-warming trick works, the configured offset applied,
a configured probe that is absent, the reset sentinel named as a wiring fault and
distinguished from silence, 84.9 °C not being mistaken for the sentinel, signed
register decoding, a busy port reported rather than retried, a quantity the type
cannot hold being refused, inversion applied as the runtime applies it, and every
transport failure arriving as a result rather than an exception.

`tests/test_control_server.py` covers the endpoint: the token being required,
probing working while control is disabled, and a prober that raises becoming an
answer rather than a crash.
