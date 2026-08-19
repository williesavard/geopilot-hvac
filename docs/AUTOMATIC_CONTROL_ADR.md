# ADR: Automatic Control

**Status:** Accepted, **deliberately not implemented**
**Scope:** whether and how GeoPilot may issue a command nobody pressed a button for
**Decides:** the architecture, and the gates that must be passed before any of it is written

Every command GeoPilot can issue today comes from a person who pressed a button
and typed a reason. This decides what changes when nothing does.

## Context

Two prior decisions bear on this and neither is reopened here:

- [Control Boundary](CONTROL_BOUNDARY_ADR.md): *"Revisit anticipatory control
  only after a heating season of data exists."*
- `SITE.md`: *"intelligent zoning control belongs to the future machine. There
  is nothing to control intelligently on a 2013 unit that is locking out."*

Both still hold. **This installation has zero recorded measurements.** Writing a
controller now would mean tuning it against a machine that is a candidate for
replacement, which is work thrown away twice: once when the data arrives and
contradicts the assumptions, once when the equipment changes.

So the question this ADR answers is not "shall we build it" but "**what would
have to be true, and what shape would it take**" — decided now, while nothing is
at stake, rather than in the week somebody wants it.

## What is genuinely new

The guard already handles a great deal. It is worth separating what automatic
control changes from what it does not, because conflating the two produces
either paranoia or complacency.

| Concern | Already solved | Changes under automation |
| --- | --- | --- |
| An unlisted relay | whitelist | no |
| Relay chatter | minimum interval, per target | **partly** — see below |
| Believing your own intentions | never caches, always reads back | no |
| Losing the record | persistent journal | no |
| A stuck contact being dangerous | fail-safe by wiring | no |
| **Why did it do that** | a human typed a reason | **yes** |
| **Acting on a stale reading** | a human sees "silent" on the page | **yes** |
| **Nobody watching** | a human was, by definition | **yes** |
| **Stopping it** | close the browser | **yes** |

Four real problems, and the second is the one that will actually bite.

### Acting on a stale reading

A person operating the surface sees the connectivity table beside the buttons.
When a probe says **stopped**, they do not act on it.

A rule has no such reflex. A rule that closes a damper when the loop delta
collapses will happily act on a delta computed from a reading three hours old —
and a sensor going silent is *more* likely, not less, when something is wrong.
The failure mode is a controller that responds confidently to a frozen picture
of a house it can no longer see.

### Attribution

The journal stores a `reason` a person typed. `"testing zone 1"` is a sentence a
human wrote and a human can be asked about.

An automatic command has no author. It needs the rule's identity **and the
inputs it saw**, because "the rule fired" is not an answer to "why did the
damper close at 03:41" — the answer is the reading it fired on.

### Nobody watching, and stopping it

Manual control is self-limiting: it stops when the person walks away. Automatic
control runs at 03:00 in February whether or not anyone would agree with it, and
"close the browser" stops nothing.

## Options Considered

| Option | Verdict |
| --- | --- |
| **A. A scheduled evaluator: a oneshot that reads the recording, decides, issues at most N commands, exits** | **Chosen** |
| B. Rules inside the control server | Rejected. Puts policy in the process that is a doorway on purpose, and gives a long-lived process long-lived state to corrupt |
| C. Rules inside the acquisition runtime | Rejected. Couples the thing that must never stop to the thing most likely to have bugs |
| D. An external automation platform driving the HTTP surface | Rejected as the primary design. The guard would hold, but the reasoning would leave the project and the journal would record commands whose rationale lives elsewhere |

Option A mirrors the topology already proven here: acquisition is a systemd
oneshot on a timer, and it works. An evaluator that starts, reads, decides and
exits has **no long-running state**, cannot run away faster than its timer, and
leaves one journal trail per run.

## Decision

### 1. Automatic control is a separate process on a timer

Not a thread, not a loop inside the server. Each run reads the recording, judges
freshness, evaluates rules, issues commands through the **existing**
`ControlService`, and exits.

The guard is not bypassed, extended or duplicated. A rule is simply another
caller, and every refusal it earns is recorded exactly as a person's would be.

### 2. Stale input is a refusal, not a default

Before a rule may act, every sensor it reads must be **live** by
[Connectivity](CONNECTIVITY.md)'s existing test — reporting within three times
its own median interval — for the whole window the rule considers.

