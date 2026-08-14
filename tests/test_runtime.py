"""Continuous acquisition runtime tests.

Every test injects a fake transport. No test opens a serial port, and no test
sleeps for real.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from geopilot.configuration import (
    CONFIGURATION_VERSION,
    InstallationConfig,
    SerialSourceConfig,
    parse_configuration,
)
from geopilot.modbus_transport import (
    ModbusReadRequest,
    ModbusReadResponse,
    ModbusTransportError,
    ModbusTransportErrorCode,
)
from geopilot.runtime import (
    AcquisitionSession,
    CycleOutcome,
    build_read_request,
    build_register_definition,
    build_registry,
    run_cycles,
    summarize,
)
from geopilot.sqlite_historian import SqliteMeasurementHistorian

STAMP = datetime(2026, 8, 11, tzinfo=UTC)


class FakeTransport:
    """Returns scripted words, or raises a scripted transport error."""

    def __init__(self, words: tuple[int, ...] = (215,), error: ModbusTransportError | None = None):
        self._words = words
        self._error = error
        self.calls = 0

    def read_registers(self, request: ModbusReadRequest) -> ModbusReadResponse:
        self.calls += 1
        if self._error is not None:
            raise self._error
        return ModbusReadResponse(
            request_id=request.request_id,
            words=self._words,
            observed_at=STAMP + timedelta(seconds=self.calls),
        )


def document(database: Path) -> dict[str, Any]:
    return {
        "version": CONFIGURATION_VERSION,
        "storage": {"database": str(database)},
        "residence": {"id": "residence_home", "name": "Home", "timezone": "America/Toronto"},
        "system": [{"id": "system_main", "name": "Main", "system_type": "hydronic"}],
        "equipment": [
            {
                "id": "equipment_hp",
                "system_id": "system_main",
                "name": "Heat pump",
                "equipment_type": "heat_pump",
            }
        ],
        "sensor": [
            {
                "id": "sensor_loop_in",
                "equipment_id": "equipment_hp",
                "name": "Loop in",
                "measurement_kind": "temperature",
                "sensor_kind": "temperature",
                "unit": "degC",
                "source_id": "source_bus",
            }
        ],
        "source": [{"id": "source_bus", "port": "/dev/cu.fake"}],
        "read": [
            {
                "id": "read_loop_in",
                "source_id": "source_bus",
                "sensor_id": "sensor_loop_in",
                "unit_id": 1,
                "register": "input",
                "address": 1,
                "data_type": "int16",
                "unit": "degC",
                "scale": 0.1,
                "source_reference": "bench manual page 4",
            }
        ],
    }


def config_for(database: Path) -> InstallationConfig:
    return parse_configuration(document(database), created_at=STAMP)


def session_for(
    database: Path,
    transport: FakeTransport,
    historian: SqliteMeasurementHistorian | None = None,
) -> AcquisitionSession:
    return AcquisitionSession(
        config_for(database),
        transport_factory=lambda _source: transport,
        clock=lambda: STAMP,
        historian=historian,
    )


def test_registry_is_built_from_configuration(tmp_path: Path) -> None:
    registry = build_registry(config_for(tmp_path / "db.sqlite3"))

    assert registry.get_residence("residence_home").name == "Home"
    assert registry.get_hvac_system("system_main").name == "Main"
    assert registry.get_sensor("sensor_loop_in").unit == "degC"


def test_read_config_maps_to_definition_and_request(tmp_path: Path) -> None:
    read = config_for(tmp_path / "db.sqlite3").reads[0]

    definition = build_register_definition(read)
    request = build_read_request(read)

    assert definition.register_id == "read_loop_in"
    assert definition.scale == 0.1
    assert definition.source_reference == "bench manual page 4"
    assert request.unit_id == 1
    assert request.address == 1


def test_a_cycle_stores_a_measurement(tmp_path: Path) -> None:
    database = tmp_path / "db.sqlite3"
    transport = FakeTransport(words=(215,))

    with session_for(database, transport) as session:
        outcome = session.run_cycle()

        assert outcome.succeeded
        assert outcome.report is not None
        assert outcome.report.success_count == 1
        stored = session.historian.all()
        assert len(stored) == 1
        # 215 raw, scale 0.1 -> 21.5 degC
        assert stored[0].value == pytest.approx(21.5)
        assert stored[0].sensor_id == "sensor_loop_in"


def test_measurements_persist_to_the_configured_database(tmp_path: Path) -> None:
    database = tmp_path / "db.sqlite3"

    with session_for(database, FakeTransport()) as session:
        session.run_cycle()

    assert database.exists()
    with SqliteMeasurementHistorian(database) as reopened:
        assert reopened.count() == 1


def test_a_transport_failure_is_recorded_not_raised(tmp_path: Path) -> None:
    transport = FakeTransport(
        error=ModbusTransportError(
            code=ModbusTransportErrorCode.TIMEOUT,
            message="timed out",
        )
    )

    with session_for(tmp_path / "db.sqlite3", transport) as session:
        outcome = session.run_cycle()

        assert outcome.succeeded
        assert outcome.report is not None
        assert outcome.report.failure_count == 1
        assert outcome.report.success_count == 0
        assert session.historian.count() == 0


def test_each_cycle_stores_a_distinct_observation(tmp_path: Path) -> None:
    """The device timestamps each response, so cycles are distinct instants."""

    transport = FakeTransport()

    with session_for(tmp_path / "db.sqlite3", transport) as session:
        run_cycles(session, cycles=3, interval_seconds=0)

        assert transport.calls == 3
        assert session.historian.count() == 3


def test_run_cycles_sleeps_between_cycles_but_not_after_the_last(tmp_path: Path) -> None:
    slept: list[float] = []

    with session_for(tmp_path / "db.sqlite3", FakeTransport()) as session:
        run_cycles(session, cycles=3, interval_seconds=30, sleeper=slept.append)

    assert slept == [30, 30]


def test_run_cycles_reports_each_cycle(tmp_path: Path) -> None:
    seen: list[int] = []

    with session_for(tmp_path / "db.sqlite3", FakeTransport()) as session:
        run_cycles(
            session,
            cycles=2,
            interval_seconds=0,
            on_cycle=lambda index, _outcome: seen.append(index),
        )

    assert seen == [1, 2]


def test_negative_interval_is_rejected(tmp_path: Path) -> None:
    with (
        session_for(tmp_path / "db.sqlite3", FakeTransport()) as session,
        pytest.raises(ValueError, match="must not be negative"),
    ):
        run_cycles(session, cycles=1, interval_seconds=-1)


def test_an_unexpected_error_does_not_end_the_run(tmp_path: Path) -> None:
    """A year of recording must survive one bad night."""

    class ExplodingTransport(FakeTransport):
        def read_registers(self, request: ModbusReadRequest) -> ModbusReadResponse:
            raise RuntimeError("bus on fire")

    with session_for(tmp_path / "db.sqlite3", ExplodingTransport()) as session:
        outcomes = run_cycles(session, cycles=2, interval_seconds=0)

    assert len(outcomes) == 2
    assert all(not outcome.succeeded for outcome in outcomes)
    assert outcomes[0].error is not None
    assert "bus on fire" in outcomes[0].error


def test_a_source_with_no_reads_is_skipped(tmp_path: Path) -> None:
    payload = document(tmp_path / "db.sqlite3")
    payload["source"].append({"id": "source_unused", "port": "/dev/cu.unused"})
    opened: list[SerialSourceConfig] = []

    def factory(source: SerialSourceConfig) -> FakeTransport:
        opened.append(source)
        return FakeTransport()

    config = parse_configuration(payload, created_at=STAMP)
    with AcquisitionSession(
        config,
        transport_factory=factory,
        clock=lambda: STAMP,
    ) as session:
        session.run_cycle()

    assert [source.source_id for source in opened] == ["source_bus"]


def test_summary_counts_cycles_measurements_and_failures(tmp_path: Path) -> None:
    with session_for(tmp_path / "db.sqlite3", FakeTransport()) as session:
        outcomes = run_cycles(session, cycles=2, interval_seconds=0)

    line = summarize(outcomes)

    assert "2 cycle(s)" in line
    assert "2 completed" in line
    assert "2 measurement(s) stored" in line


def test_an_injected_historian_is_not_closed_by_the_session(tmp_path: Path) -> None:
    historian = SqliteMeasurementHistorian()
    try:
        with session_for(tmp_path / "db.sqlite3", FakeTransport(), historian) as session:
            session.run_cycle()
        # Still usable after the session exits.
        assert historian.count() == 1
    finally:
        historian.close()


def test_should_stop_ends_an_unbounded_run(tmp_path: Path) -> None:
    """A shutdown signal must take effect within one interval, not never."""

    stop_after = 2
    seen = 0

    def should_stop() -> bool:
        return seen >= stop_after

    with session_for(tmp_path / "db.sqlite3", FakeTransport()) as session:

        def count(_index: int, _outcome: CycleOutcome) -> None:
            nonlocal seen
            seen += 1

        outcomes = run_cycles(
            session,
            cycles=None,
            interval_seconds=0,
            on_cycle=count,
            should_stop=should_stop,
        )

    assert len(outcomes) == stop_after


def onewire_document(database: Path, tmp_path: Path) -> dict[str, Any]:
    """A configuration with both a Modbus source and a 1-Wire bus."""

    payload = document(database)
    payload["sensor"].append(
        {
            "id": "sensor_loop_out",
            "equipment_id": "equipment_hp",
            "name": "Loop out",
            "measurement_kind": "temperature",
            "sensor_kind": "temperature",
            "unit": "degC",
            "source_id": "source_probes",
        }
    )
    payload["onewire_source"] = [{"id": "source_probes", "root": str(tmp_path / "w1")}]
    payload["onewire_read"] = [
        {
            "id": "read_loop_out",
            "source_id": "source_probes",
            "sensor_id": "sensor_loop_out",
            "device_id": "28-0000075b2c3f",
            "offset_celsius": -0.12,
            "source_reference": "same-bath calibration 2026-08-11",
        }
    ]
    return payload


def test_a_cycle_reads_modbus_and_onewire_together(tmp_path: Path) -> None:
    from geopilot.onewire import FakeOneWireBus, OneWireReading

    config = parse_configuration(
        onewire_document(tmp_path / "db.sqlite3", tmp_path), created_at=STAMP
    )
    bus = FakeOneWireBus(
        {
            "28-0000075b2c3f": OneWireReading(
                device_id="28-0000075b2c3f",
                millidegrees=11500,
                observed_at=STAMP,
            )
        }
    )

    with AcquisitionSession(
        config,
        transport_factory=lambda _source: FakeTransport(),
        onewire_bus_factory=lambda _source: bus,
        clock=lambda: STAMP,
    ) as session:
        outcome = session.run_cycle()

        assert outcome.report is not None
        assert outcome.report.success_count == 2
        by_sensor = {item.sensor_id: item.value for item in session.historian.all()}
        assert by_sensor["sensor_loop_in"] == pytest.approx(21.5)
        # 11.5 raw, offset -0.12 applied
        assert by_sensor["sensor_loop_out"] == pytest.approx(11.38)


def test_a_probe_failure_is_a_structured_failure_not_a_crash(tmp_path: Path) -> None:
    from geopilot.onewire import FakeOneWireBus

    config = parse_configuration(
        onewire_document(tmp_path / "db.sqlite3", tmp_path), created_at=STAMP
    )

    with AcquisitionSession(
        config,
        transport_factory=lambda _source: FakeTransport(),
        onewire_bus_factory=lambda _source: FakeOneWireBus(),
        clock=lambda: STAMP,
    ) as session:
        outcome = session.run_cycle()

        assert outcome.succeeded
        assert outcome.report is not None
        assert outcome.report.success_count == 1
        assert outcome.report.failure_count == 1
        assert session.historian.count() == 1
