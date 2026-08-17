"""Ask the hardware to answer right now.

Connectivity infers what is connected from the recording, which makes it free
and makes it a minute stale. That is the wrong loop for somebody with a
screwdriver: strip, connect, wait, refresh, guess again.

A probe goes to the device instead. It records nothing, ingests nothing and
decides nothing — it asks, and it reports what came back, including what came
back wrong.

**1-Wire probing discovers.** It lists every DS18B20 the kernel can see, whether
or not the configuration mentions it, with each one's current reading. That is
the answer to the question every 1-Wire installation starts with: three
identical probes on one cable, and no way to tell which id is which. Warm one in
your hand, probe again, and the one that moved is the one you are holding.

**Modbus probing verifies.** There is nothing to discover: a device answers at an
address or it does not, and sweeping a bus looking for one is a different tool
with different risks. So it reads what the configuration already claims is there
and reports whether the claim holds.

Nothing here retries. A probe is a button press, and a person who sees "the bus
is busy" presses it again — which is more honest than a loop that hides how often
the port was unavailable.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from geopilot.configuration import (
    BitReadConfig,
    OneWireReadConfig,
    RegisterReadConfig,
)
from geopilot.modbus_transport import (
    ModbusBitReadRequest,
    ModbusBitTransport,
    ModbusReadRequest,
    ModbusTransport,
    ModbusTransportError,
)
from geopilot.onewire import (
    OneWireError,
    OneWireErrorCode,
    OneWireInventory,
)
from geopilot.register_decoder import RegisterDataType


class ProbeKind(StrEnum):
    """What sort of thing was asked."""

    ONEWIRE = "onewire"
    REGISTER = "register"
    BIT = "bit"


RESET_ADVICE = (
    "the probe answered with its 85 C power-on reset value, not a temperature: "
    "check the pull-up resistor and the supply"
)
"""What to do about a probe that is present and not ready.

