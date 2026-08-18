"""Serialise access to one serial port between GeoPilot processes.

Three things reach for the same RS485 segment: the acquisition timer every
minute, the control surface when a relay is operated, and the probe whenever
somebody presses the button. Nothing coordinated them, so whoever asked second
got an error.

**The granularity is a transaction, not a port.** Holding the lock for a port's
lifetime looks tidier and is wrong here: the acquisition session opens its ports
and never closes them, so a lifetime lock would let the long-running monitor
service hold the bus forever and starve everything else. A Modbus RTU segment is
shared by design — what must not interleave is one request and its response, and
that is exactly what this covers.

That is also the failure this prevents. Without it, process A writes a request,
process B writes its own before A has read, and A reads B's answer. Each frame is
intact and CRC-correct, so nothing detects the swap. With it, an exchange
completes or waits.

**It fails open, deliberately, and this is not the fail-open pattern to worry
about.** If the lock file cannot be created the behaviour is what it has always
been: whoever gets the port wins and the other sees an error. Nothing unsafe
becomes possible, because a lost race produces a failed read or a write whose
echo does not verify — never a silently wrong command. Refusing to poll because
a lock file could not be made would stop the recording, which is the one thing
worth protecting here.
"""

from __future__ import annotations

import os
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path

try:  # pragma: no cover - the fallback is exercised by its own test
    import fcntl

    LOCKING_AVAILABLE = True
except ImportError:  # pragma: no cover - Windows has no fcntl
    LOCKING_AVAILABLE = False

DEFAULT_TIMEOUT_SECONDS = 5.0
"""How long to wait for the bus before giving up.

Longer than any single Modbus transaction and shorter than a poll interval. A
caller that waits this long has been blocked by something that is not a
transaction, and reporting that beats waiting silently.
"""

RETRY_SECONDS = 0.02
"""How often to re-attempt a held lock.

`flock` can block properly, but a blocking call cannot be bounded by a timeout
without signals. Polling every 20 ms costs nothing against transactions that take
tens of milliseconds and keeps the timeout honest.
"""

LOCK_DIRECTORIES = ("/run/lock", "/var/lock")
"""Where lock files are looked for, in order, before falling back to the temp dir.

Both are tmpfs on a Raspberry Pi, so a stale lock cannot survive a reboot.
"""


class PortBusyError(RuntimeError):
    """Raised when the bus could not be obtained within the timeout."""


def lock_directory() -> Path:
    """The first writable conventional lock directory, or the temp directory."""

    for candidate in LOCK_DIRECTORIES:
        path = Path(candidate)
        if path.is_dir() and os.access(path, os.W_OK):
            return path
    return Path(tempfile.gettempdir())


def lock_path(port: str, *, directory: str | Path | None = None) -> Path:
    """The lock file for one port.

    The device path is flattened into the file name rather than nested, so two
    ports cannot collide and no directories have to be created. `/dev/ttyUSB0`
    becomes `geopilot-dev-ttyUSB0.lock`.
    """

    flattened = "".join(
        character if character.isalnum() else "-" for character in port
    ).strip("-")
    root = Path(directory) if directory is not None else lock_directory()
    return root / f"geopilot-{flattened}.lock"


class PortLock:
    """An advisory lock on one serial port, held only across a transaction.

    The lock file is opened once and kept open; each transaction takes and
    releases the advisory lock on that descriptor. Opening a file per read would
    cost more than the reads.
    """

    __slots__ = ("_path", "_timeout", "_handle", "_available")

    def __init__(
        self,
        port: str,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        directory: str | Path | None = None,
    ) -> None:
        self._path = lock_path(port, directory=directory)
        self._timeout = timeout
        self._handle: int | None = None
        self._available = LOCKING_AVAILABLE

        if not self._available:
            return

        try:
            self._handle = os.open(self._path, os.O_RDWR | os.O_CREAT, 0o666)
        except OSError:
            # No lock file means no coordination, which is where this started.
            self._available = False

    @property
    def path(self) -> Path:
        return self._path

    @property
    def active(self) -> bool:
        """Whether this lock can actually coordinate anything."""

        return self._available and self._handle is not None

    @contextmanager
    def hold(self) -> Iterator[bool]:
        """Hold the bus for one exchange.

        Yields True when the lock was obtained, False when locking is
        unavailable and the caller is proceeding uncoordinated — the caller is
        told rather than left to assume it was protected.

        Raises `PortBusyError` if the lock exists and stays held past the
        timeout, because at that point something is wrong that waiting longer
        will not fix.
        """

        if not self.active:
            yield False
            return

        assert self._handle is not None
        deadline = time.monotonic() + self._timeout

        while True:
            try:
                fcntl.flock(self._handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise PortBusyError(
                        f"another GeoPilot process has held {self._path.name} for more "
                        f"than {self._timeout:g}s"
                    ) from None
                time.sleep(RETRY_SECONDS)

        try:
            yield True
        finally:
            with suppress(OSError):  # unlocking our own descriptor
                fcntl.flock(self._handle, fcntl.LOCK_UN)

    def close(self) -> None:
        """Release the descriptor. The advisory lock goes with it."""

        if self._handle is not None:
            with suppress(OSError):
                os.close(self._handle)
            self._handle = None
