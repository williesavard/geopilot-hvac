"""Command guard for equipment control.

Every command GeoPilot issues passes through here. The write transport will
happily operate a relay as fast as it is called; this module is what decides
whether it should, and records what happened either way.

Implements decision 5 of ``docs/CONTROL_BOUNDARY_ADR.md``. It performs no I/O
beyond delegating an approved command to a write transport, opens no port,
schedules nothing, and knows nothing about HVAC.

One rule is enforced by omission rather than by code: **this module never
caches the physical state of a relay**. Assuming a contact is where you last
commanded it is how a controller and a building drift apart after a power cycle
somebody else caused.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Protocol

from geopilot.modbus_write import (
    ModbusCoilWriteRequest,
    ModbusWriteError,
    ModbusWriteTransport,
)


class ControlConfigurationError(ValueError):
    """Raised when a control policy or target is invalid."""


class CommandStatus(StrEnum):
    """What became of a command."""

    APPLIED = "applied"
    REFUSED = "refused"
    FAILED = "failed"


class RefusalCode(StrEnum):
    """Why a command was refused before reaching any hardware."""

    CONTROL_DISABLED = "control_disabled"
    UNKNOWN_TARGET = "unknown_target"
    RATE_LIMITED = "rate_limited"


@dataclass(frozen=True, slots=True)
class ControlTarget:
    """One relay GeoPilot is permitted to operate.

    `minimum_interval_seconds` is not a performance setting. Relay chatter is
    how contactors weld and compressors die, so every target declares the
    fastest it may be operated, and the guard enforces it.
    """

    target_id: str
    unit_id: int
    address: int
    minimum_interval_seconds: float
    description: str = ""

    def __post_init__(self) -> None:
        if not self.target_id.strip():
            raise ControlConfigurationError("target_id must be a non-empty identifier")
        if isinstance(self.unit_id, bool) or not isinstance(self.unit_id, int):
            raise ControlConfigurationError("unit_id must be an integer")
        if self.unit_id < 0 or self.unit_id > 0xFF:
            raise ControlConfigurationError("unit_id must be an unsigned 8-bit value")
        if isinstance(self.address, bool) or not isinstance(self.address, int):
            raise ControlConfigurationError("address must be an integer")
        if self.address < 0 or self.address > 0xFFFF:
            raise ControlConfigurationError("address must be an unsigned 16-bit value")
        if self.minimum_interval_seconds < 0:
            raise ControlConfigurationError("minimum_interval_seconds must not be negative")


@dataclass(frozen=True, slots=True)
class ControlPolicy:
    """What control is permitted, if any.

    `enabled` defaults to False. A configuration that says nothing about control
    grants none, which is the behaviour the ADR requires.
    """

    enabled: bool = False
    targets: tuple[ControlTarget, ...] = ()

    def __post_init__(self) -> None:
        seen: set[str] = set()
        for target in self.targets:
            if target.target_id in seen:
                raise ControlConfigurationError(f"duplicate target: {target.target_id}")
            seen.add(target.target_id)

    def target(self, target_id: str) -> ControlTarget | None:
        """Return a whitelisted target, or None if it is not permitted."""

        for candidate in self.targets:
            if candidate.target_id == target_id:
                return candidate
        return None


@dataclass(frozen=True, slots=True)
class CommandRequest:
    """One request to place a relay in a state.

    `reason` is required. A control system that cannot say why it did something
    is undebuggable after an incident, and an incident is exactly when the
    question gets asked.
    """

    command_id: str
    target_id: str
    closed: bool
    reason: str

    def __post_init__(self) -> None:
        for value, name in (
            (self.command_id, "command_id"),
            (self.target_id, "target_id"),
            (self.reason, "reason"),
        ):
            if not value.strip():
                raise ControlConfigurationError(f"{name} must be non-empty")
        if not isinstance(self.closed, bool):
            raise ControlConfigurationError("closed must be a boolean")


@dataclass(frozen=True, slots=True)
class CommandRecord:
    """Audit record for one command attempt, applied or not."""

    command_id: str
    target_id: str
    closed: bool
    reason: str
    status: CommandStatus
    detail: str
    decided_at: datetime

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-safe representation."""

        return {
            "command_id": self.command_id,
            "target_id": self.target_id,
            "closed": self.closed,
            "reason": self.reason,
            "status": self.status.value,
            "detail": self.detail,
            "decided_at": self.decided_at.astimezone(UTC)
            .isoformat()
            .replace("+00:00", "Z"),
        }


