# Command Guard

**Status:** Draft
**Scope:** deciding whether a command may happen, and recording what did
**Implements:** decision 5 of [Control Boundary ADR](CONTROL_BOUNDARY_ADR.md)
**Not wired into the runtime.** Nothing in GeoPilot issues commands yet.

The write transport will operate a relay as fast as it is called. This is what
decides whether it should.

## The four conditions

A command is refused unless all of them hold.

| Condition | Refusal |
| --- | --- |
| Control is explicitly enabled | `control_disabled` |
| The target is whitelisted by id | `unknown_target` |
| The minimum interval for that target has elapsed | `rate_limited` |
| A write transport exists | fails rather than pretending |

`ControlPolicy()` with no arguments has `enabled=False`. **A configuration that
says nothing about control grants none**, which is the behaviour the ADR
requires and the first thing the tests assert.

## Why a minimum interval per target

`minimum_interval_seconds` is not a performance setting. Relay chatter is how
contactors weld and compressors die, so every target declares the fastest it may
be operated and the guard enforces it.

Two behaviours matter as much as the limit itself:

- **a refused command does not restart the window.** Otherwise a caller
  retrying every few seconds would starve itself forever;
- **a failed command does not start the window.** A write that did not happen
  must not block the retry.

Both are tested, because both are the kind of thing that looks correct and is
not.

## Why the guard never caches relay state

The service does not remember whether a relay is open or closed, and
deliberately does not skip a command that matches the state it last requested.

Assuming a contact is where you left it is how a controller and a building drift
apart, after a power cycle, a manual override, or a technician's afternoon. The
guard commands what it was asked to command and lets the device answer.

## Every attempt is recorded

Applied, refused or failed, each attempt produces a `CommandRecord` carrying the
target, the state, the outcome, the detail, the timestamp, and the **reason**
the caller gave.

`reason` is a required field on every command. A control system that cannot say
why it did something is undebuggable after an incident, and an incident is
exactly when the question gets asked.

Records serialize to JSON-safe data, so a journal can be exported the same way
measurements are.

## Refusals are returned, not raised

`execute()` always returns a record. A caller driving four dampers must not lose
the other three because one was rate limited.

## What is deliberately missing

- **No persistent journal.** `InMemoryCommandJournal` exists for tests and bench
  work. A SQLite journal belongs with the historian and has not been written;
- **No runtime wiring.** `runtime.py` does not import this module. Acquisition
  is untouched;
- **No configuration.** Control cannot yet be described in `installation.toml`,
  which means it cannot yet be enabled by editing a file. That is a deliberate
  ordering, not an oversight;
- **No logic that decides what to command.** Nothing here knows about zones,
  temperatures or heat. It executes decisions; it does not make them.

## Testing

`tests/test_control.py` uses a fake write transport and an advanceable clock, so
rate limiting is tested without sleeping.

Covered: disabled by default, disabled policy, unlisted target, permitted
command reaching the transport, rate limit refusing and then allowing, refusals
and failures not affecting the window, transport failure recorded rather than
raised, missing transport, journalling with reasons, JSON serialization, and the
absence of state caching.

## Before control is ever enabled

1. The wiring must be normally-closed pass-through, per the ADR. Nothing in this
   module provides safety without it.
2. The system must have been recorded long enough to know what it does.
3. A persistent journal should exist, because the first question after an
   incident is what happened, and memory does not survive a restart.
