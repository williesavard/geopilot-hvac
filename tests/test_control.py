"""Command guard tests.

Every test uses a fake write transport. Nothing here reaches hardware.
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from geopilot.control import (
    CommandRequest,
    CommandStatus,
    ControlConfigurationError,
    ControlPolicy,
    ControlService,
    ControlTarget,
    InMemoryCommandJournal,
    RefusalCode,
)
from geopilot.modbus_write import (
    FakeModbusWriteTransport,
    ModbusWriteError,
    ModbusWriteErrorCode,
)

STAMP = datetime(2026, 8, 16, 12, 0, 0, tzinfo=UTC)

DAMPER = ControlTarget(
    target_id="damper_zone_1",
    unit_id=1,
    address=0,
    minimum_interval_seconds=60,
    description="Zone 1 damper",
)


def command(closed: bool = True, target: str = "damper_zone_1") -> CommandRequest:
    return CommandRequest(
        command_id=f"cmd-{target}-{closed}",
        target_id=target,
        closed=closed,
        reason="zone 1 calling for heat",
    )


class Clock:
    """Advanceable clock, so rate limiting is tested without sleeping."""

    def __init__(self, start: datetime = STAMP) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


def service(
    *,
    enabled: bool = True,
    targets: tuple[ControlTarget, ...] = (DAMPER,),
    transport: FakeModbusWriteTransport | None = None,
    clock: Clock | None = None,
) -> tuple[ControlService, FakeModbusWriteTransport, InMemoryCommandJournal]:
    write = transport or FakeModbusWriteTransport()
    journal = InMemoryCommandJournal()
    return (
        ControlService(
            ControlPolicy(enabled=enabled, targets=targets),
            write,
            journal=journal,
            clock=clock or Clock(),
        ),
        write,
        journal,
    )


def test_control_is_disabled_by_default() -> None:
    """A policy that says nothing about control grants none."""

    assert ControlPolicy().enabled is False


def test_a_disabled_policy_refuses_everything() -> None:
    control, write, journal = service(enabled=False)

    record = control.execute(command())

    assert record.status is CommandStatus.REFUSED
    assert RefusalCode.CONTROL_DISABLED in record.detail
    assert write.writes == []
    assert len(journal.records) == 1


def test_an_unlisted_target_is_refused() -> None:
    control, write, _ = service()

    record = control.execute(command(target="compressor_contactor"))

    assert record.status is CommandStatus.REFUSED
    assert RefusalCode.UNKNOWN_TARGET in record.detail
    assert write.writes == []


def test_a_permitted_command_reaches_the_transport() -> None:
    control, write, _ = service()

    record = control.execute(command(closed=True))

    assert record.status is CommandStatus.APPLIED
    assert len(write.writes) == 1
    assert write.writes[0].unit_id == 1
    assert write.writes[0].address == 0
    assert write.writes[0].closed is True


def test_rate_limiting_refuses_a_second_command_too_soon() -> None:
    clock = Clock()
    control, write, _ = service(clock=clock)

    first = control.execute(command(closed=True))
    clock.advance(30)
    second = control.execute(command(closed=False))

    assert first.status is CommandStatus.APPLIED
    assert second.status is CommandStatus.REFUSED
    assert RefusalCode.RATE_LIMITED in second.detail
    assert "30.0s remaining" in second.detail
    assert len(write.writes) == 1


def test_rate_limiting_allows_a_command_after_the_interval() -> None:
    clock = Clock()
    control, write, _ = service(clock=clock)

    control.execute(command(closed=True))
    clock.advance(60)
    second = control.execute(command(closed=False))

    assert second.status is CommandStatus.APPLIED
    assert len(write.writes) == 2


def test_a_refused_command_does_not_restart_the_rate_limit() -> None:
    """A refusal must not extend the window, or a caller could starve itself."""

    clock = Clock()
    control, write, _ = service(clock=clock)

    control.execute(command(closed=True))
    clock.advance(30)
    control.execute(command(closed=False))
    clock.advance(30)
    third = control.execute(command(closed=False))

    assert third.status is CommandStatus.APPLIED
    assert len(write.writes) == 2


def test_a_transport_failure_is_recorded_not_raised() -> None:
    write = FakeModbusWriteTransport(
        errors={
            "damper_zone_1": ModbusWriteError(
                code=ModbusWriteErrorCode.NOT_ACKNOWLEDGED,
                message="relay did not echo",
            )
        }
    )
    control, _, journal = service(transport=write)

    record = control.execute(command())

    assert record.status is CommandStatus.FAILED
    assert "not_acknowledged" in record.detail
    assert journal.records[-1].status is CommandStatus.FAILED


def test_a_failed_command_does_not_start_the_rate_limit() -> None:
    """A write that did not happen must not block the retry."""

    write = FakeModbusWriteTransport(
        errors={
            "damper_zone_1": ModbusWriteError(
                code=ModbusWriteErrorCode.TIMEOUT,
                message="no answer",
            )
        }
    )
    clock = Clock()
    control, _, _ = service(transport=write, clock=clock)

    control.execute(command())
    clock.advance(1)
    second = control.execute(command())

    assert second.status is CommandStatus.FAILED


def test_missing_transport_fails_rather_than_pretending() -> None:
    control = ControlService(
        ControlPolicy(enabled=True, targets=(DAMPER,)),
        None,
        clock=Clock(),
    )

    record = control.execute(command())

    assert record.status is CommandStatus.FAILED
    assert "no write transport" in record.detail


def test_every_attempt_is_journalled_with_its_reason() -> None:
    control, _, journal = service()

    control.execute(command(closed=True))
    control.execute(command(target="unknown"))

    assert len(journal.records) == 2
    assert [record.status for record in journal.records] == [
        CommandStatus.APPLIED,
        CommandStatus.REFUSED,
    ]
    assert all(record.reason == "zone 1 calling for heat" for record in journal.records)


def test_a_record_serializes_to_json_safe_data() -> None:
    control, _, _ = service()

    payload = control.execute(command()).to_dict()

    assert payload["status"] == "applied"
    assert payload["decided_at"] == "2026-08-16T12:00:00Z"
    assert payload["reason"] == "zone 1 calling for heat"


def test_journal_reports_the_last_applied_time() -> None:
    clock = Clock()
    control, _, journal = service(clock=clock)

    control.execute(command(closed=True))
    clock.advance(60)
    control.execute(command(closed=False))

    assert journal.last_applied_at("damper_zone_1") == STAMP + timedelta(seconds=60)
    assert journal.last_applied_at("other") is None


def test_a_command_requires_a_reason() -> None:
    with pytest.raises(ControlConfigurationError, match="reason"):
        CommandRequest(command_id="c", target_id="t", closed=True, reason="  ")


def test_targets_reject_invalid_fields() -> None:
    with pytest.raises(ControlConfigurationError, match="minimum_interval_seconds"):
        ControlTarget(
            target_id="t", unit_id=1, address=0, minimum_interval_seconds=-1
        )
    with pytest.raises(ControlConfigurationError, match="unit_id"):
        ControlTarget(target_id="t", unit_id=999, address=0, minimum_interval_seconds=1)


def test_duplicate_targets_are_rejected() -> None:
    with pytest.raises(ControlConfigurationError, match="duplicate target"):
        ControlPolicy(enabled=True, targets=(DAMPER, DAMPER))


def test_the_guard_never_caches_physical_relay_state() -> None:
    """Assuming a contact is where you left it is how a controller drifts.

    Commanding the same state twice must still reach the transport, because
    something else may have moved the relay in between.
    """

    clock = Clock()
    control, write, _ = service(clock=clock)

    control.execute(command(closed=True))
    clock.advance(60)
    control.execute(command(closed=True))

    assert len(write.writes) == 2
    assert [item.closed for item in write.writes] == [True, True]


def test_control_module_does_not_reach_the_domain_or_storage() -> None:
    source = Path("backend/src/geopilot/control.py").read_text()
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    assert not (
        imported
        & {
            "geopilot.domain",
            "geopilot.historian",
            "geopilot.sqlite_historian",
            "geopilot.runtime",
            "geopilot.snapshot",
        }
    )
