from __future__ import annotations

import ast
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from geopilot.acquisition import AcquisitionErrorCode, AcquisitionFailure, AcquisitionPipeline
from geopilot.domain import (
    Equipment,
    EquipmentType,
    HVACSystem,
    MeasurementKind,
    Residence,
    Sensor,
    SystemType,
)
from geopilot.historian import InMemoryMeasurementHistorian
from geopilot.ingestion import IngestionService, MeasurementNormalizer
from geopilot.modbus_simulator import (
    SimulatedModbusAcquisitionService,
    TransportBackedSimulatedModbusRegisterClient,
)
from geopilot.modbus_transport import (
    FakeModbusTransport,
    ModbusReadRequest,
    ModbusReadResponse,
    ModbusRegisterKind,
    ModbusTransportBoundaryError,
    ModbusTransportError,
    ModbusTransportErrorCode,
)
from geopilot.register_decoder import RegisterDataType, RegisterDefinition
from geopilot.registry import InMemoryAssetRegistry

CREATED_AT = datetime(2026, 7, 21, 12, 0, 0, tzinfo=UTC)
OBSERVED_AT = datetime(2026, 7, 21, 12, 5, 0, tzinfo=UTC)
RECEIVED_AT = datetime(2026, 7, 21, 12, 6, 0, tzinfo=UTC)


def test_modbus_read_request_represents_read_only_register_request() -> None:
    request = read_request("temperature", register_kind=ModbusRegisterKind.INPUT)

    assert request.request_id == "temperature"
    assert request.source_id == "source_simulated_modbus"
    assert request.unit_id == 1
    assert request.register_kind is ModbusRegisterKind.INPUT
    assert request.address == 100
    assert request.quantity == 1


def test_modbus_read_request_rejects_invalid_quantity() -> None:
    with pytest.raises(ModbusTransportBoundaryError, match="quantity"):
        ModbusReadRequest(
            request_id="bad",
            source_id="source_simulated_modbus",
            unit_id=1,
            register_kind=ModbusRegisterKind.HOLDING,
            address=100,
            quantity=0,
        )


def test_modbus_read_response_returns_raw_words_only() -> None:
    response = read_response("temperature", (215,))

    assert response.words == (215,)
    assert response.observed_at == OBSERVED_AT
    json.dumps(
        {
            "request_id": response.request_id,
            "words": response.words,
            "observed_at": response.observed_at.isoformat(),
        },
        sort_keys=True,
    )


def test_fake_transport_returns_valid_response_in_request_order() -> None:
    transport = FakeModbusTransport(
        responses=(
            read_response("humidity", (430,)),
            read_response("temperature", (215,)),
        )
    )

    response = transport.read_registers(read_request("temperature"))

    assert response.words == (215,)
    assert transport.read_request_ids() == ("temperature",)


def test_fake_transport_reports_device_absent_as_timeout() -> None:
    transport = FakeModbusTransport(
        errors=(
            ModbusTransportError(
                code=ModbusTransportErrorCode.TIMEOUT,
                message="device did not respond",
                request_id="temperature",
            ),
        )
    )

    with pytest.raises(ModbusTransportError) as exc_info:
        transport.read_registers(read_request("temperature"))

    assert exc_info.value.code is ModbusTransportErrorCode.TIMEOUT
    assert "device did not respond" in str(exc_info.value)


def test_fake_transport_reports_missing_register_as_illegal_address() -> None:
    transport = FakeModbusTransport()

    with pytest.raises(ModbusTransportError) as exc_info:
        transport.read_registers(read_request("missing"))

    assert exc_info.value.code is ModbusTransportErrorCode.ILLEGAL_ADDRESS


def test_fake_transport_reports_short_response_as_invalid_response() -> None:
    transport = FakeModbusTransport(
        responses=(read_response("temperature", (215,)),)
    )

    with pytest.raises(ModbusTransportError) as exc_info:
        transport.read_registers(read_request("temperature", quantity=2))

    assert exc_info.value.code is ModbusTransportErrorCode.INVALID_RESPONSE


@pytest.mark.parametrize(
    "error_code",
    (
        ModbusTransportErrorCode.ILLEGAL_FUNCTION,
        ModbusTransportErrorCode.ILLEGAL_ADDRESS,
        ModbusTransportErrorCode.DEVICE_FAILURE,
        ModbusTransportErrorCode.CONNECTION_FAILED,
        ModbusTransportErrorCode.UNKNOWN,
    ),
)
def test_fake_transport_can_simulate_modbus_exception_categories(
    error_code: ModbusTransportErrorCode,
) -> None:
    transport = FakeModbusTransport(
        errors=(
            ModbusTransportError(
                code=error_code,
                message="simulated Modbus exception",
                request_id="temperature",
            ),
        )
    )

    with pytest.raises(ModbusTransportError) as exc_info:
        transport.read_registers(read_request("temperature"))

    assert exc_info.value.code is error_code


