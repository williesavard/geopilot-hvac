# Commissioning

**Status:** Procedure
**Scope:** from an unopened box to a recording that can be left alone

The configuration says what should exist. This is the order to make it true.

Each step ends with a check that either passes or tells you what to fix. Do not
skip ahead: every step depends on the one before it, and a failure three steps
later is much harder to attribute.

Keep your real configuration in `config/`, which is gitignored. The file under
`examples/` is the one that ships.

## 0. Before anything: does the GPIO header work

**Five minutes, and it can invalidate the whole 1-Wire plan.**

Open the case and confirm the 40-pin header is physically reachable. Some
assembled kits ship with a heatsink, fan or SSD hat over it. If it is blocked,
the DS18B20 probes have nowhere to land and that changes what you buy before it
changes anything else.

## 1. One reading, from one probe

Not six sensors. Not the full configuration. **One.**

Enable the 1-Wire kernel driver:

```bash
echo "dtoverlay=w1-gpio" | sudo tee -a /boot/firmware/config.txt
sudo reboot
```

Wire one DS18B20: data to GPIO4, plus the **4.7 kΩ pull-up between data and
3.3 V**. Without it the probe reads 85.000 °C exactly, which is the power-on
reset value and not a temperature.

```bash
ls /sys/bus/w1/devices/          # expect a 28-… directory
python3 tools/geopilot_probe.py --config config/installation.toml --only onewire
```

**Check:** a plausible room temperature. If it says 85 °C, it is the pull-up.

This is the moment the project stops being plausible and starts being true.

## 2. Learn which probe is which

Three identical probes on one cable, no markings. Plug them all in:

```bash
python3 tools/geopilot_probe.py --config config/installation.toml --only onewire
```

Every id on the bus is listed, including the ones your configuration does not
mention yet. **Warm one probe in your hand and run it again** — the id whose
reading moved is the one you are holding.

Write each id into its `device_id` before taping anything to a pipe. Afterwards
they are indistinguishable and you will be doing this in a crawlspace.

## 3. Calibrate, before installing

All three probes in **one stirred bath**. An ice bath — crushed ice, a little
water — gives absolute truth for the price of a bowl of ice.

```bash
python3 tools/geopilot_calibrate.py --config config/installation.toml \
    --minutes 10 --reference 0.0
```

Paste the printed lines into each `[[onewire_read]]`.

**Check:** the run reports *usable*. If it says NOT USABLE, a probe was still
settling — stir, wait, run it again.

**Do not skip this.** Two DS18B20 can sit a full degree apart in the same water
and both be within specification. The number this installation exists to produce
is a 2–3 °C delta. See [Calibration](CALIBRATION.md).

Record the bath and the date in `docs/hardware/BENCH_NOTES.md`.

## 4. Install the probes

Reuse the existing openings in the pipe insulation where they exist. Good
thermal contact and insulation over the top matter more than probe placement to
the centimetre: a probe reading partly the room instead of the pipe produces a
delta that is quietly too small, which is the same direction as the fault you
are looking for.

```bash
python3 tools/geopilot_probe.py --config config/installation.toml --only onewire
```

**Check:** each probe reads something consistent with where you put it.

## 5. The RS485 device

Work [Hardware Bench Runbook](HARDWARE_BENCH_RUNBOOK.md) step 6 with the device
on the bench, and record what you **observe** in `BENCH_NOTES.md` — not what a
vendor page predicted.

Then fill in the commented-out `[[read]]` entries and uncomment them.

```bash
python3 tools/geopilot_probe.py --config config/installation.toml
```

**Check:** the value is plausible *and* the raw words in the detail column make
sense for it. A scale that is off by ten produces a number that looks fine in
summer and absurd in January.

## 6. Record once, by hand

```bash
python3 tools/geopilot_poll.py --config config/installation.toml --once
python3 tools/geopilot_report.py --database geopilot.sqlite3
```

**Check:** every sensor you expect appears with a count of 1.

## 7. Hand it to systemd

```bash
sudo cp deploy/systemd/geopilot-poll.* /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now geopilot-poll.timer
```

See [Deployment](DEPLOYMENT.md) for the user, the state directory and the
timer's deliberate refusal to fire missed cycles on boot.

**Check, after ten minutes:**

```bash
python3 tools/geopilot_report.py --database /var/lib/geopilot/geopilot.sqlite3
```

The count rises. That is the whole test.

## 8. The first week is the one that matters

Look at the dashboard daily for a week, then weekly.

```bash
python3 tools/geopilot_dashboard.py \
    --database /var/lib/geopilot/geopilot.sqlite3 \
    --config config/installation.toml \
    --output ~/geopilot.html \
    --delta sensor_loop_a:sensor_loop_b
```

**What to look at, in order:**

1. **What is connected** — everything green. A sensor that goes amber in week
   one is a connector, and a connector found in week one is a connector, while
   the same connector found in March is a hole in the record;
2. **the largest gap** — it should be about one poll interval. Anything larger
   is an outage, and you want to know why while you still remember what you
   were doing;
3. **the delta** — is it plausible, does it move with the machine.

A count that stops rising is the failure that matters, and no alert will tell
you.

## What "done" looks like

Recording unattended, gaps under a poll interval, and a delta you would be
willing to show an engineer. Everything after that is patience: the evidence is
made of time, and there is no way to hurry it.

## When something is added later

A meter, a pressure transmitter, a lockout contact — the sequence is the same
from step 5: bench it, source it, configure it, probe it, poll once, then let
the timer have it. Add one thing at a time, and check the connectivity table
after each.
