"""Deterministic simulated polling cycles.

The polling runner executes declared acquisition plans across ordered cycles.
It does not sleep, schedule work, retry, run asynchronously, create threads,
perform hardware I/O, emit alerts, or control HVAC equipment.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from geopilot.acquisition import AcquisitionClock
from geopilot.acquisition_runner import AcquisitionPlan, AcquisitionRunner, AcquisitionRunReport
from geopilot.ingestion import utc_now


class SimulatedPollingError(ValueError):
    """Raised when a simulated polling object is invalid."""


@dataclass(frozen=True, slots=True)
class SimulatedPollingCycle:
    """One declared simulated polling cycle."""

    cycle_id: str
    acquisition_plan: AcquisitionPlan

    def __post_init__(self) -> None:
        _require_identifier(self.cycle_id, "cycle_id")


@dataclass(frozen=True, slots=True)
class SimulatedPollingPlan:
    """Ordered set of simulated polling cycles."""

    plan_id: str
    cycles: tuple[SimulatedPollingCycle, ...]

    def __post_init__(self) -> None:
        _require_identifier(self.plan_id, "plan_id")
        cycle_ids: set[str] = set()
        for cycle in self.cycles:
            if cycle.cycle_id in cycle_ids:
                raise SimulatedPollingError(f"Duplicate polling cycle: {cycle.cycle_id}")
            cycle_ids.add(cycle.cycle_id)


@dataclass(frozen=True, slots=True)
class SimulatedPollingCycleReport:
    """Report for one simulated polling cycle."""

    cycle_id: str
    run_report: AcquisitionRunReport

    def __post_init__(self) -> None:
        _require_identifier(self.cycle_id, "cycle_id")

    @property
    def success_count(self) -> int:
        """Return the number of successful acquisition results in this cycle."""

        return self.run_report.success_count

    @property
    def failure_count(self) -> int:
        """Return the number of failed acquisition results in this cycle."""

        return self.run_report.failure_count

    @property
    def total_count(self) -> int:
        """Return the total number of acquisition results in this cycle."""

        return self.run_report.total_count

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible cycle report representation."""

        return _dataclass_to_dict(self) | {
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "total_count": self.total_count,
        }


@dataclass(frozen=True, slots=True)
class SimulatedPollingReport:
    """Deterministic report for a simulated polling plan."""

    plan_id: str
    started_at: datetime
    completed_at: datetime
    cycle_reports: tuple[SimulatedPollingCycleReport, ...]

    def __post_init__(self) -> None:
        _require_identifier(self.plan_id, "plan_id")
        _require_aware_datetime(self.started_at, "started_at")
        _require_aware_datetime(self.completed_at, "completed_at")
        if self.completed_at < self.started_at:
            raise SimulatedPollingError("completed_at must be after or equal to started_at")

    @property
    def cycle_count(self) -> int:
        """Return the number of executed cycles."""

        return len(self.cycle_reports)

    @property
    def success_count(self) -> int:
        """Return the number of successful acquisition results."""

        return sum(report.success_count for report in self.cycle_reports)

    @property
    def failure_count(self) -> int:
        """Return the number of failed acquisition results."""

        return sum(report.failure_count for report in self.cycle_reports)

    @property
    def total_count(self) -> int:
        """Return the total number of acquisition results."""

        return sum(report.total_count for report in self.cycle_reports)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible polling report representation."""

        return _dataclass_to_dict(self) | {
            "cycle_count": self.cycle_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "total_count": self.total_count,
        }


class SimulatedPollingRunner:
    """Execute simulated polling cycles in deterministic order."""

    def __init__(
        self,
        acquisition_runner: AcquisitionRunner,
        *,
        clock: AcquisitionClock = utc_now,
    ) -> None:
        self._acquisition_runner = acquisition_runner
        self._clock = clock

    def run(self, plan: SimulatedPollingPlan) -> SimulatedPollingReport:
        """Execute each cycle's acquisition plan once."""

        started_at = self._clock()
        cycle_reports: list[SimulatedPollingCycleReport] = []

        for cycle in plan.cycles:
            cycle_reports.append(
                SimulatedPollingCycleReport(
                    cycle_id=cycle.cycle_id,
                    run_report=self._acquisition_runner.run(cycle.acquisition_plan),
                )
            )

        completed_at = self._clock()
        return SimulatedPollingReport(
            plan_id=plan.plan_id,
            started_at=started_at,
            completed_at=completed_at,
            cycle_reports=tuple(cycle_reports),
        )


def _serialize_value(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value

    if isinstance(value, datetime):
        if value.tzinfo is UTC or value.utcoffset() == UTC.utcoffset(value):
            return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
        return value.isoformat()

    if isinstance(value, tuple):
        return [_serialize_value(item) for item in value]

    if hasattr(value, "to_dict"):
        return value.to_dict()

    if hasattr(value, "__dataclass_fields__"):
        return _dataclass_to_dict(value)

    return value


def _dataclass_to_dict(instance: Any) -> dict[str, Any]:
    return {
        field.name: _serialize_value(getattr(instance, field.name))
        for field in fields(instance)
    }


def _require_identifier(value: str, field_name: str) -> None:
    if not value.strip():
        raise SimulatedPollingError(f"{field_name} must be a non-empty identifier")


def _require_aware_datetime(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SimulatedPollingError(f"{field_name} must be timezone-aware")
