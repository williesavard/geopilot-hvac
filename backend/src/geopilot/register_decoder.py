"""Pure simulated register decoding for future acquisition adapters.

This module does not implement Modbus polling, serial ports, hardware access,
register maps for real devices, diagnostics, or equipment control. It only
turns explicitly provided 16-bit words into ``RawMeasurement`` objects for
tests and simulator-driven development.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from geopilot.ingestion import RawMeasurement


class RegisterDecoderError(ValueError):
    """Raised when a simulated register payload cannot be decoded safely."""


class RegisterDataType(StrEnum):
    """Supported register data representations.

    The two 32-bit float types differ only in **word order**, and that
    distinction is not pedantry: Modbus defines the order of bytes within a
    register and says nothing about the order of registers within a 32-bit
    value. Manufacturers split roughly evenly.

    Guess wrong and the value is not slightly off — it is nonsense of a
    magnitude that sometimes looks plausible. 230.5 read with the words
    swapped is 2.9e-41, which is obviously wrong; 4.2 kW read swapped can land
    on a number that passes for a reading. Both orders exist here so the
    configuration states which one the device uses, and the probe shows the raw
    words beside the decoded value so the choice can be checked rather than
    assumed.
    """

    UINT16 = "uint16"
    INT16 = "int16"
    FLOAT32 = "float32"
    """Two registers, high word first. Eastron, and most of Modbus's own docs."""

    FLOAT32_SWAPPED = "float32_swapped"
    """Two registers, low word first. Common on Schneider and many PLC gateways."""


@dataclass(frozen=True, slots=True)
class RegisterDefinition:
    """Source-reviewed mapping from one register value to one GeoPilot sensor."""

    register_id: str
    source_id: str
    sensor_id: str
    unit: str
    data_type: RegisterDataType
    scale: float = 1.0
    offset: float = 0.0
    source_reference: str = ""

    def __post_init__(self) -> None:
        _require_identifier(self.register_id, "register_id")
        _require_identifier(self.source_id, "source_id")
        _require_identifier(self.sensor_id, "sensor_id")
        _require_identifier(self.unit, "unit")
        _require_text(self.source_reference, "source_reference")
        _require_finite(self.scale, "scale")
        _require_finite(self.offset, "offset")
        if self.scale == 0:
            raise RegisterDecoderError("scale must not be zero")


@dataclass(frozen=True, slots=True)
class SimulatedRegisterPayload:
    """Raw words supplied by a simulator or captured-frame test."""

    register_id: str
    words: tuple[int, ...]
    observed_at: datetime

    def __post_init__(self) -> None:
        _require_identifier(self.register_id, "register_id")
        _require_aware_datetime(self.observed_at, "observed_at")
        if not self.words:
            raise RegisterDecoderError("words must contain at least one register")
        for word in self.words:
            if isinstance(word, bool) or not isinstance(word, int):
                raise RegisterDecoderError("words must be integers")
            if word < 0 or word > 0xFFFF:
                raise RegisterDecoderError("words must be unsigned 16-bit values")


class RegisterDecoder:
    """Decode simulated register payloads into neutral raw measurements."""

    def decode(
        self,
        definition: RegisterDefinition,
        payload: SimulatedRegisterPayload,
    ) -> RawMeasurement:
        if payload.register_id != definition.register_id:
            raise RegisterDecoderError(
                f"Payload register {payload.register_id} does not match "
                f"definition {definition.register_id}"
            )

        raw_value = decode_words(payload.words, definition.data_type)
        value = raw_value * definition.scale + definition.offset
        return RawMeasurement(
            source_id=definition.source_id,
            sensor_id=definition.sensor_id,
            value=value,
            unit=definition.unit,
            timestamp=payload.observed_at,
            metadata={
                "register_id": definition.register_id,
                "source_reference": definition.source_reference,
            },
        )


def decode_words(words: tuple[int, ...], data_type: RegisterDataType) -> float:
    """Turn raw register words into a number, per the declared representation.

    Public so the live probe decodes exactly as acquisition does. A second
    implementation would drift, and the first symptom would be a probe that
    disagrees with the recording about the same register.
    """

    match data_type:
        case RegisterDataType.UINT16:
            _require_word_count(words, 1, data_type)
            return words[0]
        case RegisterDataType.INT16:
            _require_word_count(words, 1, data_type)
            return _decode_int16(words[0])
        case RegisterDataType.FLOAT32:
            _require_word_count(words, 2, data_type)
            return _decode_float32(words[0], words[1])
        case RegisterDataType.FLOAT32_SWAPPED:
            _require_word_count(words, 2, data_type)
            return _decode_float32(words[1], words[0])


def _decode_int16(word: int) -> int:
    if word <= 0x7FFF:
        return word
    return word - 0x10000


def _decode_float32(high: int, low: int) -> float:
    """Assemble two registers into an IEEE-754 single.

    A meter reporting NaN or an infinity is reporting that it has no value —
    a CT not connected, or a phase not present. Letting that through would put
    a number in the historian that no aggregate can survive: one NaN makes
    every mean, minimum and maximum over the window NaN too, silently and
    permanently.
    """

    value: float = struct.unpack(">f", struct.pack(">HH", high, low))[0]
    if not math.isfinite(value):
        raise RegisterDecoderError(
            "the device returned a non-finite float, which usually means the "
            "measurement is unavailable rather than zero"
        )
    return value


def _require_word_count(
    words: tuple[int, ...],
    expected: int,
    data_type: RegisterDataType,
) -> None:
    if len(words) != expected:
        raise RegisterDecoderError(
            f"{data_type.value} requires {expected} register word(s)"
        )


def _require_identifier(value: str, field_name: str) -> None:
    if not value.strip():
        raise RegisterDecoderError(f"{field_name} must be a non-empty identifier")


def _require_text(value: str, field_name: str) -> None:
    if not value.strip():
        raise RegisterDecoderError(f"{field_name} must be non-empty")


def _require_aware_datetime(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise RegisterDecoderError(f"{field_name} must be timezone-aware")


def _require_finite(value: float, field_name: str) -> None:
    if value != value or value in {float("inf"), float("-inf")}:
        raise RegisterDecoderError(f"{field_name} must be finite")
