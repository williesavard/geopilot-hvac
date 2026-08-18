#!/usr/bin/env python3
"""Measure what to put in `offset_celsius`.

Put every DS18B20 in the same bath, wait for them to settle, then:

    python3 tools/geopilot_calibrate.py --config installation.toml --minutes 10

It prints the offsets to paste into the configuration. Nothing is recorded and
nothing is written back — the file stays yours to edit.

**Why bother.** A DS18B20 is specified to ±0.5 °C, so two of them can sit a full
degree apart in the same water and both be in specification. A loop delta of 2 °C
read by two probes that disagree by 1 °C is half noise, and no amount of careful
analysis afterwards recovers it.

**Two kinds of bath.** With no reference, the probes are calibrated to their own
mean: they end up agreeing with each other, which is what a delta needs. With
`--reference 0.0` in an ice bath — crushed ice, a little water, stirred — they
are calibrated to truth. Do the ice bath if you can; it costs a bowl of ice.

**Stirring matters more than waiting.** Still water stratifies, and probes at
different depths then measure a real difference that is not an offset. Stir it,
or accept that you calibrated the temperature gradient of a glass of water.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

from geopilot.calibration import (
    SETTLED_SPREAD_CELSIUS,
    CalibrationError,
    CalibrationRun,
    ProbeSamples,
    calibrate,
)
from geopilot.configuration import ConfigurationError, load_configuration
from geopilot.onewire import OneWireError, SysfsOneWireBus

EXIT_OK = 0
EXIT_USAGE = 1
EXIT_UNSETTLED = 2


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""

    parser = argparse.ArgumentParser(
        prog="geopilot_calibrate.py",
        description="Measure DS18B20 offsets from a same-bath run.",
    )
    parser.add_argument("--config", required=True, help="path to the installation TOML")
    parser.add_argument(
        "--minutes", type=float, default=10.0, help="how long to sample, default 10"
    )
    parser.add_argument(
        "--interval", type=float, default=10.0, help="seconds between rounds, default 10"
    )
    reference = parser.add_mutually_exclusive_group()
    reference.add_argument(
        "--reference",
        type=float,
        metavar="CELSIUS",
        help="a known bath temperature, for example 0.0 for an ice bath",
    )
    reference.add_argument(
        "--reference-device",
        metavar="DEVICE_ID",
        help="calibrate the others to agree with this probe",
    )
    parser.add_argument(
        "--include-unconfigured",
        action="store_true",
        help="also sample probes on the bus that the configuration does not mention",
    )
    return parser


def sample(
    buses: Sequence[tuple[SysfsOneWireBus, dict[str, str]]],
    *,
    minutes: float,
    interval: float,
    announce: bool = True,
) -> tuple[ProbeSamples, ...]:
    """Read every probe repeatedly for the requested time.

    A probe that fails one round is not dropped: its other readings still stand,
    and a probe that fails *every* round simply produces no samples and is
    refused later by name.
    """

    readings: dict[str, list[float]] = {}
    sensors: dict[str, str] = {}
    deadline = time.monotonic() + minutes * 60
    rounds = 0

    while True:
        rounds += 1
        for bus, devices in buses:
            for device_id, sensor_id in devices.items():
                sensors[device_id] = sensor_id
                try:
                    reading = bus.read_temperature(device_id)
                except OneWireError:
                    continue
                readings.setdefault(device_id, []).append(reading.celsius)

        if announce:
            spread = _live_spread(readings)
            remaining = max(0.0, deadline - time.monotonic())
            print(
                f"round {rounds:3d} · {len(readings)} probe(s) · "
                f"spread {spread:.3f} degC · {remaining / 60:.1f} min left",
                flush=True,
            )

        if time.monotonic() >= deadline:
            break
        time.sleep(interval)

    return tuple(
        ProbeSamples(
            device_id=device_id,
            sensor_id=sensors.get(device_id, ""),
            celsius=tuple(values),
        )
        for device_id, values in sorted(readings.items())
    )


def _live_spread(readings: dict[str, list[float]]) -> float:
    latest = [values[-1] for values in readings.values() if values]
    return max(latest) - min(latest) if len(latest) > 1 else 0.0


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point. Returns a process exit code rather than raising."""

    arguments = build_parser().parse_args(argv)

    try:
        config = load_configuration(Path(arguments.config))
    except ConfigurationError as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_USAGE

    if not config.onewire_sources:
        print("error: the configuration declares no 1-Wire source", file=sys.stderr)
        return EXIT_USAGE

    buses = []
    for source in config.onewire_sources:
        bus = SysfsOneWireBus(source.root)
        devices = {
            read.device_id: read.sensor_id
            for read in config.onewire_reads
            if read.source_id == source.source_id
        }
        if arguments.include_unconfigured:
            for device_id in bus.available_devices():
                devices.setdefault(device_id, "")
        buses.append((bus, devices))

    if not any(devices for _, devices in buses):
        print("error: no probes to sample", file=sys.stderr)
        return EXIT_USAGE

    print(
        f"sampling for {arguments.minutes:g} min every {arguments.interval:g}s. "
        "Keep every probe in the same stirred bath."
    )
    started_at = datetime.now(UTC).astimezone()
    samples = sample(buses, minutes=arguments.minutes, interval=arguments.interval)

    try:
        run = calibrate(
            samples,
            started_at=started_at,
            duration=timedelta(minutes=arguments.minutes),
            reference=arguments.reference,
            reference_device=arguments.reference_device,
        )
    except CalibrationError as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_USAGE

    _report(run)
    return EXIT_OK if run.usable else EXIT_UNSETTLED


def _report(run: CalibrationRun) -> None:
    print(f"\nreference : {run.reference:.4f} degC, from {run.reference_kind}")
    print(f"started   : {run.started_at.isoformat(timespec='seconds')}")
    print(f"disagreement before correction: {run.disagreement:.3f} degC\n")

    print(f"{'probe':22s} {'sensor':22s} {'mean':>9s} {'spread':>8s} {'noise':>8s} {'offset':>9s}")
    for probe in run.probes:
        mark = " " if probe.settled else "!"
        print(
            f"{mark}{probe.device_id:21s} {probe.sensor_id or '—':22s} "
            f"{probe.mean:>9.3f} {probe.spread:>8.3f} {probe.noise:>8.3f} {probe.offset:>+9.4f}"
        )

    if not run.usable:
        print(
            f"\nNOT USABLE: a probe moved more than {SETTLED_SPREAD_CELSIUS} degC during the "
            "run (marked !), so what was measured is it still settling, not its offset. "
            "Stir the bath, wait longer, and run it again."
        )
        return

    print("\nPaste each line into that probe's [[onewire_read]] entry:\n")
    for probe in run.probes:
        print(f"  {probe.toml()}")
    print(
        f"\nRecord the bath and the date in docs/hardware/BENCH_NOTES.md. An offset "
        f"measured against {run.reference_kind} is only meaningful if the next person "
        "knows which it was."
    )


if __name__ == "__main__":
    sys.exit(main())