The adapter already refuses to turn 85.000 C into a temperature, which is the
right call for the recording. For somebody holding a screwdriver, refusing is
only half an answer — the other half is that this particular failure is almost
always a data line without a proper pull-up, or parasite power that cannot
supply the conversion.
"""


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """One live reading attempt, successful or not."""

    kind: ProbeKind
    reference: str
    sensor_id: str
    value: float | None
    unit: str
    ok: bool
    configured: bool
    suspect: bool
    detail: str

    # `ok` means a usable value came back. `suspect` means the device answered in
    # a way that points at a wiring or power fault rather than at silence, which
    # is a different thing to go and fix.

    @property
    def label(self) -> str:
        return self.sensor_id or self.reference


TransportFor = Callable[[str], ModbusTransport]
BitTransportFor = Callable[[str], ModbusBitTransport]


def probe_onewire(
    bus: OneWireInventory,
    reads: tuple[OneWireReadConfig, ...],
    *,
    family: str = "28",
) -> tuple[ProbeResult, ...]:
    """Read every probe on the bus, configured or not.

    The union matters in both directions: a device present but unconfigured is
    the id you still have to write down, and a device configured but absent is
    the one that is not plugged in.
    """

    discovered = tuple(bus.available_devices(family))
    by_device = {read.device_id: read for read in reads}
    known = tuple(read.device_id for read in reads)

    results = []
    for device_id in list(discovered) + [item for item in known if item not in discovered]:
        read = by_device.get(device_id)
        results.append(_probe_one_device(bus, device_id, read))
    return tuple(results)


def _probe_one_device(
    bus: OneWireInventory, device_id: str, read: OneWireReadConfig | None
) -> ProbeResult:
    sensor_id = read.sensor_id if read else ""
    unit = read.unit if read else "degC"
    offset = read.offset_celsius if read else 0.0

    try:
        reading = bus.read_temperature(device_id)
    except OneWireError as error:
        # A probe that is present but not ready is a different fault from a probe
        # that is absent, and it has a specific thing to go and check.
        reset = error.code is OneWireErrorCode.POWER_ON_RESET
        return ProbeResult(
            kind=ProbeKind.ONEWIRE,
            reference=device_id,
            sensor_id=sensor_id,
            value=None,
            unit=unit,
            ok=False,
            configured=read is not None,
            suspect=reset,
            detail=RESET_ADVICE if reset else str(error),
        )

    return ProbeResult(
        kind=ProbeKind.ONEWIRE,
        reference=device_id,
        sensor_id=sensor_id,
        value=reading.celsius + offset,
        unit=unit,
        ok=True,
        configured=read is not None,
        suspect=False,
        detail="" if read else "on the bus, not in the configuration",
    )


def probe_registers(
    transport_for: TransportFor,
    reads: tuple[RegisterReadConfig, ...],
) -> tuple[ProbeResult, ...]:
    """Read each configured register right now and decode it."""

    results = []
    for read in reads:
        reference = f"unit {read.unit_id}, {read.register_kind} {read.address}"
        try:
            response = transport_for(read.source_id).read_registers(
                ModbusReadRequest(
                    request_id=f"probe-{read.read_id}",
                    source_id=read.source_id,
                    unit_id=read.unit_id,
                    register_kind=read.register_kind,
                    address=read.address,
                    quantity=read.quantity,
                )
            )
        except (ModbusTransportError, OSError) as error:
            results.append(
                ProbeResult(
                    kind=ProbeKind.REGISTER,
                    reference=reference,
                    sensor_id=read.sensor_id,
                    value=None,
                    unit=read.unit,
                    ok=False,
                    configured=True,
                    suspect=False,
                    detail=str(error),
                )
            )
            continue

        words = tuple(int(word) for word in response.words)
        value = _decode(words, read)
        results.append(
            ProbeResult(
                kind=ProbeKind.REGISTER,
                reference=reference,
                sensor_id=read.sensor_id,
                value=value,
                unit=read.unit,
                ok=value is not None,
                configured=True,
                suspect=False,
                detail=(
                    f"raw {' '.join(f'0x{word:04X}' for word in words)}"
                    if value is not None
                    else f"{read.quantity} word(s) cannot be decoded as {read.data_type}"
                ),
            )
        )
    return tuple(results)


def _decode(words: tuple[int, ...], read: RegisterReadConfig) -> float | None:
    """Apply the configured data type, scale and offset.

    Returns None rather than guessing when the words do not fit the declared
    type — a wrong quantity in the configuration is exactly the mistake a probe
    should surface, not paper over.
    """

    if len(words) != 1:
        return None
    raw = words[0]
    if read.data_type is RegisterDataType.INT16 and raw > 0x7FFF:
        raw -= 0x10000
    return raw * read.scale + read.offset


def probe_bits(
    transport_for: BitTransportFor,
    reads: tuple[BitReadConfig, ...],
) -> tuple[ProbeResult, ...]:
    """Read each configured discrete input or coil right now.

    Inversion is applied here exactly as the runtime applies it, so a probe and a
    recorded reading agree about what "asserted" means.
    """

    results = []
    for read in reads:
        reference = f"unit {read.unit_id}, {read.bit_kind} {read.address}"
        try:
            response = transport_for(read.source_id).read_bits(
                ModbusBitReadRequest(
                    request_id=f"probe-{read.read_id}",
                    source_id=read.source_id,
                    unit_id=read.unit_id,
                    bit_kind=read.bit_kind,
                    address=read.address,
                    quantity=1,
                )
            )
        except (ModbusTransportError, OSError) as error:
            results.append(
                ProbeResult(
                    kind=ProbeKind.BIT,
                    reference=reference,
                    sensor_id=read.sensor_id,
                    value=None,
                    unit="state",
                    ok=False,
                    configured=True,
                    suspect=False,
                    detail=str(error),
                )
            )
            continue

        asserted = response.bits[0] != read.inverted
        results.append(
            ProbeResult(
                kind=ProbeKind.BIT,
                reference=reference,
                sensor_id=read.sensor_id,
                value=float(int(asserted)),
                unit="state",
                ok=True,
                configured=True,
                suspect=False,
                detail="inverted in configuration" if read.inverted else "",
            )
        )
    return tuple(results)
