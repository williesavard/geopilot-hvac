"""Structured acquisition results for adapter pipelines.

This module keeps acquisition success and failure reporting separate from the
core domain model. It does not perform hardware I/O, implement a protocol, emit
alerts, or control HVAC equipment.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from geopilot.domain import Measurement
from geopilot.ingestion import (
    IncompatibleMeasurementUnitError,
    IngestionError,
    IngestionService,
    RawMeasurement,
    utc_now,
)
from geopilot.registry import AssetNotFoundError

AcquisitionClock = Callable[[], datetime]


class AcquisitionResultError(ValueError):
    """Raised when an acquisition result object is invalid."""


class AcquisitionErrorCode(StrEnum):
    """Structured acquisition error categories."""

    READ_FAILED = "read_failed"
    DECODE_FAILED = "decode_failed"
    NORMALIZATION_FAILED = "normalization_failed"
    SENSOR_NOT_FOUND = "sensor_not_found"
    PROFILE_INCOMPLETE = "profile_incomplete"
    PARTIAL_READ = "partial_read"
    UNKNOWN_DEVICE = "unknown_device"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class AcquisitionContext:
    """Identifiers that locate an acquisition attempt."""

    source_id: str
    profile_id: str | None
    register_id: str | None
    sensor_id: str | None

    def __post_init__(self) -> None:
        _require_identifier(self.source_id, "source_id")
        _require_optional_identifier(self.profile_id, "profile_id")
        _require_optional_identifier(self.register_id, "register_id")
        _require_optional_identifier(self.sensor_id, "sensor_id")


@dataclass(frozen=True, slots=True)
class AcquisitionSuccess:
    """Successful acquisition result with a normalized measurement."""

    context: AcquisitionContext
    measurement: Measurement
    acquired_at: datetime

    def __post_init__(self) -> None:
        _require_aware_datetime(self.acquired_at, "acquired_at")


@dataclass(frozen=True, slots=True)
class AcquisitionFailure:
    """Failed acquisition result with a structured code and readable message."""

    context: AcquisitionContext
    code: AcquisitionErrorCode
    message: str
    acquired_at: datetime

    def __post_init__(self) -> None:
        _require_text(self.message, "message")
        _require_aware_datetime(self.acquired_at, "acquired_at")


AcquisitionResult = AcquisitionSuccess | AcquisitionFailure


class AcquisitionPipeline:
    """Convert raw measurements into structured acquisition results."""

    def __init__(
        self,
        ingestion: IngestionService,
        *,
        clock: AcquisitionClock = utc_now,
    ) -> None:
        self._ingestion = ingestion
        self._clock = clock

    def ingest_raw_measurements(
        self,
        raw_measurements: Iterable[RawMeasurement],
        *,
        profile_id: str | None = None,
    ) -> tuple[AcquisitionResult, ...]:
        """Ingest raw measurements and return success or failure per item."""

        results: list[AcquisitionResult] = []
        for raw in raw_measurements:
            context = context_from_raw(raw, profile_id=profile_id)
            try:
                measurement = self._ingestion.ingest(raw)
            except (
                AssetNotFoundError,
                IncompatibleMeasurementUnitError,
                IngestionError,
            ) as exc:
                results.append(
                    acquisition_failure(
                        context,
                        code=_code_from_exception(exc),
                        message=str(exc),
                        acquired_at=self._clock(),
                    )
                )
                continue

            results.append(
                AcquisitionSuccess(
                    context=context,
                    measurement=measurement,
                    acquired_at=self._clock(),
                )
            )

        return tuple(results)

    def failure(
        self,
        context: AcquisitionContext,
        *,
        code: AcquisitionErrorCode,
        message: str,
    ) -> AcquisitionFailure:
        """Return a timestamped structured failure."""

        return acquisition_failure(
            context,
            code=code,
            message=message,
            acquired_at=self._clock(),
        )


def context_from_raw(
    raw: RawMeasurement,
    *,
    profile_id: str | None = None,
) -> AcquisitionContext:
    """Build acquisition context from a raw measurement."""

    register_id_value = raw.metadata.get("register_id")
    register_id = register_id_value if isinstance(register_id_value, str) else None
    return AcquisitionContext(
        source_id=raw.source_id,
        profile_id=profile_id,
        register_id=register_id,
        sensor_id=raw.sensor_id,
    )


def context_from_definition(
    *,
    source_id: str,
    profile_id: str | None,
    register_id: str | None,
    sensor_id: str | None,
) -> AcquisitionContext:
    """Build acquisition context before a raw measurement exists."""

    return AcquisitionContext(
        source_id=source_id,
        profile_id=profile_id,
        register_id=register_id,
        sensor_id=sensor_id,
    )


def acquisition_failure(
    context: AcquisitionContext,
    *,
    code: AcquisitionErrorCode,
    message: str,
    acquired_at: datetime,
) -> AcquisitionFailure:
    """Create a validated acquisition failure."""

    return AcquisitionFailure(
        context=context,
        code=code,
        message=message,
        acquired_at=acquired_at,
    )


def successful_measurements(
    results: Iterable[AcquisitionResult],
) -> tuple[Measurement, ...]:
    """Return normalized measurements from successful acquisition results."""

    return tuple(
        result.measurement
        for result in results
        if isinstance(result, AcquisitionSuccess)
    )


def failures(results: Iterable[AcquisitionResult]) -> tuple[AcquisitionFailure, ...]:
    """Return failures from acquisition results."""

    return tuple(
        result
        for result in results
        if isinstance(result, AcquisitionFailure)
    )


def _code_from_exception(exc: Exception) -> AcquisitionErrorCode:
    if isinstance(exc, AssetNotFoundError):
        return AcquisitionErrorCode.SENSOR_NOT_FOUND
    if isinstance(exc, IngestionError | IncompatibleMeasurementUnitError):
        return AcquisitionErrorCode.NORMALIZATION_FAILED
    return AcquisitionErrorCode.UNKNOWN


def _require_identifier(value: str, field_name: str) -> None:
    if not value.strip():
        raise AcquisitionResultError(f"{field_name} must be a non-empty identifier")


def _require_optional_identifier(value: str | None, field_name: str) -> None:
    if value is not None:
        _require_identifier(value, field_name)


def _require_text(value: str, field_name: str) -> None:
    if not value.strip():
        raise AcquisitionResultError(f"{field_name} must be non-empty")


def _require_aware_datetime(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise AcquisitionResultError(f"{field_name} must be timezone-aware")
