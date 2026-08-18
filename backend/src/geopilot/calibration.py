"""Measure the offsets that make probes agree.

`offset_celsius` has always existed in the configuration. What has not existed
is any way to find out what to put in it, which left it a field people either
guess at or leave at zero.

Two probes in the same bath will not read the same number. A DS18B20 is
specified to ±0.5 °C, so two of them can sit 1 °C apart and both be within
specification. That is fine for "is the basement cold" and fatal for the
measurement this installation exists to make: **a loop delta of 2 °C, read by
two probes that disagree by 1 °C, is half noise.**

## Agreement, not truth

The default reference is the group's own mean, which calibrates the probes to
agree with each other rather than with a standard. For a delta that is the right
target: what matters is that loop-in and loop-out are measured on the same scale,
not that either is absolutely right.

Pass a known temperature — an ice bath is 0.0 °C and costs nothing — and it
calibrates to truth instead. Say which one you did, because they answer different
questions.

## Settling is not optional

A probe moved from a pocket into a bath takes minutes to arrive. Sampling during
that time measures the transient, not the offset, so every probe's spread across
the run is reported and a run where anything is still moving is marked unusable.
Refusing beats emitting a confident wrong number into a configuration file.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import fmean, pstdev

SETTLED_SPREAD_CELSIUS = 0.25
"""How far a probe may wander across a run and still count as settled.

A DS18B20 in twelve-bit mode resolves 0.0625 °C, so a quarter of a degree is
several counts of genuine movement — well past dithering on the least
significant bit and well short of anything a settled probe in a stirred bath
does.
"""

MINIMUM_SAMPLES = 5
"""Below this there is no spread worth speaking of, so nothing can be judged."""


@dataclass(frozen=True, slots=True)
class ProbeSamples:
    """Every reading taken from one probe during a calibration run."""

    device_id: str
    sensor_id: str
    celsius: tuple[float, ...]

    @property
    def mean(self) -> float:
        return fmean(self.celsius)

    @property
    def spread(self) -> float:
        """Peak-to-peak movement, not a standard deviation.

        A probe that drifted steadily by a third of a degree has a small standard
        deviation and is not settled. The range catches it.
        """

        return max(self.celsius) - min(self.celsius)

    @property
    def noise(self) -> float:
        return pstdev(self.celsius) if len(self.celsius) > 1 else 0.0

    @property
    def settled(self) -> bool:
        return len(self.celsius) >= MINIMUM_SAMPLES and self.spread <= SETTLED_SPREAD_CELSIUS


@dataclass(frozen=True, slots=True)
class ProbeCalibration:
    """One probe's measured offset."""

    device_id: str
    sensor_id: str
    mean: float
    spread: float
    noise: float
    samples: int
    offset: float
    settled: bool

    def toml(self) -> str:
        """The line to paste into this probe's `[[onewire_read]]` entry."""

        return f"offset_celsius = {self.offset:+.4f}  # {self.device_id}"


@dataclass(frozen=True, slots=True)
class CalibrationRun:
    """The result of one bath, and whether it can be trusted."""

    reference: float
    reference_kind: str
    started_at: datetime
    duration: timedelta
    probes: tuple[ProbeCalibration, ...]

    @property
    def usable(self) -> bool:
        """Whether every probe settled. A run with one wanderer is not usable."""

        return bool(self.probes) and all(probe.settled for probe in self.probes)

    @property
    def disagreement(self) -> float:
        """How far apart the probes were before correction.

        This is the number the calibration is worth: the error you would have
        carried into every delta had you not measured it.
        """

        if not self.probes:
            return 0.0
        means = [probe.mean for probe in self.probes]
        return max(means) - min(means)


class CalibrationError(ValueError):
    """Raised when a run cannot be turned into offsets at all."""


def calibrate(
    samples: Sequence[ProbeSamples],
    *,
    started_at: datetime,
    duration: timedelta,
    reference: float | None = None,
    reference_device: str | None = None,
) -> CalibrationRun:
    """Turn a bath of samples into per-probe offsets.

    With no reference the probes are calibrated to their own mean, which makes
    them agree with each other. With `reference` they are calibrated to a known
    temperature. With `reference_device` they are calibrated to one probe, which
    is what you want when one of them is the trusted instrument.

    An offset is what must be **added** to a raw reading to reach the reference,
    which is the direction `offset_celsius` is applied in.
    """

    if not samples:
        raise CalibrationError("no probes were sampled; nothing to calibrate")
    if reference is not None and reference_device is not None:
        raise CalibrationError("calibrate against a known temperature or a probe, not both")

    thin = [item for item in samples if len(item.celsius) < MINIMUM_SAMPLES]
    if thin:
        raise CalibrationError(
            f"{thin[0].device_id} produced {len(thin[0].celsius)} sample(s); "
            f"at least {MINIMUM_SAMPLES} are needed before a spread means anything"
        )

    if reference_device is not None:
        chosen = next((item for item in samples if item.device_id == reference_device), None)
        if chosen is None:
            raise CalibrationError(f"{reference_device} was not among the probes sampled")
        target, kind = chosen.mean, f"probe {reference_device}"
    elif reference is not None:
        target, kind = reference, f"known {reference:g} degC"
    else:
        target, kind = fmean([item.mean for item in samples]), "the group mean"

    return CalibrationRun(
        reference=target,
        reference_kind=kind,
        started_at=started_at,
        duration=duration,
        probes=tuple(
            ProbeCalibration(
                device_id=item.device_id,
                sensor_id=item.sensor_id,
                mean=item.mean,
                spread=item.spread,
                noise=item.noise,
                samples=len(item.celsius),
                offset=target - item.mean,
                settled=item.settled,
            )
            for item in samples
        ),
    )
