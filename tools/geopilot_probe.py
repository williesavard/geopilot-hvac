#!/usr/bin/env python3
"""Ask the hardware what it says right now.

    python3 tools/geopilot_probe.py --config /etc/geopilot/installation.toml

Nothing is recorded. This reads and prints, so the loop while wiring is seconds
instead of a poll interval.

**1-Wire is a discovery.** Every DS18B20 the kernel can see is listed, whether
the configuration mentions it or not, with its current reading. Three identical
probes on one cable and no idea which id is which: warm one in your hand, probe
again, and the one that moved is the one you are holding.

**Modbus is a verification.** It reads what the configuration claims is there.
Nothing sweeps the bus looking for devices.

The acquisition timer opens the same serial port every minute. This opens it
briefly and does not retry: a probe that reports a busy bus is a probe you press
again, which is more honest than a loop that hides how often the port was taken.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from geopilot.configuration import (
    ConfigurationError,
    InstallationConfig,
    load_configuration,
)
from geopilot.modbus_pyserial_transport import (
    PySerialModbusBitTransport,
    PySerialModbusConfig,
    PySerialModbusTransport,
)
from geopilot.onewire import SysfsOneWireBus
from geopilot.probe import (
    ProbeResult,
    probe_bits,
    probe_onewire,
    probe_registers,
)

EXIT_OK = 0
EXIT_USAGE = 1
EXIT_TROUBLE = 2


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""

    parser = argparse.ArgumentParser(
        prog="geopilot_probe.py",
        description="Read every configured sensor right now, without recording anything.",
    )
    parser.add_argument("--config", required=True, help="path to the installation TOML")
    parser.add_argument(
        "--only",
        choices=("onewire", "modbus"),
        help="probe one bus family instead of all of them",
    )
    parser.add_argument(
        "--family",
        default="28",
        help="1-Wire family code to enumerate, default 28 for DS18B20",
    )
    return parser


def settings_for(config: InstallationConfig, source_id: str) -> PySerialModbusConfig:
    """Serial settings for one configured source."""

    source = config.source(source_id)
    return PySerialModbusConfig(
        port=source.port,
        baudrate=source.baudrate,
        parity=source.parity,
        stopbits=source.stopbits,
        bytesize=source.bytesize,
        timeout=source.timeout,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point. Returns a process exit code rather than raising."""

    arguments = build_parser().parse_args(argv)

    try:
        config = load_configuration(Path(arguments.config))
    except ConfigurationError as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_USAGE

    results: list[ProbeResult] = []

    if arguments.only != "modbus" and (config.onewire_sources or config.onewire_reads):
        for source in config.onewire_sources or ():
            results.extend(
                probe_onewire(
                    SysfsOneWireBus(source.root),
                    tuple(
                        read
                        for read in config.onewire_reads
                        if read.source_id == source.source_id
                    ),
                    family=arguments.family,
                )
            )

    if arguments.only != "onewire":
        results.extend(
            probe_registers(
                lambda source_id: PySerialModbusTransport(settings_for(config, source_id)),
                config.reads,
            )
        )
        results.extend(
            probe_bits(
                lambda source_id: PySerialModbusBitTransport(settings_for(config, source_id)),
                config.bit_reads,
            )
        )

    if not results:
        print("nothing to probe: the configuration declares no reads")
        return EXIT_USAGE

    _report(tuple(results))
    return EXIT_OK if all(item.ok and not item.suspect for item in results) else EXIT_TROUBLE


def _report(results: tuple[ProbeResult, ...]) -> None:
    print(f"{'what':30s} {'kind':9s} {'reading':>12s}  {'reference / note'}")

    for item in results:
        reading = "—" if item.value is None else f"{item.value:g} {item.unit}"
        mark = " " if item.ok and not item.suspect else "!"
        note = item.reference if item.sensor_id else ""
        if item.detail:
            note = f"{note} · {item.detail}" if note else item.detail
        print(f"{mark}{item.label:29s} {item.kind:9s} {reading:>12s}  {note}")

    unconfigured = [item for item in results if item.ok and not item.configured]
    if unconfigured:
        print(f"\n{len(unconfigured)} device(s) are on the bus but not in the configuration:")
        for item in unconfigured:
            print(f"  {item.reference}")
        print("copy the ids into [[onewire_read]] entries to start recording them")

    troubled = [item for item in results if not item.ok or item.suspect]
    if troubled:
        print(f"\n{len(troubled)} of {len(results)} did not answer cleanly (marked !)")


if __name__ == "__main__":
    sys.exit(main())
