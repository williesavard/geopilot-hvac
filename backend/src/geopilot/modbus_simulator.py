"""Simulator-backed Modbus register client port.

This module defines a clean read-only client boundary for future Modbus-style
acquisition tests. It does not open serial ports, speak Modbus RTU on the wire,
poll real hardware, perform writes, or claim device support.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from geopilot.acquisition import (
    AcquisitionErrorCode,
    AcquisitionPipeline,
    AcquisitionResult,
    context_from_definition,
)
from geopilot.ingestion import RawMeasurement
from geopilot.modbus_transport import (
    ModbusReadRequest,
    ModbusTransport,
    ModbusTransportError,
    ModbusTransportErrorCode,
)
from geopilot.register_decoder import (
    RegisterDecoder,
    RegisterDecoderError,
    RegisterDefinition,
    SimulatedRegisterPayload,
)


class ModbusSimulatorError(ValueError):
    """Raised when simulated Modbus register acquisition cannot proceed."""

    def __init__(
        self,
        message: str,
        *,
        acquisition_code: AcquisitionErrorCode = AcquisitionErrorCode.READ_FAILED,
    ) -> None:
        super().__init__(message)
        self.acquisition_code = acquisition_code


class ModbusRegisterClient(Protocol):
    """Read-only register client boundary for simulator and future transports."""

    def read_register(self, definition: RegisterDefinition) -> SimulatedRegisterPayload:
        """Return raw register words for one register definition."""


class SimulatedModbusRegisterClient:
    """In-memory register client for hardware-free acquisition tests."""

    def __init__(self, payloads: Iterable[SimulatedRegisterPayload]) -> None:
        self._payloads: dict[str, SimulatedRegisterPayload] = {}
        self._read_register_ids: list[str] = []

        for payload in payloads:
            if payload.register_id in self._payloads:
                raise ModbusSimulatorError(f"Duplicate simulated register: {payload.register_id}")
            self._payloads[payload.register_id] = payload

    def read_register(self, definition: RegisterDefinition) -> SimulatedRegisterPayload:
        self._read_register_ids.append(definition.register_id)
        try:
            return self._payloads[definition.register_id]
        except KeyError as exc:
            raise ModbusSimulatorError(
                f"Missing simulated payload for register: {definition.register_id}"
            ) from exc

    def read_register_ids(self) -> tuple[str, ...]:
        """Return register ids read so far, in read order."""

        return tuple(self._read_register_ids)


class TransportBackedSimulatedModbusRegisterClient:
    """Register client backed by a hardware-free Modbus transport."""

    def __init__(
        self,
        transport: ModbusTransport,
        requests: Iterable[tuple[str, ModbusReadRequest]],
    ) -> None:
        self._transport = transport
        self._requests: dict[str, ModbusReadRequest] = {}
        self._read_register_ids: list[str] = []

        for register_id, request in requests:
            if not register_id.strip():
                raise ModbusSimulatorError("register_id must be a non-empty identifier")
            if register_id in self._requests:
                raise ModbusSimulatorError(f"Duplicate transport register: {register_id}")
            self._requests[register_id] = request

    def read_register(self, definition: RegisterDefinition) -> SimulatedRegisterPayload:
        self._read_register_ids.append(definition.register_id)

        try:
            request = self._requests[definition.register_id]
        except KeyError as exc:
            raise ModbusSimulatorError(
                f"Missing transport request for register: {definition.register_id}",
                acquisition_code=AcquisitionErrorCode.PROFILE_INCOMPLETE,
            ) from exc

        try:
            response = self._transport.read_registers(request)
        except ModbusTransportError as exc:
            raise ModbusSimulatorError(
                str(exc),
                acquisition_code=_acquisition_code_from_transport_error(exc.code),
            ) from exc

        return SimulatedRegisterPayload(
            register_id=definition.register_id,
            words=response.words,
            observed_at=response.observed_at,
        )

    def read_register_ids(self) -> tuple[str, ...]:
        """Return register ids read so far, in read order."""

        return tuple(self._read_register_ids)


class SimulatedModbusAcquisitionService:
    """Decode register reads from a Modbus client into raw measurements."""

    def __init__(
        self,
        client: ModbusRegisterClient,
        decoder: RegisterDecoder | None = None,
    ) -> None:
        self._client = client
        self._decoder = decoder or RegisterDecoder()

    def read_raw_measurements(
        self,
        definitions: Iterable[RegisterDefinition],
    ) -> tuple[RawMeasurement, ...]:
        raw_measurements: list[RawMeasurement] = []
        for definition in definitions:
            payload = self._client.read_register(definition)
            raw_measurements.append(self._decoder.decode(definition, payload))
        return tuple(raw_measurements)

    def acquire(
        self,
        definitions: Iterable[RegisterDefinition],
        pipeline: AcquisitionPipeline,
        *,
        profile_id: str | None = None,
    ) -> tuple[AcquisitionResult, ...]:
        """Read, decode, normalize and store measurements as structured results."""

        results: list[AcquisitionResult] = []
        for definition in definitions:
            results.extend(
                self._read_decode_and_ingest(
                    definition,
                    pipeline=pipeline,
                    profile_id=profile_id,
                )
            )
        return tuple(results)

    def _read_decode_and_ingest(
        self,
        definition: RegisterDefinition,
        *,
        pipeline: AcquisitionPipeline,
        profile_id: str | None,
    ) -> tuple[AcquisitionResult, ...]:
        context = context_from_definition(
            source_id=definition.source_id,
            profile_id=profile_id,
            register_id=definition.register_id,
            sensor_id=definition.sensor_id,
        )
        try:
            payload = self._client.read_register(definition)
        except ModbusSimulatorError as exc:
            return (
                pipeline.failure(
                    context,
                    code=exc.acquisition_code,
                    message=str(exc),
                ),
            )

        try:
            raw = self._decoder.decode(definition, payload)
        except RegisterDecoderError as exc:
            return (
                pipeline.failure(
                    context,
                    code=AcquisitionErrorCode.DECODE_FAILED,
                    message=str(exc),
                ),
            )

        return pipeline.ingest_raw_measurements((raw,), profile_id=profile_id)


def _acquisition_code_from_transport_error(
    code: ModbusTransportErrorCode,
) -> AcquisitionErrorCode:
    match code:
        case ModbusTransportErrorCode.INVALID_RESPONSE:
            return AcquisitionErrorCode.PARTIAL_READ
        case (
            ModbusTransportErrorCode.TIMEOUT
            | ModbusTransportErrorCode.CONNECTION_FAILED
            | ModbusTransportErrorCode.ILLEGAL_FUNCTION
            | ModbusTransportErrorCode.ILLEGAL_ADDRESS
            | ModbusTransportErrorCode.DEVICE_FAILURE
            | ModbusTransportErrorCode.UNKNOWN
        ):
            return AcquisitionErrorCode.READ_FAILED
