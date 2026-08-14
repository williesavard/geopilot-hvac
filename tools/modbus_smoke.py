#!/usr/bin/env python3
"""Manual Modbus RTU read-only smoke check for bench work.

This tool exists to make `docs/HARDWARE_BENCH_RUNBOOK.md` steps 4 and 6 a single
command instead of a pasted snippet. It is operator-driven and hardware-only.

It never runs from `pytest`: `pyproject.toml` restricts test collection to
`tests/`, and this file is not a test module. Its testable core accepts an
injected serial factory, so the automated tests exercise every path except the
one that opens a real port.

It performs read-only register reads. It does not write registers, decode
values, apply scale factors, name measurements, consult device profiles, touch
the historian, or control HVAC equipment. Raw register words are printed exactly
as the device returned them.

Requires the optional `modbus` extra:

    pip install --editable ".[modbus]"

Example:

    python3 tools/modbus_smoke.py \
        --port /dev/cu.usbserial-XXXX \
        --unit-id 1 \
        --register input \
        --address 1 \
        --quantity 2
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass

from geopilot.modbus_pyserial_transport import (
    PySerialModbusConfig,
    PySerialModbusTransport,
    SerialFactory,
    build_read_request_frame,
)
from geopilot.modbus_transport import (
    ModbusReadRequest,
    ModbusRegisterKind,
    ModbusTransportBoundaryError,
    ModbusTransportError,
)

EXIT_OK = 0
EXIT_USAGE = 1
EXIT_TRANSPORT_ERROR = 2

SAFETY_BANNER = """\
GeoPilot Modbus smoke check - read-only, real hardware
  * This talks to a physical RS485 bus. Read `docs/HARDWARE_BENCH_RUNBOOK.md`
    before using it.
  * Any mains-voltage wiring or live electrical measurement must be performed
    by a qualified electrician.
  * Register words are printed raw. Interpreting them requires a
    source-reviewed register map, which GeoPilot does not have yet.
  * Stop the session and record the observation if anything is unexpected.
"""


@dataclass(frozen=True, slots=True)
class SmokeAttempt:
    """Outcome of one read attempt."""

    index: int
    words: tuple[int, ...] | None
    error_code: str | None
    error_message: str | None
    elapsed_ms: float

    @property
    def succeeded(self) -> bool:
        return self.words is not None


@dataclass(frozen=True, slots=True)
class SmokeReport:
    """Outcome of a whole smoke run."""

    request_frame: bytes
    attempts: tuple[SmokeAttempt, ...]

    @property
    def successes(self) -> int:
        return sum(1 for attempt in self.attempts if attempt.succeeded)

    @property
    def failures(self) -> int:
        return len(self.attempts) - self.successes


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser.

    Every bus coordinate is required. The runbook forbids guessing a port, a
    slave id, a register family or an address, so none of them has a default.
    """

    parser = argparse.ArgumentParser(
        prog="modbus_smoke.py",
        description="Read-only Modbus RTU smoke check for manual bench work.",
    )
    parser.add_argument(
        "--port",
        required=True,
        help="serial device, for example /dev/cu.usbserial-XXXX",
    )
    parser.add_argument(
        "--unit-id",
        required=True,
        type=int,
        help="Modbus slave id from the device manual",
    )
    parser.add_argument(
        "--register",
        required=True,
        choices=[kind.value for kind in ModbusRegisterKind],
        help="register family from the device manual",
    )
    parser.add_argument(
        "--address",
        required=True,
        type=int,
        help="register address from the device manual",
    )
    parser.add_argument(
        "--quantity",
        type=int,
        default=1,
        help="number of registers to read (default 1)",
    )
    parser.add_argument("--baudrate", type=int, default=9600)
    parser.add_argument("--parity", default="N", choices=["N", "E", "O", "M", "S"])
    parser.add_argument("--stopbits", type=float, default=1)
    parser.add_argument("--bytesize", type=int, default=8)
    parser.add_argument("--timeout", type=float, default=1.0, help="read timeout in seconds")
    parser.add_argument("--repeat", type=int, default=1, help="number of read attempts (default 1)")
    parser.add_argument(
        "--source-id",
        default="bench",
        help="label recorded in the request, not a GeoPilot source",
    )
    return parser


