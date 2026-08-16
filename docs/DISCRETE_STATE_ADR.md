# ADR: Discrete State Representation

**Status:** Accepted, implemented
**Scope:** how GeoPilot stores an observation that is on or off
**Blocks:** ingesting Modbus discrete inputs, which is the measurement that
tests whether zoning causes the high-pressure lockouts

The bit transport can read "zone 1 is calling" from the wire. The domain cannot
store it. This decides how it should.

## Context

`Measurement` is the only thing the historian, the snapshot and the exports
know how to handle, and it constrains what a discrete signal can become:

| Constraint | Consequence |
| --- | --- |
| `value` is `int \| float` and **explicitly rejects `bool`** | a state cannot be stored as True |
| `unit` is a required non-empty string | a state must name a unit |
| `SensorMeasurementKind` has temperature, relative humidity, power | no kind accepts a state |
| the normalizer accepts `degC`, `°C`, `degF`, `°F`, `%`, `W`, `kW` | no unit accepts a state |

`EquipmentState` exists and looks like a candidate, but it describes an
**equipment** operational state drawn from a fixed enum, `off`, `idle`,
`heating`, `cooling`, `fan_only`, `defrost`. A thermostat call is neither
equipment nor one of those, and the historian does not store `EquipmentState` at
all. It is the wrong home.

## Options Considered

| Option | Verdict |
| --- | --- |
| **A. A state sensor kind, value 0 or 1, canonical unit `state`** | **Chosen** |
| B. A parallel `DiscreteObservation` type | Rejected. A second historian, snapshot, export and identity rule doubles the surface for one bit |
| C. Reuse `EquipmentState` | Rejected. Wrong subject, wrong vocabulary, not stored |
| D. Encode as an existing unit, `1.0 W` or `100 %` | Rejected. Dishonest data is worse than missing data |

Option A keeps every downstream path unchanged. The historian, the SQLite
schema, the snapshot, the exports, the duplicate policy and the measurement
identity all work without modification, because a state is stored as a number
like everything else.

## Decision

### A state is a measurement whose value is 0 or 1

- `1` means **the signal is asserted**;
- `0` means it is not;
- **no other value is accepted.** A state that can be 0.7 is not a state, and
  the normalizer rejects it rather than rounding.

Storing 0 and 1 rather than a boolean also keeps every existing tool working:
a duty cycle is an average, a transition count is a diff, and both are
questions worth asking of a zone call.

### The canonical unit is `state`

`state` is not a physical dimension, and this is the first unit in GeoPilot that
is not. The field is required and non-empty, so a discrete measurement must name
something, and naming it `state` is more honest than borrowing `%`.

Only that spelling is accepted. Temperature carries aliases, `degC` and `°C`,
because both spellings arrive from real devices. A discrete state has no legacy
spelling to accommodate, so it gets exactly one.

### New enum values

```text
MeasurementKind.STATE          generic kind, alongside temperature, power, mode
SensorMeasurementKind.STATE    unit-compatibility kind, alongside the three existing
```

`MeasurementKind.MODE` already exists and is the near miss. A mode is one of
several named values; a state is asserted or not. Conflating them would make
`mode` mean two things.

### Normalization is pass-through, with validation

A `STATE` sensor accepts unit `state` and a value of 0 or 1, and stores both
unchanged. There is no conversion because there is nothing to convert. What the
normalizer does is **refuse everything else**, which is the same job it does for
temperature, expressed against a smaller domain.

### Inversion lives in configuration, never in the domain

Active-low wiring exists. A thermostat whose contact closes when it is **not**
calling is a real thing, and somebody will meet one.

The stored measurement must always mean the same thing, so a stored `1` always
means asserted. An adapter that reads an inverted signal inverts it **before**
ingestion, driven by a configuration flag on the read, in the same way a
DS18B20 carries a calibration offset.

The domain never learns that inversion exists. If it did, every consumer would
have to ask whether this particular 1 meant yes.

## Consequences

### Positive

- discrete signals become first-class without a new storage path;
- duty cycle, transition counts and correlation against lockout timestamps all
  become ordinary queries;
- the first unit that is not a physical dimension is introduced deliberately,
  with a stated reason, rather than by someone needing a placeholder later.

### Negative

- `unit` no longer always means a physical dimension, which weakens a property
  that was previously true without exception;
- `1` carries no self-description. What asserted means for a given signal lives
  in the sensor's name and the configuration, not in the value. A measurement
  read in isolation is less self-explanatory than `21.5 degC`;
- periodic sampling of a state is wasteful, see below.

### The storage cost, measured against known numbers

Four zone calls sampled every 30 seconds produce **4.2 million rows a year**, at
the measured 211 bytes per row, roughly **0.9 GB**, to record signals that change
perhaps fifty times a day.

Change-of-state recording would produce about **73,000 rows a year**, a factor of
about 57.

This ADR does **not** adopt change-of-state recording. It requires a second
acquisition mode, a decision about how to represent "still true since", and care
about what a gap in the data means. Periodic sampling is simpler, its cost is
known, and 0.9 GB a year is affordable. The optimization is recorded here so the
next person knows it was considered rather than missed.

## Out Of Scope

- multi-valued modes and enumerations. `MeasurementKind.MODE` remains unused
  and undecided;
- change-of-state recording;
- deriving equipment state from discrete inputs. Inferring that the compressor
  is running because a contact is closed is interpretation, and interpretation
  belongs to a later phase;
- alerting on a state change.

## Acceptance Criteria

Accept when a reviewer confirms:

- 0 and 1 with a `state` unit is preferable to a parallel discrete type;
- introducing a non-physical unit is an acceptable price for leaving the storage
  path untouched;
- inversion belongs in configuration, so that a stored `1` always means the same
  thing;
- rejecting every value other than 0 and 1 is desired, rather than coercing.

## Follow-Up Work

1. `feature/discrete-state` — the two enum values, normalizer support, and tests
   asserting that 0.5, 2 and `True` are all refused.
2. Configuration for bit reads, including the inversion flag.
3. Wire the bit transport into the runtime, so zone calls are recorded alongside
   temperatures.