def test_modbus_transport_module_has_no_domain_dependency() -> None:
    source = Path("backend/src/geopilot/modbus_transport.py").read_text()
    parsed = ast.parse(source)
    imports: list[str] = []
    for node in ast.walk(parsed):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            imports.append(node.module)

    assert "geopilot.domain" not in imports
    assert "geopilot.ingestion" not in imports
    assert "geopilot.historian" not in imports
    assert "geopilot.snapshot" not in imports
    assert "serial" not in imports
    assert "pyserial" not in imports


def test_fake_transport_integrates_with_acquisition_pipeline() -> None:
    registry = registry_with_modbus_sensor()
    historian = InMemoryMeasurementHistorian()
    pipeline = AcquisitionPipeline(
        IngestionService(
            MeasurementNormalizer(clock=lambda: RECEIVED_AT),
            historian,
            registry,
        ),
        clock=lambda: RECEIVED_AT,
    )
    request = read_request("temperature")
    transport = FakeModbusTransport(responses=(read_response("temperature", (215,)),))
    client = TransportBackedSimulatedModbusRegisterClient(
        transport,
        requests=(("sim.temperature", request),),
    )

    results = SimulatedModbusAcquisitionService(client).acquire(
        (register_definition("sim.temperature", "sensor_temperature", "degC", scale=0.1),),
        pipeline,
        profile_id="simulated.transport.v1",
    )

    assert len(results) == 1
    assert historian.count() == 1
    assert historian.all()[0].sensor_id == "sensor_temperature"
    assert historian.all()[0].value == 21.5
    assert transport.read_request_ids() == ("temperature",)
    assert client.read_register_ids() == ("sim.temperature",)


def test_transport_error_maps_to_acquisition_failure() -> None:
    registry = registry_with_modbus_sensor()
    historian = InMemoryMeasurementHistorian()
    pipeline = AcquisitionPipeline(
        IngestionService(
            MeasurementNormalizer(clock=lambda: RECEIVED_AT),
            historian,
            registry,
        ),
        clock=lambda: RECEIVED_AT,
    )
    transport = FakeModbusTransport(
        errors=(
            ModbusTransportError(
                code=ModbusTransportErrorCode.INVALID_RESPONSE,
                message="short response",
                request_id="temperature",
            ),
        )
    )
    client = TransportBackedSimulatedModbusRegisterClient(
        transport,
        requests=(("sim.temperature", read_request("temperature")),),
    )

    results = SimulatedModbusAcquisitionService(client).acquire(
        (register_definition("sim.temperature", "sensor_temperature", "degC", scale=0.1),),
        pipeline,
        profile_id="simulated.transport.v1",
    )

    assert len(results) == 1
    failure = results[0]
    assert isinstance(failure, AcquisitionFailure)
    assert failure.code is AcquisitionErrorCode.PARTIAL_READ
    assert "short response" in failure.message
    assert historian.all() == ()


def read_request(
    request_id: str,
    *,
    register_kind: ModbusRegisterKind = ModbusRegisterKind.HOLDING,
    quantity: int = 1,
) -> ModbusReadRequest:
    return ModbusReadRequest(
        request_id=request_id,
        source_id="source_simulated_modbus",
        unit_id=1,
        register_kind=register_kind,
        address=100,
        quantity=quantity,
    )


def read_response(request_id: str, words: tuple[int, ...]) -> ModbusReadResponse:
    return ModbusReadResponse(
        request_id=request_id,
        words=words,
        observed_at=OBSERVED_AT,
    )


def register_definition(
    register_id: str,
    sensor_id: str,
    unit: str,
    *,
    scale: float,
) -> RegisterDefinition:
    return RegisterDefinition(
        register_id=register_id,
        source_id="source_simulated_modbus",
        sensor_id=sensor_id,
        unit=unit,
        data_type=RegisterDataType.UINT16,
        scale=scale,
        source_reference="simulated transport fixture",
    )


def registry_with_modbus_sensor() -> InMemoryAssetRegistry:
    registry = InMemoryAssetRegistry()
    registry.add_residence(
        Residence(
            id="residence_home",
            name="Home",
            timezone="America/Toronto",
            created_at=CREATED_AT,
        )
    )
    registry.add_hvac_system(
        HVACSystem(
            id="system_main",
            residence_id="residence_home",
            name="Main system",
            system_type=SystemType.HYDRONIC,
            created_at=CREATED_AT,
        )
    )
    registry.add_equipment(
        Equipment(
            id="equipment_heat_pump",
            hvac_system_id="system_main",
            name="Heat pump",
            equipment_type=EquipmentType.HEAT_PUMP,
            created_at=CREATED_AT,
        )
    )
    registry.add_sensor(
        Sensor(
            id="sensor_temperature",
            equipment_id="equipment_heat_pump",
            name="Temperature",
            measurement_kind=MeasurementKind.TEMPERATURE,
            unit="degC",
            source_id="source_simulated_modbus",
            created_at=CREATED_AT,
        )
    )
    return registry
