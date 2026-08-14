# ADR: Continuous Acquisition

**Status:** Accepted
**Scope:** how GeoPilot describes an installation and how it records it over
months without supervision
**Blocks:** every use of GeoPilot on a real system

Until now GeoPilot could acquire, normalize, store and project, but nothing ran
on its own. `AcquisitionRunner` executes a plan once. `SimulatedPollingRunner`
executes several plans with no delay between them. There is no process that
records anything over a year, and the asset registry is populated in Python
source, in `scenarios.py`.

That gap is the only thing standing between the project and its purpose.

## Context

The immediate need is a year of continuous measurement on a real geothermal
system, requested in writing by the engineer analysing that system: fluid
temperatures over a full year of operation, plus energy consumption of the heat
pump separated from the rest of the house. Manual readings have never captured
the critical events.

Two decisions are required before any of that can run.

## Decision 1: configuration is TOML

An installation is described in a TOML file, parsed with `tomllib` from the
standard library.

| Option | Why not |
| --- | --- |
| **TOML** | **Chosen.** In the standard library since Python 3.11, so no dependency. Comments allowed, which matters for recording why a register address was chosen |
| YAML | Requires PyYAML. A dependency for a project that has none, to gain indentation-sensitivity nobody asked for |
| JSON | No comments. A configuration file describing physical hardware needs comments more than most |
| Python module | What exists today. Executable configuration is not configuration |

The file replaces `scenarios.py` as the way an installation is declared. It
carries the registry, the sources, what to read, and where to store it.

## Decision 2: the runtime is a loop, the schedule is not GeoPilot's problem

Two execution modes, both in a runtime module outside the domain:

- **one shot.** Execute every configured plan once and exit. This is what a
  systemd timer or cron invokes, and it is the recommended production mode.
  Restart, supervision, logging and boot behaviour become the operating
  system's job, which is where they belong and where they already work;
- **interval loop.** Execute, sleep, repeat, until interrupted. Simple, useful
  for bench work and for sub-minute resolution that cron cannot express.

The domain keeps its guarantees. No `sleep`, no thread, no async, no scheduler
enters `domain.py`, `ingestion.py`, `historian.py`, `acquisition*.py` or any
transport. The loop lives in a runtime module and calls the same
`AcquisitionRunner` that tests already cover.

### Why not async

There is nothing to overlap. A Modbus RTU bus is serial by nature and a
half-duplex RS485 segment permits exactly one transaction at a time. Async
would add a concurrency model to a problem that has no concurrency.

## Failure Policy

Unattended recording for a year fails differently than a bench script. The rules:

- **a failed read is data, not a crash.** Transport errors already become
  `AcquisitionFailure`. A cycle continues after one;
- **a cycle never aborts the run.** An unexpected exception in one cycle is
  logged and the next cycle proceeds. A year of recording must not end because
  of one bad night;
- **storage errors are fatal.** If the database cannot be written, continuing
  would silently discard the measurements that justify the whole exercise;
- **no retry, no backoff.** The next cycle is the retry. Retrying inside a cycle
  distorts the time series with samples that are not where they claim to be.

## Consequences

### Positive

- an installation becomes a reviewable file instead of Python source;
- the same configuration describes bench and production, so what is validated on
  the bench is what runs;
- comments in the configuration record why an address was chosen, next to the
  address;
- the operating system handles supervision, which removes the largest category
  of homemade daemon bugs.

### Negative

- a configuration format is a compatibility surface. Changing it later breaks
  existing files;
- one-shot mode pays process startup on every cycle, which is acceptable at the
  intervals involved and unacceptable below roughly one second;
- errors are now something an unattended process reports rather than something a
  human sees immediately. Log quality matters more than it did.

## Out Of Scope

- alerting on failures;
- a dashboard;
- writing to any device;
- remote access of any kind;
- configuration reload without restart;
- retention or rotation of stored data.

## Follow-Up Work

1. Configuration loading and validation.
2. Runtime with both execution modes.
3. A worked example configuration for the bench.
4. A systemd unit and timer, documented, once the bench session confirms the
   hardware.
