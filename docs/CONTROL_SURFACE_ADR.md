# ADR: A Local Control Surface

**Status:** Accepted, implemented
**Scope:** how a person operates a relay from a browser
**Changes:** GeoPilot now listens on a socket. Nothing else in the project does.

The guard was built in [Control Boundary](CONTROL_BOUNDARY_ADR.md) and has never
been reachable by a human. This decides how it becomes reachable.

## Context

The dashboard is a static file. A file has no back channel: it can show a relay
and it cannot move one. Commanding needs a process on a socket, and that is a
category change for a project whose every component so far has been a script
that runs, does one thing, and exits.

It is worth being clear about what is now true that was not:

| Before | After |
| --- | --- |
| nothing listens | one process listens, always |
| a bug can corrupt a database | a bug can operate a contactor |
| the attack surface is the filesystem | the attack surface includes anything that can reach a socket |
| the Pi can be off and nothing is lost but data | the Pi being wedged with a relay closed is a physical state |

## Options Considered

| Option | Verdict |
| --- | --- |
| **A. A local HTTP server, loopback by default** | **Chosen** |
| B. Keep the file; a CLI applies commands | Rejected. It is the CLI that already exists, with extra steps, and answers nothing the user asked |
| C. A queue file the page writes and a daemon drains | Rejected. A browser cannot write files, so this needs a server anyway — with a worse audit story |
| D. Expose it on the LAN with a password | Rejected as a default. It may be wanted later, and is available with `--bind`, but it is not what "let me press a button" costs |

## Decision

### It binds to the loopback interface

`127.0.0.1` unless told otherwise. Nothing off the machine can reach it. This is
the single largest thing protecting a contactor, and it costs one flag to give
up, which is why the tool prints a warning when you do.

### The doorway is separate from the guard

`ControlSurface` decides who may knock. `ControlService` decides what happens
next, and it was already written, already tested, and is unchanged by this. No
policy, no whitelist and no rate limit moved into the HTTP layer.

### Three tests on every command, and none of them is a password

| Test | What it stops |
| --- | --- |
| `Host` must be a loopback name | DNS rebinding, where the browser resolves an attacker's domain to 127.0.0.1 and makes the request *from inside* |
| `Origin`, when present, must be ours | Any page on the internet submitting a form to `http://127.0.0.1:8322/` |
| a token minted at startup, embedded in the page | Anything that never loaded the page |

A password was considered and rejected: it would be typed into a browser on the
same machine that holds the configuration, protecting nothing that loopback does
not already protect, and it would arrive with a credential to store.

### Control is off unless the configuration turns it on

`[control] enabled = false` is the default and the absence of the table means
the same. With control off the page still lists every whitelisted relay and
still reads its real state back from the bus, and every command is refused —
and **recorded as refused**.

That is the intended way to run it for the first weeks: the surface is real, the
wiring is proven, and nothing can move.

### The displayed state is read back, never remembered

Every poll asks the bus what the coil is doing. Nothing in the page or the server
stores what was last commanded and shows that back. This is the same rule the
guard already follows by refusing to cache, and it is the difference between a
controller that notices a contact did not move and one that cannot.

A relay that does not answer reads as **unknown**, not as open. A silent bus is
not an open contact.

### The serial port is opened per command, not held

The acquisition timer opens the same port every minute. Two processes cannot
hold an RS485 segment at once, so the surface opens it, transacts, and closes,
keeping the window to milliseconds.

A collision is not retried and not hidden: the write fails, the guard records it
as `FAILED` with the reason, and the page shows it.

### Every command carries a reason, typed by a person

The guard has always required one. The surface asks for it *before* the
confirmation, while the person still remembers why they are doing this, and
sends it to be journalled.

## Consequences

### Positive

- the guard finally has a user, and its refusals are visible instead of
  theoretical;
- the read-back rule is enforced where it is most tempting to break;
- an operator sees the whole picture — charts, cycles, relay states and the
  command journal — in one place;
- the first weeks can run with control disabled, which proves the wiring without
  risking the equipment.

### Negative

- **there is now a process that must stay running**, and a port that must not
  collide;
- **a browser is now part of the trust boundary.** Loopback, `Host`, `Origin`
  and a token are four defences, and a sufficiently determined piece of malware
  already running on the Pi defeats all four — it can read the token from the
  process or write the configuration;
- `--bind` exists and is a foot-gun. It warns; it does not refuse;
- the audit journal is in memory. It is lost on restart, which is acceptable for
  a surface used by hand and is **not** acceptable once anything automatic
  issues commands.

### Explicitly out of scope

- **automatic control.** Nothing here decides to do anything. Every command in
  this design comes from a person pressing a button and typing a reason.
  Anticipatory heating, weather compensation and staging are a separate decision
  with a separate ADR, and they are what make the in-memory journal insufficient;
- authentication, accounts and remote access;
- a persistent command journal;
- any interlock between targets. The guard permits each relay independently, and
  nothing prevents a configuration that allows two contradictory things at once.
  **Fail-safe belongs in the wiring**, as the control boundary ADR already
  requires: if a relay being stuck closed is dangerous, that must be untrue by
  how it is wired, not by software being careful.

## Acceptance Criteria

Accept when a reviewer confirms:

- loopback-by-default plus `Host`, `Origin` and token is proportionate for a
  surface that can operate HVAC relays;
- keeping the HTTP layer free of policy is worth the extra indirection;
- opening the serial port per command is preferable to holding it and
  restructuring the acquisition timer;
- shipping with control disabled, but the surface fully visible, is the right
  first-run posture.

## Follow-Up Work

1. A persistent command journal, before anything automatic can issue commands.
2. A systemd unit for the surface, with `--bind` fixed to loopback.
3. An ADR for automatic control, which is where the interesting safety questions
   actually live.
