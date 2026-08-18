"""Calibration tests.

The number that matters is the offset, and the rule that matters is refusing to
emit one from a run where a probe was still settling.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from geopilot.calibration import (
    MINIMUM_SAMPLES,
    CalibrationError,
    ProbeSamples,
    calibrate,
)

STARTED = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)
RAN_FOR = timedelta(minutes=10)


def samples(device_id: str, *values: float, sensor_id: str = "") -> ProbeSamples:
    return ProbeSamples(
        device_id=device_id,
        sensor_id=sensor_id or f"sensor_{device_id[-1]}",
        celsius=values,
    )


def steady(device_id: str, around: float, count: int = 10) -> ProbeSamples:
    """A settled probe: tiny dither around one value, no drift."""

    values = tuple(around + (0.0625 if index % 2 else -0.0625) for index in range(count))
    return samples(device_id, *values)


def test_probes_are_calibrated_to_agree_with_each_other_by_default() -> None:
    """For a delta, agreement is the target. Absolute truth is a different bath."""

    result = calibrate(
        (steady("28-a", 20.0), steady("28-b", 21.0)),
        started_at=STARTED,
        duration=RAN_FOR,
    )

    assert result.reference == pytest.approx(20.5)
    offsets = {probe.device_id: probe.offset for probe in result.probes}
    assert offsets["28-a"] == pytest.approx(0.5)
    assert offsets["28-b"] == pytest.approx(-0.5)


def test_an_offset_is_what_must_be_added_to_reach_the_reference() -> None:
    """The direction `offset_celsius` is applied in, so it cannot be backwards."""

    result = calibrate(
        (steady("28-a", 19.6),), started_at=STARTED, duration=RAN_FOR, reference=20.0
    )

    probe = result.probes[0]
    assert probe.offset == pytest.approx(0.4)
    assert probe.mean + probe.offset == pytest.approx(20.0)


def test_a_known_bath_calibrates_to_truth() -> None:
    result = calibrate(
        (steady("28-a", 0.3), steady("28-b", -0.2)),
        started_at=STARTED,
        duration=RAN_FOR,
        reference=0.0,
    )

    assert result.reference == 0.0
    assert "known 0 degC" in result.reference_kind
    offsets = {probe.device_id: probe.offset for probe in result.probes}
    assert offsets["28-a"] == pytest.approx(-0.3)
    assert offsets["28-b"] == pytest.approx(0.2)


def test_one_probe_can_be_the_reference() -> None:
    """For when one of them is the trusted instrument."""

    result = calibrate(
        (steady("28-a", 20.0), steady("28-b", 21.0)),
        started_at=STARTED,
        duration=RAN_FOR,
        reference_device="28-a",
    )

    offsets = {probe.device_id: probe.offset for probe in result.probes}
    assert offsets["28-a"] == pytest.approx(0.0)
    assert offsets["28-b"] == pytest.approx(-1.0)


def test_an_unknown_reference_probe_is_refused() -> None:
    with pytest.raises(CalibrationError, match="not among the probes"):
        calibrate(
            (steady("28-a", 20.0),),
            started_at=STARTED,
            duration=RAN_FOR,
            reference_device="28-zzz",
        )


def test_two_kinds_of_reference_at_once_are_refused() -> None:
    with pytest.raises(CalibrationError, match="not both"):
        calibrate(
            (steady("28-a", 20.0),),
            started_at=STARTED,
            duration=RAN_FOR,
            reference=0.0,
            reference_device="28-a",
        )


def test_a_run_with_no_probes_is_refused() -> None:
    with pytest.raises(CalibrationError, match="nothing to calibrate"):
        calibrate((), started_at=STARTED, duration=RAN_FOR)


def test_too_few_samples_to_judge_a_spread_is_refused() -> None:
    """Below a handful of readings there is no spread worth speaking of."""

    with pytest.raises(CalibrationError, match=f"at least {MINIMUM_SAMPLES}"):
        calibrate((samples("28-a", 20.0, 20.1),), started_at=STARTED, duration=RAN_FOR)


def test_a_probe_still_settling_makes_the_run_unusable() -> None:
    """Sampling during the transient measures the transient, not the offset."""

    drifting = samples("28-b", 25.0, 23.5, 22.0, 21.0, 20.6, 20.4, 20.3)
    result = calibrate(
        (steady("28-a", 20.0), drifting), started_at=STARTED, duration=RAN_FOR
    )

    assert not result.usable
    assert not next(p for p in result.probes if p.device_id == "28-b").settled
    assert next(p for p in result.probes if p.device_id == "28-a").settled


def test_a_settled_run_is_usable() -> None:
    result = calibrate(
        (steady("28-a", 20.0), steady("28-b", 20.4)),
        started_at=STARTED,
        duration=RAN_FOR,
    )

    assert result.usable


def test_spread_is_peak_to_peak_not_a_standard_deviation() -> None:
    """A probe drifting steadily has a small deviation and is not settled."""

    drifting = samples("28-a", 20.0, 20.1, 20.2, 20.3, 20.4, 20.5, 20.6)

    assert drifting.spread == pytest.approx(0.6)
    assert drifting.noise < 0.25
    assert not drifting.settled


def test_the_disagreement_is_reported_because_it_is_the_point() -> None:
    """The error you would have carried into every delta had you not measured."""

    result = calibrate(
        (steady("28-a", 20.0), steady("28-b", 21.0), steady("28-c", 20.4)),
        started_at=STARTED,
        duration=RAN_FOR,
    )

    assert result.disagreement == pytest.approx(1.0)


def test_the_pasteable_line_carries_the_device_it_belongs_to() -> None:
    """Three offsets and three identical entries is how they get swapped."""

    result = calibrate(
        (steady("28-abcdef", 20.4),), started_at=STARTED, duration=RAN_FOR, reference=20.0
    )

    line = result.probes[0].toml()
    assert line.startswith("offset_celsius = -0.4")
    assert "28-abcdef" in line


def test_a_single_probe_calibrates_to_itself_with_no_reference() -> None:
    """Honest, and useless — which the zero offset makes obvious."""

    result = calibrate((steady("28-a", 20.0),), started_at=STARTED, duration=RAN_FOR)

    assert result.probes[0].offset == pytest.approx(0.0)
    assert result.disagreement == pytest.approx(0.0)
