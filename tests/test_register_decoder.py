from __future__ import annotations

import struct
from datetime import UTC, datetime

import pytest
from geopilot.ingestion import MeasurementNormalizer
from geopilot.register_decoder import (
    RegisterDataType,
    RegisterDecoder,
    RegisterDecoderError,
    RegisterDefinition,
    SimulatedRegisterPayload,
    decode_words,
)

OBSERVED_AT = datetime(2026, 7, 21, 12, 0, 0, tzinfo=UTC)
RECEIVED_AT = datetime(2026, 7, 21, 12, 1, 0, tzinfo=UTC)


def definition(
    *,
    data_type: RegisterDataType = RegisterDataType.UINT16,
    scale: float = 1.0,
    offset: float = 0.0,
) -> RegisterDefinition:
    return RegisterDefinition(
        register_id="sim.temperature",
        source_id="source_simulated_registers",
        sensor_id="sensor_loop_entering_temp",
        unit="degC",
        data_type=data_type,
        scale=scale,
        offset=offset,
        source_reference="simulated fixture",
    )


def payload(*words: int, register_id: str = "sim.temperature") -> SimulatedRegisterPayload:
    return SimulatedRegisterPayload(
        register_id=register_id,
        words=words,
        observed_at=OBSERVED_AT,
    )


def test_decodes_uint16_scaled_register_to_raw_measurement() -> None:
    raw = RegisterDecoder().decode(definition(scale=0.1), payload(215))

    assert raw.source_id == "source_simulated_registers"
    assert raw.sensor_id == "sensor_loop_entering_temp"
    assert raw.value == 21.5
    assert raw.unit == "degC"
    assert raw.timestamp == OBSERVED_AT
    assert raw.metadata["register_id"] == "sim.temperature"


def test_decodes_signed_int16_register() -> None:
    raw = RegisterDecoder().decode(
        definition(data_type=RegisterDataType.INT16, scale=0.1),
        payload(0xFF33),
    )

    assert raw.value == -20.5


def test_decoded_raw_measurement_can_flow_through_normalizer() -> None:
    raw = RegisterDecoder().decode(definition(scale=0.1), payload(215))

    measurement = MeasurementNormalizer(clock=lambda: RECEIVED_AT).normalize(raw)

    assert measurement.sensor_id == "sensor_loop_entering_temp"
    assert measurement.observed_at == OBSERVED_AT
    assert measurement.received_at == RECEIVED_AT
    assert measurement.value == 21.5
    assert measurement.unit == "degC"


def test_rejects_payload_for_different_register() -> None:
    with pytest.raises(RegisterDecoderError, match="does not match"):
        RegisterDecoder().decode(definition(), payload(1, register_id="other"))


def test_rejects_missing_source_reference() -> None:
    with pytest.raises(RegisterDecoderError, match="source_reference"):
        RegisterDefinition(
            register_id="sim.temperature",
            source_id="source_simulated_registers",
            sensor_id="sensor_loop_entering_temp",
            unit="degC",
            data_type=RegisterDataType.UINT16,
        )


def test_rejects_invalid_word_values() -> None:
    with pytest.raises(RegisterDecoderError, match="unsigned 16-bit"):
        payload(0x10000)


def test_rejects_wrong_word_count() -> None:
    with pytest.raises(RegisterDecoderError, match="uint16 requires"):
        RegisterDecoder().decode(definition(), payload(1, 2))


def test_rejects_naive_payload_timestamp() -> None:
    with pytest.raises(RegisterDecoderError, match="timezone-aware"):
        SimulatedRegisterPayload(
            register_id="sim.temperature",
            words=(215,),
            observed_at=datetime(2026, 7, 21, 12, 0, 0),
        )


def test_a_float32_spans_two_registers_high_word_first() -> None:
    """The Eastron order, and the one most Modbus documentation shows."""

    assert decode_words((0x4348, 0x0000), RegisterDataType.FLOAT32) == pytest.approx(200.0)


def test_a_swapped_float32_reads_the_same_words_low_word_first() -> None:
    assert decode_words((0x0000, 0x4348), RegisterDataType.FLOAT32_SWAPPED) == pytest.approx(
        200.0
    )


def test_the_two_word_orders_are_not_interchangeable() -> None:
    """Guessing wrong does not give a slightly wrong number; it gives nonsense."""

    words = (0x4348, 0x0000)
    correct = decode_words(words, RegisterDataType.FLOAT32)
    swapped = decode_words(words, RegisterDataType.FLOAT32_SWAPPED)

    assert correct == pytest.approx(200.0)
    assert abs(swapped) < 1e-30


def test_a_negative_float32_survives_the_round_trip() -> None:
    """Power flowing the other way, which a heat pump does not do — but a CT
    mounted backwards does, and that has to be visible rather than absurd."""

    words = struct.unpack(">HH", struct.pack(">f", -1234.5))

    assert decode_words(words, RegisterDataType.FLOAT32) == pytest.approx(-1234.5)


def test_a_float32_needs_exactly_two_words() -> None:
    for words in ((0x4348,), (0x4348, 0x0000, 0x0000)):
        with pytest.raises(RegisterDecoderError, match="2 register word"):
            decode_words(words, RegisterDataType.FLOAT32)


def test_a_non_finite_float_is_refused_rather_than_recorded() -> None:
    """One NaN makes every mean, minimum and maximum over the window NaN too."""

    nan = struct.unpack(">HH", struct.pack(">f", float("nan")))
    infinity = struct.unpack(">HH", struct.pack(">f", float("inf")))

    for words in (nan, infinity):
        with pytest.raises(RegisterDecoderError, match="non-finite"):
            decode_words(words, RegisterDataType.FLOAT32)


def test_a_measurement_of_zero_is_not_confused_with_unavailable() -> None:
    """A meter reading exactly zero watts is a fact, not a missing value."""

    words = struct.unpack(">HH", struct.pack(">f", 0.0))

    assert decode_words(words, RegisterDataType.FLOAT32) == 0.0


def test_the_sixteen_bit_types_still_take_one_word() -> None:
    assert decode_words((0x00D7,), RegisterDataType.INT16) == 215
    assert decode_words((0xFFCE,), RegisterDataType.INT16) == -50
    assert decode_words((0xFFCE,), RegisterDataType.UINT16) == 65486