class CommandJournal(Protocol):
    """Storage-independent audit journal."""

    def append(self, record: CommandRecord) -> None:
        """Record one command attempt."""


@dataclass(slots=True)
class InMemoryCommandJournal:
    """Audit journal for tests and bench work."""

    records: list[CommandRecord] = field(default_factory=list)

    def append(self, record: CommandRecord) -> None:
        self.records.append(record)

    def last_applied_at(self, target_id: str) -> datetime | None:
        """Return when a target was last successfully operated."""

        for record in reversed(self.records):
            if record.target_id == target_id and record.status is CommandStatus.APPLIED:
                return record.decided_at
        return None


class ControlService:
    """Decide, execute and record commands.

    Refusals and failures are returned, never raised. A caller driving several
    targets must not lose the rest because one was rate limited.
    """

    def __init__(
        self,
        policy: ControlPolicy,
        transport: ModbusWriteTransport | None = None,
        *,
        journal: CommandJournal | None = None,
        clock: object = None,
    ) -> None:
        self._policy = policy
        self._transport = transport
        self._journal = journal or InMemoryCommandJournal()
        self._clock = clock if callable(clock) else _utc_now
        self._gate = threading.Lock()
        self._last_applied: dict[str, datetime] = {}

    @property
    def journal(self) -> CommandJournal:
        """Return the audit journal this service writes to."""

        return self._journal

    def execute(self, command: CommandRequest) -> CommandRecord:
        """Evaluate a command, execute it if permitted, and record the outcome.

        Serialised, because the surface serves each request on its own thread
        and the rate limit is check-then-act: two concurrent commands for the
        same relay would both read "long enough ago" and both write, which is
        exactly the chatter the interval exists to prevent. Holding the lock
        across the write also serialises the bus access, which RS485 demands
        anyway.
        """

        with self._gate:
            return self._execute(command)

    def _execute(self, command: CommandRequest) -> CommandRecord:
        now = self._clock()

        if not self._policy.enabled:
            return self._record(command, CommandStatus.REFUSED, RefusalCode.CONTROL_DISABLED, now)

        target = self._policy.target(command.target_id)
        if target is None:
            return self._record(command, CommandStatus.REFUSED, RefusalCode.UNKNOWN_TARGET, now)

        if self._transport is None:
            return self._record(
                command,
                CommandStatus.FAILED,
                "no write transport is configured",
                now,
            )

        previous = self._remember(target.target_id)
        if previous is not None:
            elapsed = now - previous
            minimum = timedelta(seconds=target.minimum_interval_seconds)
            if elapsed < minimum:
                remaining = (minimum - elapsed).total_seconds()
                return self._record(
                    command,
                    CommandStatus.REFUSED,
                    f"{RefusalCode.RATE_LIMITED}: {remaining:.1f}s remaining",
                    now,
                )

        try:
            self._transport.write_coil(
                ModbusCoilWriteRequest(
                    request_id=command.command_id,
                    target_id=target.target_id,
                    unit_id=target.unit_id,
                    address=target.address,
                    closed=command.closed,
                )
            )
        except ModbusWriteError as error:
            return self._record(command, CommandStatus.FAILED, str(error), now)

        self._last_applied[target.target_id] = now
        return self._record(command, CommandStatus.APPLIED, "", now)

    def _remember(self, target_id: str) -> datetime | None:
        """When this target was last operated, asking the journal if need be.

        The in-process cache is empty after a restart, and a rate limit that
        resets when the process does is not a rate limit — a relay operated ten
        seconds before a restart could be operated again immediately after it,
        which is exactly the chatter the interval exists to prevent.

        A journal that cannot answer simply returns nothing, and the guard
        behaves as it did before.
        """

        cached = self._last_applied.get(target_id)
        if cached is not None:
            return cached

        ask = getattr(self._journal, "last_applied_at", None)
        if not callable(ask):
            return None

        try:
            remembered = ask(target_id)
        except Exception:  # noqa: BLE001 - a journal fault must not block a refusal
            return None

        if isinstance(remembered, datetime):
            self._last_applied[target_id] = remembered
            return remembered
        return None

    def _record(
        self,
        command: CommandRequest,
        status: CommandStatus,
        detail: object,
        decided_at: datetime,
    ) -> CommandRecord:
        record = CommandRecord(
            command_id=command.command_id,
            target_id=command.target_id,
            closed=command.closed,
            reason=command.reason,
            status=status,
            detail=str(detail),
            decided_at=decided_at,
        )
        self._journal.append(record)
        return record


def _utc_now() -> datetime:
    return datetime.now(UTC)
