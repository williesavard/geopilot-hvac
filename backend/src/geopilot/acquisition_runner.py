"""Deterministic in-memory acquisition runner.

The runner executes declared acquisition requests in order and returns a local
report. It does not schedule work, retry, run asynchronously, create threads,
perform hardware I/O, emit alerts, or control HVAC equipment.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol

from geopilot.acquisition import (
    AcquisitionClock,
    AcquisitionPipeline,
    AcquisitionResult,
    failures,
    successful_measurements,
)
from geopilot.ingestion import utc_now


class AcquisitionRunnerError(ValueError):
    """Raised when an acquisition runner object is invalid."""


class RequestExecutor(Protocol):
    """Callable request executor used by the runner."""

    def __call__(self, pipeline: AcquisitionPipeline) -> tuple[AcquisitionResult, ...]:
        """Execute one acquisition request."""


@dataclass(frozen=True, slots=True)
class AcquisitionRequest:
    """One declared acquisition request."""

    request_id: str
    profile_id: str | None
    executor: RequestExecutor

    def __post_init__(self) -> None:
        _require_identifier(self.request_id, "request_id")
        _require_optional_identifier(self.profile_id, "profile_id")


@dataclass(frozen=True, slots=True)
class AcquisitionPlan:
    """Ordered set of acquisition requests."""

    plan_id: str
    requests: tuple[AcquisitionRequest, ...]

    def __post_init__(self) -> None:
        _require_identifier(self.plan_id, "plan_id")
        request_ids: set[str] = set()
        for request in self.requests:
            if request.request_id in request_ids:
                raise AcquisitionRunnerError(
                    f"Duplicate acquisition request: {request.request_id}"
                )
            request_ids.add(request.request_id)


@dataclass(frozen=True, slots=True)
class AcquisitionRunReport:
    """Deterministic report for one acquisition plan run."""

    plan_id: str
    started_at: datetime
    completed_at: datetime
    results: tuple[AcquisitionResult, ...]

    def __post_init__(self) -> None:
        _require_identifier(self.plan_id, "plan_id")
        _require_aware_datetime(self.started_at, "started_at")
        _require_aware_datetime(self.completed_at, "completed_at")
        if self.completed_at < self.started_at:
            raise AcquisitionRunnerError("completed_at must be after or equal to started_at")

    @property
    def success_count(self) -> int:
        """Return the number of successful results."""

        return len(successful_measurements(self.results))

    @property
    def failure_count(self) -> int:
        """Return the number of failed results."""

        return len(failures(self.results))

    @property
    def total_count(self) -> int:
        """Return the total number of results."""

        return len(self.results)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible report representation."""

        return _dataclass_to_dict(self) | {
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "total_count": self.total_count,
        }


class AcquisitionRunner:
    """Execute an acquisition plan once in deterministic request order."""

    def __init__(
        self,
        pipeline: AcquisitionPipeline,
        *,
        clock: AcquisitionClock = utc_now,
    ) -> None:
        self._pipeline = pipeline
        self._clock = clock

    def run(self, plan: AcquisitionPlan) -> AcquisitionRunReport:
        """Execute every request in a plan once."""

        started_at = self._clock()
        results: list[AcquisitionResult] = []

        for request in plan.requests:
            results.extend(request.executor(self._pipeline))

        completed_at = self._clock()
        return AcquisitionRunReport(
            plan_id=plan.plan_id,
            started_at=started_at,
            completed_at=completed_at,
            results=tuple(results),
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
        raise AcquisitionRunnerError(f"{field_name} must be a non-empty identifier")


def _require_optional_identifier(value: str | None, field_name: str) -> None:
    if value is not None:
        _require_identifier(value, field_name)


def _require_aware_datetime(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise AcquisitionRunnerError(f"{field_name} must be timezone-aware")
