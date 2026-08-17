#!/usr/bin/env python3
"""Serve the dashboard as a control surface on this machine.

    python3 tools/geopilot_control.py --config /etc/geopilot/installation.toml

Then open http://127.0.0.1:8322/.

Unlike `geopilot_dashboard.py`, which writes a file, this listens. It is the
only part of GeoPilot that does, and it binds to the loopback interface: nothing
off this machine can reach it unless you pass `--bind`, which prints a warning
you are meant to read.

**Control is off unless the configuration turns it on.** With `[control]
enabled = false`, or with no `[control]` table at all, the page still shows every
whitelisted relay and reads its real state back from the bus — and every command
is refused and recorded as refused. That is the intended way to run it first.

The serial port is opened for the duration of one command and closed again,
because the acquisition timer opens the same port every minute and two processes
cannot hold an RS485 segment at once. A command that collides fails, says so,
and is journalled — it is never retried silently.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from geopilot.configuration import ConfigurationError, InstallationConfig, load_configuration
from geopilot.connectivity import roster_from
from geopilot.control import ControlPolicy
from geopilot.control_server import ControlSurface, build_service, serve
from geopilot.dashboard import DeltaPair, render
from geopilot.modbus_pyserial_transport import (
    PySerialModbusBitTransport,
    PySerialModbusConfig,
    PySerialModbusTransport,
    open_serial_port,
)
from geopilot.modbus_pyserial_write import PySerialModbusWriteTransport
from geopilot.modbus_transport import (
    ModbusBitKind,
    ModbusBitReadRequest,
    ModbusTransportError,
)
from geopilot.modbus_write import ModbusCoilWriteRequest, ModbusWriteError
from geopilot.onewire import SysfsOneWireBus
from geopilot.probe import ProbeResult, probe_bits, probe_onewire, probe_registers
from geopilot.reporting import ReportingError, open_readonly

EXIT_OK = 0
EXIT_USAGE = 1

LOOPBACK = "127.0.0.1"


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""

    parser = argparse.ArgumentParser(
        prog="geopilot_control.py",
        description="Serve the GeoPilot dashboard as a local control surface.",
    )
    parser.add_argument("--config", required=True, help="path to the installation TOML")
    parser.add_argument("--port", type=int, default=8322, help="TCP port, default 8322")
    parser.add_argument(
        "--bind",
        default=LOOPBACK,
        help="interface to listen on; anything but 127.0.0.1 exposes control to the network",
    )
    parser.add_argument(
        "--delta",
        action="append",
        default=[],
        metavar="SENSOR:MINUS",
        help="chart the difference between two sensors; repeatable",
    )
    parser.add_argument("--title", default="GeoPilot", help="heading for the page")
    return parser


def parse_delta(value: str) -> DeltaPair:
    """Parse `sensor:minus`; both ends are required and neither is guessed."""

    sensor_id, separator, minus = value.partition(":")
    if not separator or not sensor_id or not minus:
        raise ValueError(f"--delta needs SENSOR:MINUS, received {value!r}")
    return DeltaPair(sensor_id=sensor_id, minus=minus)


class SerialBus:
    """Opens the bus for one operation and closes it again.

    The acquisition timer holds the same port for a moment every minute. Holding
    it open here would collide with that; opening it per command keeps the window
    to milliseconds and leaves the timer's topology alone.

    A collision is not hidden. `write_coil` lets the transport's error out, and
    the guard turns it into a FAILED record with the reason attached.
    """

    def __init__(self, config: InstallationConfig) -> None:
        self._config = config

    def _settings(self, target_id: str) -> PySerialModbusConfig:
        return _settings(self._config, self._config.control_source(target_id))

    def write_coil(self, request: ModbusCoilWriteRequest) -> None:
        """Satisfy `ModbusWriteTransport` by opening, writing and closing."""

        settings = self._settings(request.target_id)
        port = open_serial_port(settings)
        try:
            PySerialModbusWriteTransport(settings, serial_port=port).write_coil(request)
        finally:
            _close(port)

    def read_state(self, target_id: str) -> bool | None:
        """Ask the device what the coil is actually doing.

        Returns None when the bus does not answer. A silent bus is not an open
        contact, and reporting it as one would be a lie the page then shows.
        """

        target = self._config.control.target(target_id)
        if target is None:
            return None

        settings = self._settings(target_id)
        try:
            port = open_serial_port(settings)
        except ModbusTransportError:
            return None

        try:
            response = PySerialModbusBitTransport(settings, serial_port=port).read_bits(
                ModbusBitReadRequest(
                    request_id=f"readback-{target_id}",
                    source_id=self._config.control_source(target_id),
                    unit_id=target.unit_id,
                    bit_kind=ModbusBitKind.COIL,
                    address=target.address,
                    quantity=1,
                )
            )
        except (ModbusTransportError, ModbusWriteError):
            return None
        finally:
            _close(port)

        return bool(response.bits[0])


def _settings(config: InstallationConfig, source_id: str) -> PySerialModbusConfig:
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


def _close(port: object) -> None:
    closer = getattr(port, "close", None)
    if callable(closer):
        closer()


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point. Returns a process exit code rather than raising."""

    arguments = build_parser().parse_args(argv)

    try:
        deltas = tuple(parse_delta(value) for value in arguments.delta)
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_USAGE

    try:
        config = load_configuration(Path(arguments.config))
    except ConfigurationError as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_USAGE

    try:
        # Opened once here only to fail loudly at startup rather than on the
        # first page load. Requests get their own connection; see below.
        open_readonly(config.database).close()
    except ReportingError as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_USAGE

    def page(token: str) -> str:
        """Render the page against a connection belonging to this request.

        Each request is served on its own thread and a SQLite connection cannot
        cross threads, so one is opened and closed per render. WAL makes that
        cheap, and it means a page can be rendered while the recorder writes.
        """

        connection = open_readonly(config.database)
        try:
            return render(
                connection,
                title=arguments.title,
                deltas=deltas,
                control_token=token,
                roster=roster_from(config),
            )
        finally:
            connection.close()

    def probe() -> list[dict[str, object]]:
        """Read every configured sensor from the hardware, right now.

        Each transport opens its own port and the probe closes over nothing, so
        this is safe to call from whichever request thread asks for it.
        """

        results: list[ProbeResult] = []
        for source in config.onewire_sources:
            results.extend(
                probe_onewire(
                    SysfsOneWireBus(source.root),
                    tuple(
                        read
                        for read in config.onewire_reads
                        if read.source_id == source.source_id
                    ),
                )
            )
        results.extend(
            probe_registers(
                lambda source_id: PySerialModbusTransport(_settings(config, source_id)),
                config.reads,
            )
        )
        results.extend(
            probe_bits(
                lambda source_id: PySerialModbusBitTransport(_settings(config, source_id)),
                config.bit_reads,
            )
        )
        return [
            {
                "label": item.label,
                "kind": str(item.kind),
                "reference": item.reference,
                "sensor_id": item.sensor_id,
                "value": item.value,
                "unit": item.unit,
                "ok": item.ok,
                "configured": item.configured,
                "suspect": item.suspect,
                "detail": item.detail,
            }
            for item in results
        ]

    bus = SerialBus(config)
    surface = ControlSurface(
        build_service(config.control, bus),
        config.control,
        page=page,
        read_state=bus.read_state,
        probe=probe,
    )

    server = serve(surface, host=arguments.bind, port=arguments.port)
    _announce(arguments.bind, arguments.port, config.control)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping")
    finally:
        server.server_close()

    return EXIT_OK


def _announce(bind: str, port: int, policy: ControlPolicy) -> None:
    """Say plainly what is now reachable, and by whom."""

    print(f"serving http://{bind}:{port}/")

    if bind != LOOPBACK:
        print(
            f"WARNING: bound to {bind}, not {LOOPBACK}. Anything that can reach this "
            "machine on the network can now operate the whitelisted relays. The token "
            "is the only thing in the way, and it is served to whoever loads the page.",
            file=sys.stderr,
        )

    if policy.enabled:
        print(f"control is ENABLED for {len(policy.targets)} relay(s)")
    else:
        print("control is disabled in the configuration; commands will be refused")


if __name__ == "__main__":
    sys.exit(main())
