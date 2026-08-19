# Security Review: the Control Surface

**Status:** Complete; every confirmed finding fixed in the same change
**Scope:** everything that listens or writes — `control_server`, `control`,
`sqlite_journal`, the rendered page and its script, the systemd units, the
repository's handling of private files
**Date:** 2026-08-19

Method: full read of the five surfaces above, and no finding reported on
belief — each suspicion was either reproduced or demonstrated false. The
threat model is the one the ADR states: loopback-only, configuration trusted
(the operator owns the machine), the browser and its headers untrusted, and
malware already running on the Pi out of scope.

## Findings

### 1. The journal raised from every request thread — HIGH, fixed

`SqliteCommandJournal` opened its connection on the main thread;
`ThreadingHTTPServer` serves every command on a request thread; sqlite3
refuses cross-thread use by default. Reproduced: the first HTTP command
raises `ProgrammingError` at the moment it should be recorded.

The ordering made it worse than a crash. `write_coil` runs **before**
`_record`, so the relay moved, then journalling raised — an operated relay
with no audit record and a client shown an error. The page renderer got the
per-request-connection fix when the server became threaded; the journal did
not, and no test started the real server, so nothing saw it.

Fixed with `check_same_thread=False` plus an internal lock around every use
of the connection, and a live-server test that drives a real command through
a real socket into the real journal.

### 2. The rate limit was check-then-act with no gate — MEDIUM, fixed

`ControlService.execute` read "last operated" and later wrote it, with
nothing serialising the two. Two concurrent commands — a double-click is
enough — both read "long enough ago" and both reached the transport, which
is precisely the relay chatter `minimum_interval_seconds` exists to prevent.

Fixed with a lock across the whole evaluate-write-record path. Holding it
during the serial write is a feature, not a cost: RS485 demands serialised
commands anyway. The regression test parks one thread inside the window and
proves the second is refused.

### 3. A negative Content-Length bypassed the body cap — LOW, fixed

`int()` accepts `-1`, `-1 > MAX_BODY_BYTES` is false, and `rfile.read(-1)`
on a socket reads until the peer closes it: one header turning into an
unbounded allocation. Token-gated, so loopback-and-authorised only — fixed
regardless, since the cap exists for exactly this caller.

### 4. A non-ASCII token crashed the comparison — LOW, fixed

`secrets.compare_digest` raises `TypeError` on non-ASCII `str`, and a header
is attacker-shaped input. The failure was closed (no response, thread dies)
but a hostile byte must read as *wrong token*, not as a traceback. Both sides
are now compared as bytes.

### 5. `_escape` ignored the single quote — hardening, fixed

Every interpolation into a single-quoted HTML attribute happened to be an
internal constant today, so this was latent, not live. It is the kind of
latent that becomes an XSS the day a sensor id lands in one. `'` now escapes
to `&#39;`.

## Verified sound

Worth recording so the next review does not re-litigate them:

- **the doorway**: Host checked against loopback names (fail-closed on
  anything odd, including `Origin: null`), Origin checked when present, token
  compared constant-time, and the token travels in a header — never a URL,
  so never in logs or history;
- **the page**: every dynamic value the server renders goes through
  `_escape`; everything the script renders goes through `textContent`; the
  embedded JSON escapes `</`; CSP allows no fetch, no frame, no external
  anything;
- **the journal**: append-only, parameterised SQL throughout, ordered by
  `seq` so a stepped clock cannot rewrite history, `INSERT OR IGNORE` on
  `command_id` so a retry is not a second event;
- **the guard**: whitelist, rate limit and refusal-recording live behind the
  HTTP layer, not in it; the displayed relay state is read back from the bus,
  never remembered;
- **the units**: loopback pinned in `ExecStart` *and* enforced by
  `IPAddressDeny`; the private files (`SITE.md`, `BENCH_NOTES.md`,
  `config/`) are ignored and verified untracked.

## Accepted, not fixed

- **any local process can take the token** by fetching the page. The ADR
  accepts this: loopback plus the four header checks defend against the
  browser being turned, not against code already on the Pi;
- **a crash between `write_coil` and `_record`** loses one audit record. The
  window is milliseconds and the fix (journalling intent before outcome)
  buys a two-phase journal for a solo installation; noted for the automatic
  control ADR, where the calculus changes;
- **`[::1]:8322` as a Host value is refused** — the port-stripping is
  IPv4-shaped. Fail-closed, cosmetic, and loopback IPv4 is what the tool
  binds and announces.
