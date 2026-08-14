# Deployment

**Status:** Draft, **not yet run on real hardware**
**Scope:** running GeoPilot unattended on a Linux host, typically a Raspberry Pi

This document installs the runtime described in
[Acquisition Runtime](ACQUISITION_RUNTIME.md) as a supervised service, so it
records for months without anyone watching.

The unit files in [`deploy/systemd`](../deploy/systemd) were written against the
systemd documentation and have not been executed on a Pi. Expect to correct them
during the first install rather than to trust them.

## Choosing timer or service

Two shapes, both provided. Pick one, not both.

| | Timer + oneshot | Long-running service |
| --- | --- | --- |
| Files | `geopilot-poll.service` + `.timer` | `geopilot-monitor.service` |
| Interval | 1 minute or slower | any, including sub-minute |
| Process | one per cycle | one, always |
| Restart, logging, boot | systemd's job | systemd's job |
| Cost | Python startup per cycle | none |

**Use the timer** unless the interval is below a minute. At 30-second
resolution, starting a Python process 2,880 times a day costs more than the
reading, and the long-running service is the better fit.

## Install

Everything below runs as root on the target host.

### 1. A user that owns nothing else

```bash
useradd --system --home /opt/geopilot --shell /usr/sbin/nologin geopilot
usermod --append --groups dialout geopilot
```

`dialout` grants serial port access on Debian and Raspberry Pi OS. Skip it if
the installation has no Modbus source.

### 2. The code and a virtualenv

```bash
install -d -o geopilot -g geopilot /opt/geopilot
git clone https://github.com/williesavard/GeoPilot.git /opt/geopilot
python3 -m venv /opt/geopilot/venv
/opt/geopilot/venv/bin/pip install --editable "/opt/geopilot[modbus]"
chown -R geopilot:geopilot /opt/geopilot
```

Install the `modbus` extra only if a Modbus source is configured. A 1-Wire only
installation does not need `pyserial`.

### 3. Configuration

```bash
install -d -o root -g geopilot -m 0750 /etc/geopilot
install -o root -g geopilot -m 0640 \
    /opt/geopilot/examples/installation.example.toml \
    /etc/geopilot/installation.toml
```

Edit it, then set the database to an absolute path inside the state directory:

```toml
[storage]
database = "/var/lib/geopilot/geopilot.sqlite3"
```

A relative path would land in the working directory, which `ProtectSystem=strict`
makes read-only. That failure is loud rather than silent, but it is avoidable.

### 4. Enable 1-Wire, if using probes

On Raspberry Pi OS, add to `/boot/firmware/config.txt` and reboot:

```text
dtoverlay=w1-gpio,gpiopin=4
```

Then confirm the kernel sees the probes:

```bash
ls /sys/bus/w1/devices/
```

Each `28-*` directory is one DS18B20. Those ids go into `device_id` in the
configuration.

### 5. Install the units

```bash
cp /opt/geopilot/deploy/systemd/geopilot-poll.service /etc/systemd/system/
cp /opt/geopilot/deploy/systemd/geopilot-poll.timer /etc/systemd/system/
systemctl daemon-reload
```

Verify before enabling anything:

```bash
systemd-analyze verify /etc/systemd/system/geopilot-poll.service
```

### 6. Prove one cycle works before automating it

```bash
sudo -u geopilot /opt/geopilot/venv/bin/python \
    /opt/geopilot/tools/geopilot_poll.py \
    --config /etc/geopilot/installation.toml --once
```

Automating something that has never run once is how an empty database is
discovered in March.

### 7. Start it

```bash
systemctl enable --now geopilot-poll.timer
systemctl list-timers geopilot-poll.timer
```

## Why a failed read does not fail the unit

`geopilot_poll.py` exits `2` when at least one read failed. On a real bus that
is normal: a device is briefly unreachable, a CRC fails, a probe is mid
conversion.

The unit sets:

```ini
SuccessExitStatus=0 2
```

Without it, every intermittent read would mark the unit failed, and a year of
recording would become a year of alerts about nothing. Exit `1`, a configuration
problem, still fails the unit, because that one is real.

## Why the timer does not catch up

```ini
Persistent=false
```

If the host is off for six hours, systemd must **not** fire the missed cycles on
boot. A measurement taken now would be recorded as if it had happened during the
outage, which quietly corrupts the time series. A gap in the data is honest; a
backfilled sample is not.

## Verifying it runs

```bash
systemctl status geopilot-poll.timer
journalctl -u geopilot-poll.service --since "1 hour ago"
```

And check that measurements are actually landing:

```bash
sudo -u geopilot sqlite3 /var/lib/geopilot/geopilot.sqlite3 \
    "SELECT COUNT(*), MAX(observed_at_us) FROM measurements"
```

A count that stops rising is the failure that matters, and no alert will tell
you. Check it deliberately during the first week.

## Time matters more than usual

`observed_at` is stamped when the reading is taken. A host whose clock is wrong
mislabels history permanently, and no later correction can recover which sample
belonged where.

```bash
timedatectl status
```

Confirm NTP synchronisation before starting a long recording. `OnBootSec=2min`
in the timer exists to give the clock time to settle.

## Backups

The service writes one SQLite file. Back it up per
[Backup And Restore](BACKUP_AND_RESTORE.md), and remember that a plain copy of a
running database is unusable under WAL journalling.

A backup timer is not provided yet. Until it is, back up manually and verify the
copy.

## Limits

- the unit files are unverified on real hardware;
- no health check, no alerting, no metrics endpoint;
- no automatic backup;
- a transport that disappears mid-run is not reopened; the long-running service
  relies on `Restart=always` to recover, the timer recovers on the next cycle;
- log volume is not bounded beyond the journal's own limits.

## Future Work

- Run this on the Pi and correct whatever is wrong.
- A backup timer once the recording is proven.
- A health check that notices when the measurement count stops rising.
