# Port Lock

**Status:** Implemented
**Scope:** serialising one serial port between GeoPilot processes

Three things reach for the same RS485 segment: the acquisition timer every
minute, the control surface when a relay is operated, and the probe whenever
somebody presses the button. Nothing coordinated them.

## The failure it prevents

Not "two processes cannot open the port" — they can. The real hazard is subtler:

```text
poller  writes request  →
probe   writes request  →
poller  reads  ← probe's answer
probe   reads  ← poller's answer
```

Every frame is intact and every CRC is correct, so **nothing detects the swap**.
The poller records a value from the wrong register, and the control surface
"confirms" a relay it never heard from.

Measured, two processes doing five exchanges each against a stand-in port:

```text
without the lock: 10 interleaved exchanges out of 10
with the lock:     0 interleaved exchanges out of 10
```

## The granularity is a transaction, not a port

Holding the lock for a port's lifetime looks tidier and is wrong here. The
acquisition session opens its ports and **never closes them** — a lifetime lock
would let the long-running monitor service hold the bus forever and starve
everything else.

An RS485 segment is shared by design. What must not interleave is one request and
its answer, so that is what is covered: the exchange, inside the transport,
which means every caller is coordinated without a single call site changing.

## Where the lock lives

`flock` on a file named after the port, in `/run/lock` or `/var/lock` if either
is writable, otherwise the temp directory. `/dev/ttyUSB0` becomes
`geopilot-dev-ttyUSB0.lock`. Both conventional directories are tmpfs on a
Raspberry Pi, so a stale lock cannot survive a reboot.

Two adapters get two lock files and never block each other.

The lock file is opened once per transport and the advisory lock is taken and
released per exchange. Opening a file for every read would cost more than the
reads do.

## Waiting, and giving up

Five seconds by default: longer than any single transaction and shorter than a
poll interval. Past it, `PortBusyError` becomes an ordinary transport error, so a
blocked read fails the way an unanswered read already fails and a blocked write
is journalled the way any failed command is.

A caller that waited five seconds was blocked by something that is not a
transaction, and saying so beats waiting silently.

## It fails open, deliberately

If the lock file cannot be created, everything proceeds uncoordinated and
`hold()` says so by yielding `False` rather than letting a caller assume it was
protected.

**This is not the fail-open pattern to worry about.** Without the lock the
behaviour is exactly what it has always been: whoever gets the port wins, and the
loser sees an error. Nothing unsafe becomes newly possible, because a lost race
produces a failed read, or a write whose echo does not verify — never a silently
wrong command. Refusing to poll because a lock file could not be made would stop
the recording, which is the thing actually worth protecting.

The same reasoning covers platforms with no `fcntl`. There is no Windows target
here; if there were, it would run uncoordinated and say so.

## What it does not do

**It does not coordinate with anything outside GeoPilot.** Another program on the
machine talking to the same adapter is not participating. The classic UUCP
`LCK..ttyUSB0` convention would interoperate with some of them and is not
implemented.

**It does not make the bus faster.** Three processes sharing one segment now
queue instead of colliding, which is better and is still a queue. If the probe
starts feeling slow during commissioning, the poller holding the bus is why.

**It does not protect the 1-Wire bus**, which needs no protection: the kernel
serialises sysfs reads.

## Testing

`tests/test_port_lock.py`.

Covered: one lock file per port and separate files for separate ports, a second
holder waiting rather than failing, the timeout being reported, the lock being
released when the exchange raises, an unusable directory degrading instead of
raising, and — the case that actually matters — **a real subprocess holding the
lock while this process is refused**, then the bus freeing when the child exits.
