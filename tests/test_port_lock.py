"""Port lock tests.

The claim worth proving is that two *processes* actually exclude each other, so
one test spawns a real subprocess. Everything else runs in-process.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest
from geopilot.port_lock import (
    LOCKING_AVAILABLE,
    PortBusyError,
    PortLock,
    lock_directory,
    lock_path,
)

pytestmark = pytest.mark.skipif(not LOCKING_AVAILABLE, reason="no fcntl on this platform")


def test_a_port_maps_to_one_lock_file(tmp_path: Path) -> None:
    assert lock_path("/dev/ttyUSB0", directory=tmp_path).name == "geopilot-dev-ttyUSB0.lock"


def test_different_ports_do_not_share_a_lock(tmp_path: Path) -> None:
    """Two adapters must not block each other."""

    first = lock_path("/dev/ttyUSB0", directory=tmp_path)
    second = lock_path("/dev/ttyUSB1", directory=tmp_path)

    assert first != second


def test_the_same_port_maps_to_the_same_lock_however_it_is_written(tmp_path: Path) -> None:
    assert lock_path("/dev/ttyUSB0", directory=tmp_path) == lock_path(
        "/dev/ttyUSB0", directory=tmp_path
    )


def test_a_lock_directory_is_chosen() -> None:
    assert lock_directory().is_dir()


def test_holding_the_lock_reports_that_it_worked(tmp_path: Path) -> None:
    lock = PortLock("/dev/ttyUSB0", directory=tmp_path)

    assert lock.active
    with lock.hold() as held:
        assert held is True
    lock.close()


def test_the_lock_file_is_created(tmp_path: Path) -> None:
    lock = PortLock("/dev/ttyUSB0", directory=tmp_path)

    assert lock.path.exists()
    lock.close()


def test_an_unusable_directory_degrades_instead_of_raising(tmp_path: Path) -> None:
    """No lock file means no coordination, which is where this started."""

    lock = PortLock("/dev/ttyUSB0", directory=tmp_path / "does" / "not" / "exist")

    assert not lock.active
    with lock.hold() as held:
        assert held is False


def test_a_second_holder_waits_rather_than_failing(tmp_path: Path) -> None:
    """The whole point: an exchange completes or waits, never interleaves."""

    first = PortLock("/dev/ttyUSB0", directory=tmp_path, timeout=5.0)
    second = PortLock("/dev/ttyUSB0", directory=tmp_path, timeout=5.0)
    order: list[str] = []

    def hold_briefly() -> None:
        with first.hold():
            order.append("first in")
            time.sleep(0.2)
            order.append("first out")

    worker = threading.Thread(target=hold_briefly)
    worker.start()
    time.sleep(0.05)

    with second.hold():
        order.append("second in")

    worker.join()
    first.close()
    second.close()

    assert order == ["first in", "first out", "second in"]


def test_waiting_past_the_timeout_is_reported(tmp_path: Path) -> None:
    """Beyond the timeout something is wrong that waiting longer will not fix."""

    holder = PortLock("/dev/ttyUSB0", directory=tmp_path)
    waiter = PortLock("/dev/ttyUSB0", directory=tmp_path, timeout=0.1)

    with holder.hold(), pytest.raises(PortBusyError, match="more than 0.1s"), waiter.hold():
        pass

    holder.close()
    waiter.close()


def test_the_lock_is_released_even_when_the_exchange_fails(tmp_path: Path) -> None:
    """A transport that raises mid-transaction must not wedge the bus."""

    lock = PortLock("/dev/ttyUSB0", directory=tmp_path)
    other = PortLock("/dev/ttyUSB0", directory=tmp_path, timeout=0.5)

    with pytest.raises(RuntimeError, match="bad crc"), lock.hold():
        raise RuntimeError("bad crc")

    with other.hold() as held:
        assert held is True

    lock.close()
    other.close()


def test_two_processes_exclude_each_other(tmp_path: Path) -> None:
    """Threads share a file table; processes are the case that actually matters."""

    marker = tmp_path / "held"
    script = textwrap.dedent(
        f"""
        import sys, time
        sys.path.insert(0, {str(Path(__file__).resolve().parents[1] / "backend/src")!r})
        from geopilot.port_lock import PortLock

        lock = PortLock("/dev/ttyUSB0", directory={str(tmp_path)!r})
        with lock.hold():
            open({str(marker)!r}, "w").write("in")
            time.sleep(0.6)
        """
    )

    child = subprocess.Popen([sys.executable, "-c", script])
    try:
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert marker.exists(), "the child never took the lock"

        ours = PortLock("/dev/ttyUSB0", directory=tmp_path, timeout=0.15)
        with pytest.raises(PortBusyError), ours.hold():
            pass
        ours.close()
    finally:
        child.wait(timeout=10)

    # Once the child exits, the bus is free again.
    after = PortLock("/dev/ttyUSB0", directory=tmp_path, timeout=2.0)
    with after.hold() as held:
        assert held is True
    after.close()


def test_closing_twice_is_harmless(tmp_path: Path) -> None:
    lock = PortLock("/dev/ttyUSB0", directory=tmp_path)

    lock.close()
    lock.close()

    assert not lock.active


def test_a_directory_given_as_a_string_works(tmp_path: Path) -> None:
    """Every other path-taking entry point in the project accepts either."""

    lock = PortLock("/dev/ttyUSB0", directory=str(tmp_path))

    assert lock.active
    lock.close()
