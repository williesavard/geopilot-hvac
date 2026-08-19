# Provenance: What Was In Effect, And When

**Status:** Implemented
**Scope:** the record of which corrections produced which measurements
**Answers:** "is that step in the graph the heat pump, or is it me?"

## The problem

Every stored measurement has already been corrected before it reached the
database:

| Read | Correction | Applied in |
| --- | --- | --- |
| DS18B20 probe | `offset_celsius` added | `onewire.py` |
| Modbus register | `× scale + offset` | `register_decoder.py` |
| Discrete input | `inverted` un-flipped | before ingestion |

The database keeps the result. It says nothing about the correction, which is
fine right up until the correction changes — and then a year of recording
quietly stops meaning one thing.

Three ways that happens, none of them hypothetical:

- **a recalibration.** The probes are re-run in an ice bath in January and the
  offsets move by 0.2 °C. December's loop delta and February's are now on
  different scales. A step in the graph is either the heat pump degrading or the
  calibration moving, and nothing distinguishes them;
- **a swapped probe.** DS18B20 device ids are 64-bit hex on identical-looking
  cables. If loop entry and loop exit trade places during commissioning, the
  delta reverses sign;
- **a corrected polarity flag.** Every cycle count before the correction means
  the opposite of every cycle count after it.

**None of this can be reconstructed afterwards.** `config/` is edited in place
and is deliberately not in version control, because it describes a specific
residence. So the only available evidence is "I do not think I changed
anything", which is not evidence — least of all in a document supporting a
$40,000 capital decision reviewed by a professional engineer.

## The decision

A third database beside the measurements and the command journal, holding
**configuration epochs**: what every sensor's value was derived from, and the
moment that became true.

An epoch is written when the fingerprint of the derivation changes, and never
otherwise. On a one-minute timer the recorder opens a session 525,600 times a
year and writes perhaps three rows.

### What is fingerprinted

Exactly the fields that change what a stored value *means*:

```text
sensor_id, kind, reference, unit, scale, offset, inverted
```

`reference` is the physical origin — a 1-Wire device id, or `unit:kind:address`
for Modbus. Descriptions, names and poll intervals are **not** fingerprinted:
editing one does not make yesterday's readings incomparable with today's, and a
fingerprint that moves for cosmetic reasons trains people to ignore it.

SHA-256 over a canonical JSON encoding, sorted, so two loads of the same file
always agree. Reports print the first 12 hex characters.

### What it does not claim

**It records the configuration, not the truth.** A probe physically wired to the
return pipe but configured as the supply is recorded faithfully as the supply.
Provenance narrows "the numbers changed" to "the numbers changed and nothing in
the configuration did" — which is the useful half, and all a file can honestly
offer.

## Using it

The recorder announces a new epoch on stderr, and `--quiet` does not silence it:

```text
configuration epoch 4ec40f450271 opened at 2026-01-14T09:22:31-05:00 (4 sensors)
  sensor_loop_in: offset 0.31 → 0.44
  measurements before and after this moment had different corrections applied
```

In code:

```python
from geopilot.sqlite_provenance import SqliteProvenanceJournal, provenance_path

journal = SqliteProvenanceJournal(provenance_path("/var/lib/geopilot/geopilot.sqlite3"))

# What was in effect when this reading was taken?
epoch = journal.at(observed_at)

# Did anything move during the window I am about to report on?
for epoch, changes in journal.changes_between(start, end):
    for change in changes:
        print(change.describe())
```

`at()` returns `None` for a moment before any epoch, which is what a database
written before this journal existed looks like. That is said out loud rather
than guessed, because guessing the configuration backwards is inventing
evidence.

## Storage

Its own file — `provenance.sqlite3`, beside the measurements — for the reason
the command journal has its own: **retention prunes measurements, and the record
of what those measurements meant has to outlive them.** `geopilot_backup.py`
copies it along with the other two.

An in-memory measurements database gets an in-memory journal, so nothing writes
`provenance.sqlite3` into whatever directory a process happened to start in.

Append only, WAL, `synchronous=FULL`, ordered by write sequence — the same
decisions as [Command Journal Storage](COMMAND_JOURNAL_STORAGE.md), for the same
reasons.

## In the report

`geopilot_report.py` warns, **without being asked**, when a correction moved
inside the window it is reporting on:

```text
WARNING: a correction changed inside this window. Measurements before and after
each moment below were computed differently, so a step in these numbers may be
the configuration rather than the equipment.
  2027-01-14T00:00:00+00:00 (epoch c3b1e1270b43)
    sensor_loop_in: offset 0.31 → 0.44
  see docs/PROVENANCE.md
```

Two design decisions make it worth having rather than worth muting:

- **it only fires for sensors the report actually depends on.** A change to the
  tank probe does not warn a reader looking at the loop delta. An irrelevant
  warning is how a warning stops being read;
- **it goes to stderr**, so `--csv > loop.csv` stays a clean CSV while the
  caveat still reaches the terminal.

Silence means nothing moved, or there is no journal because the recording
predates it. Neither is worth a line, and nagging about the second every run
teaches people to pipe stderr away.

The full history is available on request:

```bash
python3 tools/geopilot_report.py --database /var/lib/geopilot/geopilot.sqlite3 --provenance
```

```text
epoch f3b69c006043  from 2026-10-01T00:00:00+00:00
  sensor_loop_in                   from 28-000005e2fdc3, +0.31
  sensor_loop_out                  from 28-000005f1ab9d, -0.12

epoch c3b1e1270b43  from 2027-01-14T00:00:00+00:00
  sensor_loop_in                   from 28-000005e2fdc3, +0.44
  sensor_loop_out                  from 28-000005f1ab9d, -0.12
  changed:
    sensor_loop_in: offset 0.31 → 0.44

2 epoch(s); the last one is still in effect
```

## Limits

- **it starts when it starts.** Recording that predates the journal has no
  epoch, and cannot be given one honestly;
- **it cannot see outside the configuration.** A probe that drifted has the same
  provenance yesterday and today; catching that is what a re-calibration run is
  for, and running one *creates* an epoch, which is the point;
- ~~nothing consumes it yet~~ — resolved. The report warns when a correction
  moved (see above) and [the dossier](DOSSIER.md) names and dates each change on
  its front page. The dashboard still does not.
