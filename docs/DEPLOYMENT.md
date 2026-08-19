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

## Why /run/lock is writable

All three units set `ProtectSystem=strict`, which makes the entire filesystem
hierarchy read-only apart from `/dev`, `/proc` and `/sys`. `/run` is included.

Every Modbus transport builds a `PortLock`, and `port_lock` **fails open**: if
the lock file cannot be created it proceeds uncoordinated, because refusing to
poll over a missing lock file would stop the recording. That is the right
behaviour and it is also why the defect below was invisible.

Under `ProtectSystem=strict` and nothing else, the lock file can never be
created. Locking is silently off, and the acquisition timer and the control
surface can interleave a request and a response on the same RS485 segment — each
frame intact and CRC-correct, so nothing detects the swap. Hence:

```ini
ReadWritePaths=/run/lock
```

The temp-directory fallback does not rescue it either. `PrivateTmp=true` gives
each unit its own `/tmp`, so two processes falling back would take unrelated
locks and both believe themselves protected. See [Port Lock](PORT_LOCK.md).

### 8. The control surface, if you want one

Optional, and orthogonal to the choice above: it runs alongside either the timer
or the long-running service, and nothing breaks if it is never installed.

```bash
cp /opt/geopilot/deploy/systemd/geopilot-control.service /etc/systemd/system/
systemctl daemon-reload
systemd-analyze verify /etc/systemd/system/geopilot-control.service
systemctl enable --now geopilot-control.service
```

Then, on the Pi itself, open <http://127.0.0.1:8322/>. Not from a laptop — that
is the point.

**Installing it does not enable control.** `[control] enabled = false` is the
default and the absence of the table means the same. The page still lists every
whitelisted relay and reads its real state back from the bus; every command is
refused, and recorded as refused. Run it that way first: the wiring gets proven
and nothing can move.

The unit differs from the other two in ways worth knowing before editing it:

| | Why |
| --- | --- |
| `--bind 127.0.0.1` is written into `ExecStart` | the tool accepts `--bind` and warns; a unit file is copied and forgotten, so this one cannot say anything else |
| `IPAddressDeny=any`, `IPAddressAllow=localhost` | the kernel agrees with the flag, so editing `ExecStart` alone is not enough to expose relay control |
| `Restart=on-failure` with `StartLimitBurst=5` | safe only because the interval between relay operations is journalled and survives a restart; the ceiling is there because a crash loop is not fixed by restarting |
| `PrivateDevices=` is absent, `DevicePolicy=closed` is present | `PrivateDevices=yes` replaces `/dev` with a skeleton and the RS485 adapter disappears |
| `SystemCallErrorNumber=EPERM` | a filtered call becomes a Python `OSError` in the journal instead of a `SIGSYS` that kills the service with no explanation |
| `MemoryDenyWriteExecute=` is absent | it breaks interpreters that build executable trampolines, and none of this has been run on a Pi yet |

`tests/test_systemd_units.py` asserts each of those, so a well-meaning edit that
drops one fails in CI rather than on the roof of the heating season.

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
sudo -u geopilot python3 tools/geopilot_report.py \
    --database /var/lib/geopilot/geopilot.sqlite3
```

A count that stops rising is the failure that matters, and no alert will tell
you. Check it deliberately during the first week. The report opens the database
read-only and is safe to run while recording continues; its `largest gap` column
is what reveals an outage that a healthy-looking total would hide. See
[Reporting](REPORTING.md).

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
- the control surface has no health check either; if it dies between
  restarts nothing says so, and the page simply does not load;
- no health check, no alerting, no metrics endpoint;
- no automatic backup;
- a transport that disappears mid-run is not reopened; the long-running service
  relies on `Restart=always` to recover, the timer recovers on the next cycle;
- log volume is not bounded beyond the journal's own limits.

## Future Work

- Run this on the Pi and correct whatever is wrong. `systemd-analyze verify`
  on each unit is the first five minutes of that.
- A backup timer once the recording is proven.
- A health check that notices when the measurement count stops rising.
