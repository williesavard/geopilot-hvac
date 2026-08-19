"""Unit-file tests.

These are data files, not code, and nothing imports them — which is exactly why
they are worth testing. A unit is edited once during an install and then read by
systemd on a machine nobody is watching, and its two most likely failures are
silent: a sandbox directive that removes something the process needed, and a
`--bind` that grew an address.

The rule below about `/run/lock` is a regression guard for a real defect. Every
Modbus transport builds a `PortLock` by default, `ProtectSystem=strict` makes
/run read-only, and `port_lock` fails open when it cannot create its file. The
units shipped for weeks with locking that could never have engaged on the Pi.
"""

from __future__ import annotations

import configparser
from pathlib import Path

import pytest

UNITS = Path(__file__).resolve().parents[1] / "deploy" / "systemd"

SERVICES = sorted(UNITS.glob("*.service"))
LOOPBACK = "127.0.0.1"


def read(unit: Path) -> configparser.ConfigParser:
    """Parse a unit file.

    `strict=False` because systemd's list-valued directives (`DeviceAllow=`,
    `ReadWritePaths=`) legitimately repeat, and `optionxform` because directive
    names are case sensitive to systemd and would otherwise arrive lowercased.
    """

    parser = configparser.ConfigParser(strict=False, interpolation=None)
    parser.optionxform = str  # type: ignore[assignment]
    parser.read(unit, encoding="utf-8")
    return parser


def exec_start(unit: Path) -> str:
    """ExecStart as one line, with systemd's line continuations folded out."""

    return " ".join(read(unit)["Service"]["ExecStart"].split())


def test_units_are_present() -> None:
    """A failure here means the glob found nothing and every test below passed
    vacuously."""

    assert {unit.name for unit in SERVICES} == {
        "geopilot-control.service",
        "geopilot-monitor.service",
        "geopilot-poll.service",
    }


@pytest.mark.parametrize("unit", SERVICES, ids=lambda unit: unit.name)
def test_the_tool_it_runs_exists(unit: Path) -> None:
    """The installed path is /opt/geopilot; the file name must still be ours."""

    command = exec_start(unit)
    tool = next(word for word in command.split() if word.endswith(".py"))
    assert (UNITS.parents[1] / "tools" / Path(tool).name).is_file()


@pytest.mark.parametrize("unit", SERVICES, ids=lambda unit: unit.name)
def test_the_port_lock_directory_is_writable(unit: Path) -> None:
    """ProtectSystem=strict plus no ReadWritePaths is silent loss of locking."""

    service = read(unit)["Service"]
    assert service["ProtectSystem"] == "strict"
    assert "/run/lock" in service["ReadWritePaths"]


@pytest.mark.parametrize("unit", SERVICES, ids=lambda unit: unit.name)
def test_the_serial_adapter_stays_visible(unit: Path) -> None:
    """PrivateDevices=yes replaces /dev with a skeleton and the RS485 adapter
    disappears. Every unit here talks to one."""

    assert "PrivateDevices" not in read(unit)["Service"]


@pytest.mark.parametrize("unit", SERVICES, ids=lambda unit: unit.name)
def test_they_run_as_the_same_user(unit: Path) -> None:
    """The lock file and the WAL database are shared, so the processes must be
    able to open each other's files."""

    service = read(unit)["Service"]
    assert service["User"] == "geopilot"
    assert service["Group"] == "geopilot"


@pytest.mark.parametrize("unit", SERVICES, ids=lambda unit: unit.name)
def test_privileges_cannot_be_gained(unit: Path) -> None:
    assert read(unit)["Service"]["NoNewPrivileges"] == "true"


def control() -> Path:
    return UNITS / "geopilot-control.service"


def test_control_binds_loopback_and_says_so() -> None:
    """The single largest thing protecting a contactor."""

    command = exec_start(control())
    assert f"--bind {LOOPBACK}" in command
    assert command.count("--bind") == 1


def test_control_is_refused_the_network_by_the_kernel_too() -> None:
    """Defence in depth: a later edit to ExecStart must not be enough to expose
    relay control."""

    service = read(control())["Service"]
    assert service["IPAddressDeny"] == "any"
    assert service["IPAddressAllow"] == "localhost"


def test_control_keeps_a_blocked_syscall_visible() -> None:
    """Without SystemCallErrorNumber a filtered call is SIGSYS — a service that
    vanished with nothing in the journal explaining why."""

    service = read(control())["Service"]
    assert service["SystemCallFilter"] == "@system-service"
    assert service["SystemCallErrorNumber"] == "EPERM"


def test_control_restarts_but_not_forever() -> None:
    """Restarting is safe now that the rate limit is journalled, but a crash
    loop is still a problem restarting will not fix."""

    service = read(control())["Service"]
    assert service["Restart"] == "on-failure"
    assert int(service["StartLimitBurst"]) <= 5


def test_control_reaches_serial_and_nothing_else() -> None:
    service = read(control())["Service"]
    assert service["DevicePolicy"] == "closed"


def test_control_holds_no_exotic_socket() -> None:
    families = read(control())["Service"]["RestrictAddressFamilies"].split()
    assert set(families) == {"AF_UNIX", "AF_INET", "AF_INET6"}
