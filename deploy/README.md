# Deploy

Files that install GeoPilot on a host, as opposed to code that runs inside it.

Nothing here is required to use GeoPilot from a terminal. These files exist so
the acquisition runtime can record for months unattended, with restart,
logging and boot behaviour handled by the operating system rather than by
homemade supervision.

## Contents

| Path | Purpose |
| --- | --- |
| `systemd/geopilot-poll.service` | One acquisition cycle, invoked by the timer |
| `systemd/geopilot-poll.timer` | Periodic trigger, one minute or slower |
| `systemd/geopilot-monitor.service` | Long-running alternative, for sub-minute intervals |

Use the timer or the long-running service, not both.

Installation, permissions, verification and the reasoning behind the unit
settings are documented in [Deployment](../docs/DEPLOYMENT.md).

## Status

**Written against the systemd documentation, not yet executed on real
hardware.** Expect corrections during the first install.
