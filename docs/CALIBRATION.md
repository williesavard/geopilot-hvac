# Calibration

**Status:** Implemented
**Scope:** measuring the DS18B20 offsets the configuration has always accepted

`offset_celsius` has been in `[[onewire_read]]` since the 1-Wire adapter was
written. What has never existed is a way to find out what to put in it, which
left it a field to guess at or leave at zero.

```bash
python3 tools/geopilot_calibrate.py --config installation.toml \
    --minutes 10 --reference 0.0
```

Nothing is recorded and nothing is written back. It prints lines to paste.

## Why this is not optional here

A DS18B20 is specified to **±0.5 °C**. Two of them can sit a full degree apart in
the same water and both be within specification.

The measurement this installation exists to make is a loop delta of two or three
degrees. **A 2 °C delta read by two probes that disagree by 1 °C is half noise**,
and no amount of careful analysis afterwards recovers it. An hour with a bowl of
ice is the difference between evidence and a number.

Measured on a bench with three probes in one bath:

```text
disagreement before correction: 0.500 degC

probe                  sensor                      mean   spread    noise    offset
 28-0119a1b2c3d4       sensor_tank                0.312    0.000    0.000   -0.3120
 28-0119aabbccdd       sensor_loop_in            -0.188    0.000    0.000   +0.1880
 28-0119eeff0011       —                          0.062    0.000    0.000   -0.0620
```

That 0.500 °C is the error that would have gone into every delta, invisibly,
for a whole winter.

## Agreement or truth — pick one and write it down

**With no reference**, probes are calibrated to their own mean: they end up
agreeing with each other. For a delta that is the right target, because what
matters is that loop-in and loop-out are on the same scale, not that either is
absolutely right.

**With `--reference 0.0`** in an ice bath — crushed ice, a little water, stirred
— they are calibrated to truth. Do this one if you can; it costs a bowl of ice
and it also catches a probe that is simply wrong.

**With `--reference-device`**, everything is calibrated to agree with one probe.
For when one of them is the trusted instrument.

The report names which was used, and says to record it in `BENCH_NOTES.md`. An
offset is only meaningful if the next person knows what it was measured against.

## Settling, and refusing

A probe moved from a pocket into a bath takes minutes to arrive. Sampling during
that time measures the transient, not the offset.

So every probe's **peak-to-peak spread** across the run is reported, and a run in
which anything moved more than 0.25 °C is marked **NOT USABLE** and prints no
offsets at all. Refusing beats writing a confident wrong number into a
configuration file that nobody will revisit for a year.

Peak-to-peak rather than a standard deviation, deliberately: a probe drifting
steadily by half a degree has a small standard deviation and is not settled. The
range catches it; the deviation does not. Both are reported — `spread` decides,
`noise` is there to tell dithering from movement.

Below five samples nothing is judged, because there is no spread worth speaking
of, and the run is refused by name rather than passed.

## Stirring matters more than waiting

Still water stratifies. Probes at different depths then measure a genuine
temperature difference that is not an offset, and calibrating it in makes every
later reading worse.

Stir the bath. If you do not, you have calibrated the temperature gradient of a
glass of water into your configuration file.

## What it does not do

**It does not write the configuration.** It prints lines with the device id in a
comment on each one, because three offsets and three near-identical entries is
exactly how they get swapped. The file stays yours to edit.

**It does not calibrate anything but 1-Wire probes.** A Modbus transmitter has
its own scale and offset in the configuration, and calibrating it means comparing
against a reference this tool has no way to reach.

**It does not correct for self-heating, cable length or a probe's response time.**
It measures where two probes disagree while sitting in the same still conditions,
which is the error that matters for a delta and is not every error there is.

**One probe alone calibrates to itself**, offset zero. That is honest and
useless, and the zero makes it obvious.

## Testing

`tests/test_calibration.py`.

Covered: probes calibrated to their own mean, to a known bath, and to a chosen
probe; the offset being what must be *added* to reach the reference, so it cannot
be applied backwards; a still-settling probe making the whole run unusable while
its neighbour is judged settled; spread being peak-to-peak so a steady drift is
caught where a standard deviation would miss it; too few samples refused by name;
both kinds of reference at once refused; and the pasteable line carrying the
device id it belongs to.