def run_smoke(
    config: PySerialModbusConfig,
    request_template: ModbusReadRequest,
    *,
    repeat: int,
    serial_factory: SerialFactory | None = None,
) -> SmokeReport:
    """Perform `repeat` read attempts and report each outcome.

    A transport error fails one attempt without aborting the run, so an
    intermittent bus shows up as a ratio rather than as a single stack trace.
    """

    transport = PySerialModbusTransport(config, serial_factory=serial_factory)
    attempts: list[SmokeAttempt] = []
    for index in range(1, repeat + 1):
        request = ModbusReadRequest(
            request_id=f"{request_template.request_id}-{index}",
            source_id=request_template.source_id,
            unit_id=request_template.unit_id,
            register_kind=request_template.register_kind,
            address=request_template.address,
            quantity=request_template.quantity,
        )
        started = time.perf_counter()
        try:
            response = transport.read_registers(request)
        except ModbusTransportError as error:
            attempts.append(
                SmokeAttempt(
                    index=index,
                    words=None,
                    error_code=str(error.code),
                    error_message=error.message,
                    elapsed_ms=(time.perf_counter() - started) * 1000,
                )
            )
            continue
        attempts.append(
            SmokeAttempt(
                index=index,
                words=response.words,
                error_code=None,
                error_message=None,
                elapsed_ms=(time.perf_counter() - started) * 1000,
            )
        )

    return SmokeReport(
        request_frame=build_read_request_frame(request_template),
        attempts=tuple(attempts),
    )


def format_report(report: SmokeReport) -> str:
    """Render a report in the shape the runbook asks operators to record."""

    lines = [f"request frame : {report.request_frame.hex(' ')}"]
    for attempt in report.attempts:
        prefix = f"attempt {attempt.index:>3}"
        if attempt.words is None:
            lines.append(
                f"{prefix} : FAILED {attempt.error_code} - {attempt.error_message} "
                f"({attempt.elapsed_ms:.1f} ms)"
            )
            continue
        hex_words = " ".join(f"0x{word:04x}" for word in attempt.words)
        decimal_words = " ".join(str(word) for word in attempt.words)
        lines.append(
            f"{prefix} : OK   raw hex [{hex_words}] raw decimal [{decimal_words}] "
            f"({attempt.elapsed_ms:.1f} ms)"
        )
    lines.append(
        f"summary       : {report.successes} succeeded, {report.failures} failed, "
        f"{len(report.attempts)} attempted"
    )
    lines.append("raw words only. Do not interpret them without a source-reviewed register map.")
    return "\n".join(lines)


def main(
    argv: Sequence[str] | None = None,
    *,
    serial_factory: SerialFactory | None = None,
) -> int:
    """Entry point. Returns a process exit code rather than raising."""

    arguments = build_parser().parse_args(argv)
    print(SAFETY_BANNER, file=sys.stderr)

    if arguments.repeat < 1:
        print("error: --repeat must be at least 1", file=sys.stderr)
        return EXIT_USAGE

    try:
        config = PySerialModbusConfig(
            port=arguments.port,
            baudrate=arguments.baudrate,
            parity=arguments.parity,
            stopbits=arguments.stopbits,
            bytesize=arguments.bytesize,
            timeout=arguments.timeout,
        )
        request = ModbusReadRequest(
            request_id="bench-smoke",
            source_id=arguments.source_id,
            unit_id=arguments.unit_id,
            register_kind=ModbusRegisterKind(arguments.register),
            address=arguments.address,
            quantity=arguments.quantity,
        )
    except ModbusTransportBoundaryError as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_USAGE

    try:
        report = run_smoke(
            config,
            request,
            repeat=arguments.repeat,
            serial_factory=serial_factory,
        )
    except ModbusTransportError as error:
        # Raised while opening the port, before any attempt could run.
        print(f"error: {error.code} - {error.message}", file=sys.stderr)
        return EXIT_TRANSPORT_ERROR

    print(format_report(report))
    return EXIT_OK if report.failures == 0 else EXIT_TRANSPORT_ERROR


if __name__ == "__main__":
    sys.exit(main())
