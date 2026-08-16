# ADR: Control Boundary

**Status:** Proposed, awaiting review
**Scope:** whether GeoPilot may command equipment, and under what constraints
**Changes:** the read-only product principle stated in `docs/PRODUCT.md`,
`README.md` and `docs/PROJECT_HANDOFF.md`

Every document in this repository says GeoPilot is read-only and adds no HVAC
control. This ADR proposes changing that, and defines the conditions under which
it is safe to do so.

It does not implement control. It decides the boundary, the failure model and
the permanent limits, so that implementation cannot quietly become something
else.

## Context

The owner wants zone damper control and, later, anticipatory heating. The
existing installation has four motorised dampers driven today by Sinopé
MC3100ZB modules operated by hand from a phone application, and four thermostats
whose 24 VAC call signals feed a 2011-era relay panel.

The building is a triplex in a cold climate, heated by a geothermal heat pump
whose radiant slab has hours of thermal lag. Reactive control on that slab is
always late, which is a genuine argument for anticipation rather than a
preference.

Nothing about that intent is unreasonable. What makes it dangerous is the
failure mode: software that interrupts a heating call can stop heat in January
while nobody is home.

## Decision 1: control is permitted, in tiers

| Tier | Example | Permitted |
| ---: | --- | --- |
| 1 | Notify. "High-pressure lockout at 14:32, loop at 31 °C" | Yes |
| 2 | Switch equipment that is not the heat pump: a circulation pump, a dehumidifier, an auxiliary device on its own circuit | Yes |
| 3 | Operate zone dampers, or change a thermostat setpoint | Yes, under the conditions below |
| 4 | Switch the compressor contactor, write to the heat pump's own control registers, or bypass any manufacturer safety | **Never** |

Tier 4 stays forbidden permanently. The heat pump's controller owns compressor
protection, anti-short-cycle timing and pressure limits. Software that competes
with those does not add capability, it removes protection.

## Decision 2: fail-safe is a wiring property, not a software feature

**Any relay GeoPilot operates must be wired so that its de-energised state is
the existing behaviour of the system.**

```text
thermostat ──┬───────────── normally closed ──────────────► heat pump
             │                    ▲
             └── GeoPilot relay ──┘
                 energised = GeoPilot redirects
                 de-energised = original wiring, unchanged
```

Consequences that follow from the wiring rather than from code:

- a dead process, a kernel panic, a corrupted database, a failed upgrade or a
  power loss returns the building to the behaviour it had before GeoPilot
  existed;
- no watchdog, no heartbeat and no supervisor is load-bearing for safety. They
  improve availability, not survival;
- a person can disable GeoPilot's authority by cutting one supply, without
  understanding the software.

An installation that cannot be wired this way is out of scope. This is the one
condition that is not negotiable, because it is the only one that holds when the
software is wrong.

## Decision 3: commands ride the Modbus bus, not the GPIO

Actuation uses **Modbus RTU relay modules on the existing RS485 bus**, not
GPIO expansion boards.

| | Modbus relay module | GPIO relay HAT |
| --- | --- | --- |
| Isolation | galvanic, built in | none by default |
| 24 VAC near the CPU | no | yes, centimetres away |
| Mounting | DIN rail, in a cabinet | stacked on the computer |
| Protocol already implemented | yes | no |

GeoPilot already speaks Modbus, already opens the bus, and already has a
transport boundary with structured errors. Writes become a bounded extension of
something tested rather than a new subsystem.

## Decision 4: the write path is a separate protocol

Reads and writes are **different protocols in the type system**, not two methods
on one object.

```text
ModbusTransport         read_registers()      exists today, unchanged
ModbusWriteTransport    write_coil()          new, separate
```

A build, a deployment or a test that never constructs a `ModbusWriteTransport`
has no capability to write. Not a disabled flag, not a configuration value: the
capability is absent. A read-only installation stays read-only by construction,
which is a much stronger guarantee than a boolean somebody can flip.

## Decision 5: every command is guarded and recorded

A command is refused unless all of the following hold:

- **control is explicitly enabled** in configuration. Absent means off;
- **the target is whitelisted** by id. A command naming an unlisted target is
  refused, so a configuration mistake cannot reach an unintended relay;
- **the rate limit allows it.** No target may be operated more often than its
  configured minimum interval. Relay chatter is how contactors and compressors
  die;
- **the command is expressible.** Only discrete relay states. No numeric
  setpoint writes to equipment in this revision.

Every command is recorded with its outcome, applied or refused, and the reason.
A control system that cannot say what it did last Tuesday cannot be debugged
after an incident, and an incident is exactly when the question gets asked.

## Decision 6: nothing is commanded before it is understood

Control on this installation stays disabled until the system has been recorded
long enough to know what it does. The owner's own dossier states it:

> Le projet Raspberry Pi / BACnet / GEN2 est une option de contrôle et de
> monitoring, pas une solution à un manque de capacité mécanique.

Reading which zones are calling has immediate diagnostic value with no
actuation at all, and it is the measurement that tests whether zoning is behind
the high-pressure lockouts. That comes first.

## Consequences

### Positive

- the stated goal becomes reachable without weakening the parts that already
  work;
- the acquisition path is untouched. Nothing about reading changes;
- a read-only deployment remains provably read-only;
- the failure model is understandable by someone who is not a programmer, which
  matters because the person who has to disable it in an emergency may not be
  one.

### Negative

- the product is no longer purely observational, and the documents that say so
  must change;
- an installer now needs to wire relays correctly for the safety model to hold.
  A miswired normally-open relay silently removes the guarantee;
- command history is a new thing to store, back up and retain;
- the project acquires a class of bug whose consequences are physical.

## Out Of Scope

- writing to the heat pump's own registers or controller, at any tier;
- bypassing, delaying or emulating a manufacturer safety device;
- anticipatory or predictive logic, which needs a thermal model that needs data
  that does not exist yet;
- remote or internet-facing control of any kind;
- scheduling. The runtime executes; it does not decide when.

## Acceptance Criteria

Accept when a reviewer confirms:

- tier 4 is permanently excluded and the wording leaves no room to reinterpret;
- the fail-safe wiring rule is understood as a precondition, not a
  recommendation;
- a read-only build cannot write, by type rather than by flag;
- disabled-by-default is the behaviour when configuration says nothing.

## Follow-Up Work

1. `feature/modbus-write-transport` — `ModbusWriteTransport`, function code
   `0x05`, structured errors, fake transport, no runtime wiring.
2. ~~`feature/command-guard`~~ — done; see `docs/COMMAND_GUARD.md`.
3. Read zone call signals through Modbus digital inputs, still read-only.
4. Revisit anticipatory control only after a heating season of data exists.
