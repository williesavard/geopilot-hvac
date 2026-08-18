# Command Journal Storage

**Status:** Implemented
**Scope:** keeping the record of every command across a restart

[Control Surface](CONTROL_SURFACE_ADR.md) shipped with an in-memory journal and
named replacing it as follow-up 1, with the condition attached: **before
anything automatic issues commands.**

An audit trail that a crash erases is not an audit trail. The question it exists
to answer is asked *after* an incident, and an incident is exactly the event
most likely to have restarted the process.

## It is not just the record — it is the rate limit

The defect this exposed is larger than lost history. `ControlService` kept the
last-applied time **in memory**, so:

```text
14:00:00  close target_zone_1        applied
14:00:05  the surface restarts
14:00:10  open  target_zone_1        applied   ← the interval is gone
```

A relay operated ten seconds before a restart could be operated again
immediately after it — exactly the chatter the minimum interval exists to
prevent, and exactly the situation a crash loop produces.

With the journal on disk, the guard asks it:

```text
--- process 1: operate the relay ---
  applied
--- process 1 exits, everything in memory is gone ---
--- process 2: same relay, 10 s later ---
  refused  rate_limited: 290.0s remaining
```

A journal that cannot answer — the in-memory one has no such contract — simply
returns nothing and the guard behaves exactly as before.

## Three decisions

### Its own file, not the measurements database

Two reasons, and the second decides it:

- SQLite permits one writer at a time per database. The poller writes every
  minute and the surface writes on command; separate files never contend;
- **the retention policy prunes measurements.** An audit record a retention
  policy can delete is not an audit record. The cheapest way to guarantee
  commands are kept forever is to put them where retention does not reach.

It defaults to `commands.sqlite3` beside the measurements file, so one backup
directory still catches both — see [Backup and Restore](BACKUP_AND_RESTORE.md),
and note that a `cp` of a WAL database is not a backup for this one either.

### Append only, by having no other verb

There is no update, no delete, no prune. A test asserts the class exposes none
of them.

A journal that can be rewritten answers a weaker question than one that cannot,
and the difference matters precisely when somebody would like the record to say
something else.

### Ordered by write sequence, not by clock

`seq` is an autoincrementing key and every query orders by it. Two commands can
share a microsecond, and a host whose clock steps backwards can stamp a later
command earlier — a Raspberry Pi picking up NTP after boot does exactly that.
The order things were written is what an audit is asked about.

Timestamps are stored as epoch microseconds plus the UTC offset in effect, the
same representation the historian uses, so a record reads back in the wall clock
it was written on.

## What is stored

Every attempt, whatever became of it: applied, refused, failed. A command
refused because control was disabled, or because a relay had not rested long
enough, is evidence about what the system was asked to do — often more
interesting than what it did.

Re-appending the same `command_id` is ignored rather than raising. A retried
write of a record already on disk is not a new event, and a journal that throws
while being written is a journal that loses the thing it was recording.

## What it does not do

**It does not expire.** Deliberately. A command record is a few hundred bytes
and a house generates a handful a day; a decade of them is smaller than an hour
of temperature samples.

**It does not sign or seal anything.** Anyone with write access to the file can
alter it with `sqlite3`. This is a record against forgetting, not against
tampering, and treating it as the second would be a claim the storage cannot
support.

**It does not replace the systemd journal.** Refusals and failures land here
because they are decisions; a stack trace does not.

## Testing

`tests/test_sqlite_journal.py`.

Covered: a command surviving a reopen; refusals and failures stored exactly like
successes; the wall clock preserved across a round trip; a duplicate ignored
rather than raising; order following the write sequence when a clock steps
backwards; per-relay audit; last-applied ignoring refusals because a refused
command operated nothing; the schema version recorded and a future one refused;
a naive timestamp refused; the class exposing no way to delete or rewrite; and
the case that motivated all of it — **a rate limit still in force after a
restart**, plus a journal that cannot remember not blocking the guard.