A rule whose inputs are late does not fall back to a safe value, a last known
value, or a default. **It declines to act and records that it declined.** A
controller that guesses when it cannot see is worse than one that stops, because
the guess is invisible and the stop is not.

### 3. Every automatic command carries its rule and its inputs

The `reason` field becomes structured for automatic commands: the rule
identifier, and the readings it fired on, with their timestamps.

`"loop_delta_low: delta 0.8 degC at 03:41, threshold 1.5, compressor asserted
for 42 min"` is an answer. `"automatic"` is not.

### 4. A budget per run, and a budget per day

The per-target minimum interval bounds how often **one relay** moves. It does
not bound a rule flapping across several, nor a controller that has decided
something is wrong and keeps saying so.

So each run may issue at most a small fixed number of commands, and each rule
has a daily ceiling. **Exhausting either is an event to record, not a limit to
raise** — a rule at its ceiling is a rule that is wrong.

### 5. Rules propose; they do not act directly

A rule returns an intent — target, desired state, reason, inputs. The evaluator
collects intents, refuses contradictory ones outright rather than resolving them
by priority, and passes the survivors to the guard.

Priority resolution is a way to make two wrong rules produce a plausible action.
Refusing is a way to find out that two rules disagree.

### 6. An off switch that survives a restart

A file, checked at the start of every run: if present, the evaluator records
that it was disabled and exits. Not a browser session, not an environment
variable in a shell that is gone.

`[control] enabled = false` remains the master switch and is unchanged — an
automatic command is refused by the guard exactly as a manual one is.

## Gates

None of the above is written until **all** of these hold. They are stated as
checks rather than judgements so that passing them is not a matter of opinion.

1. **A heating season of data exists**, per the control boundary ADR.
2. **`geopilot_report.py` shows no gap larger than one poll interval** across
   the window a rule would have acted on. A rule cannot be trusted on a record
   the recorder could not keep.
3. **Every sensor the rule depends on reads `connected`**, and has for the whole
   season, not merely today.
4. **The relay has been operated manually at least twenty times**, with the
   read-back confirming the contact moved every time. A relay that has never
   been proven to move under a person's hand is not one to hand to a rule.
5. **Fail-safe verified physically**: power removed at the relay, and the
   observed resting state written into `BENCH_NOTES.md`. Not inferred from a
   wiring diagram.
6. **The equipment is the one that will remain.** Automatic control for a
   machine under replacement is thrown-away work.

Gate 6 is the one most likely to be argued with, and it is the one that saves
the most effort.

## Consequences

### Positive

- the architecture is decided while nothing is at stake, which is when
  architecture decisions are cheap and honest;
- the guard, the journal and the read-back rule are reused rather than
  reimplemented, so automation inherits every refusal already tested;
- the freshness rule gives the connectivity work a second, load-bearing job;
- a oneshot on a timer is observable, killable and bounded by construction.

### Negative

- **a scheduled evaluator cannot react quickly.** Anything needing a response in
  seconds is out of reach by design, and if such a need appears the answer is a
  hardware interlock, not a faster timer;
- **the gates are strict enough that they may never all be met**, particularly
  gate 6. That is an acceptable outcome: the project's value is the evidence,
  and control was always the optional part;
- refusing contradictory intents means a badly written rule set does nothing
  rather than something. Deliberate, and it will feel like a bug the first time.

### Explicitly and permanently out of scope

- **anything safety-critical.** No freeze protection, no over-temperature
  cutout, no compressor protection. Those belong to the equipment's own controls
  and to wiring. If GeoPilot failing can hurt the building, the design is wrong
  regardless of how careful the software is;
- **learning, adaptation or optimisation that changes its own thresholds.** A
  rule whose behaviour drifts cannot be audited against the reason it was
  written;
- **control of anything not on the whitelist**, which the guard enforces anyway.

## Acceptance Criteria

Accept when a reviewer confirms:

- a scheduled oneshot is the right shape, and rules do not belong in the
  listening process;
- declining to act on stale input, rather than falling back to a default, is
  correct even when it means doing nothing on a cold night;
- refusing contradictory intents is preferable to resolving them by priority;
- the gates are the right ones, and gate 6 in particular is worth honouring.

## Follow-Up Work

Nothing, deliberately. This ADR is complete without code.

When the gates are passed, the first branch is a rule that does nothing but
**log what it would have done** for a full season, evaluated against the
recording it already has. A controller that has never been proven right in
hindsight has no business being right in advance.
