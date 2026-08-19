"""Continuous acquisition runtime.

This module turns an `InstallationConfig` into something that records, as
decided in ``docs/CONTINUOUS_ACQUISITION_ADR.md``. It assembles the registry,
the transports, the acquisition pipeline and the historian, then executes
acquisition cycles.

Scheduling lives here and nowhere else. No `sleep`, thread, async or scheduler
enters the domain, ingestion, historian, acquisition or transport modules.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from types import TracebackType

from geopilot.acquisition import (
    AcquisitionContext,
    AcquisitionErrorCode,
    AcquisitionFailure,
    AcquisitionPipeline,
    AcquisitionResult,
)
from geopilot.acquisition_runner import (
    AcquisitionPlan,
    AcquisitionRequest,
    AcquisitionRunner,
    AcquisitionRunReport,
    RequestExecutor,
)
from geopilot.configuration import (
    BitReadConfig,
    InstallationConfig,
    OneWireReadConfig,
    OneWireSourceConfig,
    RegisterReadConfig,
    SerialSourceConfig,
)
from geopilot.ingestion import STATE_UNIT, IngestionService, MeasurementNormalizer, RawMeasurement
from geopilot.modbus_pyserial_transport import (
    PySerialModbusBitTransport,
    PySerialModbusConfig,
    PySerialModbusTransport,
)
from geopilot.modbus_simulator import (
    SimulatedModbusAcquisitionService,
    TransportBackedSimulatedModbusRegisterClient,
)
from geopilot.modbus_transport import (
    ModbusBitReadRequest,
    ModbusBitTransport,
    ModbusReadRequest,
    ModbusTransport,
    ModbusTransportError,
)
from geopilot.onewire import (
    OneWireAcquisitionService,
    OneWireBus,
    OneWireError,
    OneWireSensorDefinition,
    SysfsOneWireBus,
)
from geopilot.provenance import provenance_from
from geopilot.register_decoder import RegisterDefinition
from geopilot.registry import InMemoryAssetRegistry
from geopilot.sqlite_historian import SqliteMeasurementHistorian
from geopilot.sqlite_provenance import (
    ConfigurationEpoch,
    SqliteProvenanceJournal,
    provenance_path,
)

Clock = Callable[[], datetime]
TransportFactory = Callable[[SerialSourceConfig], ModbusTransport]
OneWireBusFactory = Callable[[OneWireSourceConfig], OneWireBus]
BitTransportFactory = Callable[[SerialSourceConfig], ModbusBitTransport]
Sleeper = Callable[[float], None]


def utc_now() -> datetime:
    """Return the current UTC time."""

    return datetime.now(UTC)


def open_serial_transport(source: SerialSourceConfig) -> ModbusTransport:
    """Open a real serial transport for a configured source."""

    return PySerialModbusTransport(
        PySerialModbusConfig(
            port=source.port,
            baudrate=source.baudrate,
            parity=source.parity,
            stopbits=source.stopbits,
            bytesize=source.bytesize,
            timeout=source.timeout,
        )
    )


def open_bit_transport(source: SerialSourceConfig) -> ModbusBitTransport:
    """Open a bit transport for a configured serial source."""

    return PySerialModbusBitTransport(
        PySerialModbusConfig(
            port=source.port,
            baudrate=source.baudrate,
            parity=source.parity,
            stopbits=source.stopbits,
            bytesize=source.bytesize,
            timeout=source.timeout,
        )
    )


def build_bit_read_request(read: BitReadConfig) -> ModbusBitReadRequest:
    """Convert one configured bit read into a transport request."""

    return ModbusBitReadRequest(
        request_id=read.read_id,
        source_id=read.source_id,
        unit_id=read.unit_id,
        bit_kind=read.bit_kind,
        address=read.address,
        quantity=1,
    )


def open_onewire_bus(source: OneWireSourceConfig) -> OneWireBus:
    """Open a sysfs-backed 1-Wire bus for a configured source."""

    return SysfsOneWireBus(source.root)


def build_onewire_definition(read: OneWireReadConfig) -> OneWireSensorDefinition:
    """Convert one configured probe into a 1-Wire sensor definition."""

    return OneWireSensorDefinition(
        device_id=read.device_id,
        source_id=read.source_id,
        sensor_id=read.sensor_id,
        unit=read.unit,
        offset_celsius=read.offset_celsius,
        source_reference=read.source_reference,
    )


def build_registry(config: InstallationConfig) -> InMemoryAssetRegistry:
    """Populate an asset registry from configuration."""

    registry = InMemoryAssetRegistry()
    registry.add_residence(config.residence)
    for system in config.systems:
        registry.add_hvac_system(system)
    for equipment in config.equipment:
        registry.add_equipment(equipment)
    for sensor in config.sensors:
        registry.add_sensor(sensor)
    return registry


def build_register_definition(read: RegisterReadConfig) -> RegisterDefinition:
    """Convert one configured read into a register definition."""

    return RegisterDefinition(
        register_id=read.read_id,
        source_id=read.source_id,
        sensor_id=read.sensor_id,
        unit=read.unit,
        data_type=read.data_type,
        scale=read.scale,
        offset=read.offset,
        source_reference=read.source_reference,
    )


def build_read_request(read: RegisterReadConfig) -> ModbusReadRequest:
    """Convert one configured read into a transport read request."""

    return ModbusReadRequest(
        request_id=read.read_id,
        source_id=read.source_id,
        unit_id=read.unit_id,
        register_kind=read.register_kind,
        address=read.address,
        quantity=read.quantity,
    )


@dataclass(frozen=True, slots=True)
class CycleOutcome:
    """Result of one acquisition cycle."""

    report: AcquisitionRunReport | None
    error: str | None

    @property
    def succeeded(self) -> bool:
        return self.report is not None


class AcquisitionSession:
    """Assembled runtime for one installation.

    Opens the database and every configured transport on construction, then
    executes acquisition cycles on demand.
    """

    def __init__(
        self,
        config: InstallationConfig,
        *,
        transport_factory: TransportFactory = open_serial_transport,
        onewire_bus_factory: OneWireBusFactory = open_onewire_bus,
        bit_transport_factory: BitTransportFactory = open_bit_transport,
        clock: Clock = utc_now,
        historian: SqliteMeasurementHistorian | None = None,
        provenance: SqliteProvenanceJournal | None = None,
    ) -> None:
        self._config = config
        self._owns_historian = historian is None
        self._historian = historian or SqliteMeasurementHistorian(config.database)
        self._owns_provenance = provenance is None
        self._provenance = provenance or SqliteProvenanceJournal(
            provenance_path(config.database)
        )
        self._epoch = self._provenance.record(provenance_from(config), at=clock())
        self._registry = build_registry(config)
        self._pipeline = AcquisitionPipeline(
            IngestionService(
                MeasurementNormalizer(clock=clock),
                self._historian,
                self._registry,
            ),
            clock=clock,
        )
        self._runner = AcquisitionRunner(self._pipeline, clock=clock)
        self._plan = self._build_plan(
            transport_factory, onewire_bus_factory, bit_transport_factory
        )

    @property
    def historian(self) -> SqliteMeasurementHistorian:
        """Return the historian this session writes to."""

        return self._historian

    @property
    def provenance(self) -> SqliteProvenanceJournal:
        """Return the journal recording what corrections are in effect."""

        return self._provenance

    @property
    def epoch(self) -> ConfigurationEpoch | None:
        """The epoch this session opened, or None when nothing had changed.

        A new epoch means a correction moved since the last run, which is worth
        saying out loud: it is the moment the series stops being directly
        comparable with what came before.
        """

        return self._epoch

    def run_cycle(self) -> CycleOutcome:
        """Execute one acquisition cycle.

        A failed read is already a structured `AcquisitionFailure` and does not
        raise. An unexpected error is captured so an unattended run survives it,
        because a year of recording must not end because of one bad night.
        Storage errors are deliberately not caught: if measurements cannot be
        written, continuing would discard the data the exercise exists for.
        """

        try:
            return CycleOutcome(report=self._runner.run(self._plan), error=None)
        except Exception as error:  # noqa: BLE001 - unattended runs must survive
            return CycleOutcome(report=None, error=f"{type(error).__name__}: {error}")

    def close(self) -> None:
        """Release the database connection if this session opened it."""

        if self._owns_historian:
            self._historian.close()
        if self._owns_provenance:
            self._provenance.close()

    def __enter__(self) -> AcquisitionSession:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def _build_plan(
        self,
        transport_factory: TransportFactory,
        onewire_bus_factory: OneWireBusFactory,
        bit_transport_factory: BitTransportFactory,
    ) -> AcquisitionPlan:
        requests: list[AcquisitionRequest] = []

        for source in self._config.sources:
            reads = tuple(
                read for read in self._config.reads if read.source_id == source.source_id
            )
            if not reads:
                continue

            client = TransportBackedSimulatedModbusRegisterClient(
                transport_factory(source),
                tuple((read.read_id, build_read_request(read)) for read in reads),
            )
            service = SimulatedModbusAcquisitionService(client)
            definitions = tuple(build_register_definition(read) for read in reads)
            requests.append(
                AcquisitionRequest(
                    request_id=source.source_id,
                    profile_id=None,
                    executor=_executor_for(service, definitions),
                )
            )

        for onewire_source in self._config.onewire_sources:
            probes = tuple(
                read
                for read in self._config.onewire_reads
                if read.source_id == onewire_source.source_id
            )
            if not probes:
                continue

            onewire_service = OneWireAcquisitionService(onewire_bus_factory(onewire_source))
            probe_definitions = tuple(build_onewire_definition(read) for read in probes)
            requests.append(
                AcquisitionRequest(
                    request_id=onewire_source.source_id,
                    profile_id=None,
                    executor=_onewire_executor_for(onewire_service, probe_definitions),
                )
            )

        for source in self._config.sources:
            bit_reads = tuple(
                read for read in self._config.bit_reads if read.source_id == source.source_id
            )
            if not bit_reads:
                continue

            requests.append(
                AcquisitionRequest(
                    request_id=f"{source.source_id}:bits",
                    profile_id=None,
                    executor=_bit_executor_for(bit_transport_factory(source), bit_reads),
                )
            )

        return AcquisitionPlan(plan_id="installation", requests=tuple(requests))


def _executor_for(
    service: SimulatedModbusAcquisitionService,
    definitions: tuple[RegisterDefinition, ...],
) -> RequestExecutor:
    def execute(pipeline: AcquisitionPipeline) -> tuple[AcquisitionResult, ...]:
        return service.acquire(definitions, pipeline)

    return execute


def _onewire_executor_for(
    service: OneWireAcquisitionService,
    definitions: tuple[OneWireSensorDefinition, ...],
) -> RequestExecutor:
    def execute(pipeline: AcquisitionPipeline) -> tuple[AcquisitionResult, ...]:
        results: list[AcquisitionResult] = []
        for definition in definitions:
            try:
                raw = service.read_raw_measurement(definition)
            except OneWireError as error:
                results.append(
                    AcquisitionFailure(
                        code=error.acquisition_code,
                        message=str(error),
                        context=AcquisitionContext(
                            source_id=definition.source_id,
                            profile_id=None,
                            register_id=definition.device_id,
                            sensor_id=definition.sensor_id,
                        ),
                        acquired_at=utc_now(),
                    )
                )
                continue
            results.extend(pipeline.ingest_raw_measurements((raw,)))
        return tuple(results)

    return execute


def _bit_executor_for(
    transport: ModbusBitTransport,
    reads: tuple[BitReadConfig, ...],
) -> RequestExecutor:
    def execute(pipeline: AcquisitionPipeline) -> tuple[AcquisitionResult, ...]:
        results: list[AcquisitionResult] = []
        for read in reads:
            try:
                response = transport.read_bits(build_bit_read_request(read))
            except ModbusTransportError as error:
                results.append(
                    AcquisitionFailure(
                        code=AcquisitionErrorCode.READ_FAILED,
                        message=str(error),
                        context=AcquisitionContext(
                            source_id=read.source_id,
                            profile_id=None,
                            register_id=read.read_id,
                            sensor_id=read.sensor_id,
                        ),
                        acquired_at=utc_now(),
                    )
                )
                continue

            asserted = response.bits[0] != read.inverted
            results.extend(
                pipeline.ingest_raw_measurements(
                    (
                        RawMeasurement(
                            source_id=read.source_id,
                            sensor_id=read.sensor_id,
                            value=1 if asserted else 0,
                            unit=STATE_UNIT,
                            timestamp=response.observed_at,
                        ),
                    )
                )
            )
        return tuple(results)

    return execute


def run_cycles(
    session: AcquisitionSession,
    *,
    cycles: int | None,
    interval_seconds: float,
    sleeper: Sleeper = time.sleep,
    on_cycle: Callable[[int, CycleOutcome], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> tuple[CycleOutcome, ...]:
    """Execute acquisition cycles, sleeping between them.

    `cycles=None` runs until `should_stop` returns True, which is the unattended
    mode. A finite count is used by the one-shot mode and by tests. No sleep
    occurs after the final cycle, and `should_stop` is consulted after every
    cycle so a shutdown signal takes effect within one interval.
    """

    if interval_seconds < 0:
        raise ValueError("interval_seconds must not be negative")

    outcomes: list[CycleOutcome] = []
    index = 0
    while cycles is None or index < cycles:
        outcome = session.run_cycle()
        outcomes.append(outcome)
        index += 1
        if on_cycle is not None:
            on_cycle(index, outcome)
        if cycles is not None and index >= cycles:
            break
        if should_stop is not None and should_stop():
            break
        if interval_seconds:
            sleeper(interval_seconds)

    return tuple(outcomes)


def summarize(outcomes: Iterable[CycleOutcome]) -> str:
    """Render a one-line summary of a run."""

    items = tuple(outcomes)
    successes = sum(1 for outcome in items if outcome.succeeded)
    stored = sum(
        outcome.report.success_count for outcome in items if outcome.report is not None
    )
    failures = sum(
        outcome.report.failure_count for outcome in items if outcome.report is not None
    )
    return (
        f"{len(items)} cycle(s), {successes} completed, "
        f"{stored} measurement(s) stored, {failures} read failure(s)"
    )
