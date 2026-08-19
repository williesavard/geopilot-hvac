"""What was in effect, and when.

Every stored measurement has already been corrected. A DS18B20 reading has its
`offset_celsius` added before ingestion, a register has its `scale` and `offset`
applied, an active-low contact has been un-inverted. The database keeps the
result and says nothing about the correction, which is fine right up until the
correction changes.

Then it is not fine at all. Three ways a year of recording quietly stops meaning
one thing:

- **a recalibration.** Probes are re-run in a bath in January and the offsets
  move by 0.2 °C. December's loop delta and February's are now on different
  scales, and a step in the graph is either the heat pump degrading or the
  calibration moving — indistinguishable;
- **a swapped probe.** DS18B20 device ids are 64-bit hex on identical cables. If
  loop entry and loop exit trade places, the delta reverses sign and nothing
  says so;
- **a corrected `inverted` flag.** Every cycle count before the correction meant
  the opposite of every cycle count after it.

None of these can be reconstructed afterwards. The configuration file is edited
in place and is not in version control — deliberately, since it describes a
specific residence — so "I did not change anything" is the only available
evidence, and it is not evidence.

This module makes the correction part of the record. It captures what each
sensor's value is derived from, fingerprints it, and — with
`sqlite_provenance` — stores an epoch whenever the fingerprint moves. A report
can then say **which corrections were in effect for the window it covers**, and
an engineer reading a year of loop temperatures can tell a real change from a
bookkeeping one.

What is deliberately not here: this records the configuration, not the truth. A
probe wired to the wrong pipe is recorded faithfully as being wired where the
configuration says. Provenance narrows "the numbers changed" to "the numbers
changed and nothing in the configuration did", which is the useful half.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum

from geopilot.configuration import InstallationConfig


class ProvenanceKind(StrEnum):
    """How a sensor's value is obtained."""

    ONEWIRE = "onewire"
    REGISTER = "register"
    BIT = "bit"


@dataclass(frozen=True, slots=True)
class SensorProvenance:
    """One sensor's derivation: the physical thing, and the arithmetic.

    The fields are exactly those that change what a stored value *means*. A
    description or a poll interval does not appear, because editing one does not
    make yesterday's readings incomparable with today's.
    """

    sensor_id: str
    kind: ProvenanceKind
    reference: str
    """The physical origin: a 1-Wire device id, or `unit:kind:address`."""

    unit: str
    scale: float = 1.0
    offset: float = 0.0
    """What is added to the raw reading. `offset_celsius` for a probe."""

    inverted: bool = False
    """Discrete inputs only: whether a stored 1 came from a low signal."""

    def as_row(self) -> tuple[str, str, str, str, float, float, int]:
        """Storage order, and the order the fingerprint is taken over."""

        return (
            self.sensor_id,
            str(self.kind),
            self.reference,
            self.unit,
            self.scale,
            self.offset,
            int(self.inverted),
        )

    def describe(self) -> str:
        """A person-readable summary of the correction, for reports."""

        parts = [f"from {self.reference}"]
        if self.scale != 1.0:
            parts.append(f"×{self.scale:g}")
        if self.offset:
            parts.append(f"{self.offset:+g}")
        if self.inverted:
            parts.append("inverted")
        return ", ".join(parts)


@dataclass(frozen=True, slots=True)
class ProvenanceChange:
    """One field of one sensor, before and after.

    The useful question is never "did the configuration change" but "did the
    thing I am looking at change", so a change is reported per sensor and per
    field rather than as a new fingerprint.
    """

    sensor_id: str
    field: str
    before: str | None
    after: str | None

    def describe(self) -> str:
        if self.before is None:
            return f"{self.sensor_id}: added ({self.field} {self.after})"
        if self.after is None:
            return f"{self.sensor_id}: removed (was {self.field} {self.before})"
        return f"{self.sensor_id}: {self.field} {self.before} → {self.after}"


_COMPARED_FIELDS = ("kind", "reference", "unit", "scale", "offset", "inverted")


def provenance_from(config: InstallationConfig) -> tuple[SensorProvenance, ...]:
    """Derive every sensor's provenance from a loaded configuration.

    Sorted, so two loads of the same file always fingerprint identically.
    """

    entries: list[SensorProvenance] = []

    for probe in config.onewire_reads:
        entries.append(
            SensorProvenance(
                sensor_id=probe.sensor_id,
                kind=ProvenanceKind.ONEWIRE,
                reference=probe.device_id,
                unit=probe.unit,
                offset=probe.offset_celsius,
            )
        )

    for register in config.reads:
        entries.append(
            SensorProvenance(
                sensor_id=register.sensor_id,
                kind=ProvenanceKind.REGISTER,
                reference=(
                    f"{register.unit_id}:{register.register_kind}:{register.address}"
                ),
                unit=register.unit,
                scale=register.scale,
                offset=register.offset,
            )
        )

    for bit in config.bit_reads:
        entries.append(
            SensorProvenance(
                sensor_id=bit.sensor_id,
                kind=ProvenanceKind.BIT,
                reference=f"{bit.unit_id}:{bit.bit_kind}:{bit.address}",
                unit="state",
                inverted=bit.inverted,
            )
        )

    return tuple(sorted(entries, key=lambda entry: (entry.sensor_id, str(entry.kind))))


def fingerprint(sensors: tuple[SensorProvenance, ...]) -> str:
    """A stable digest of everything that affects a stored value.

    SHA-256 over a canonical JSON encoding, so the same configuration always
    produces the same digest and any change to a correction produces a different
    one. Stored in full; reports abbreviate it for reading.
    """

    canonical = json.dumps(
        [list(entry.as_row()) for entry in sorted(sensors, key=lambda e: e.as_row())],
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compare(
    before: tuple[SensorProvenance, ...],
    after: tuple[SensorProvenance, ...],
) -> tuple[ProvenanceChange, ...]:
    """Every field that differs between two configurations, sensor by sensor."""

    old = {entry.sensor_id: entry for entry in before}
    new = {entry.sensor_id: entry for entry in after}
    changes: list[ProvenanceChange] = []

    for sensor_id in sorted(old.keys() | new.keys()):
        previous = old.get(sensor_id)
        current = new.get(sensor_id)

        if previous is None:
            assert current is not None
            changes.append(
                ProvenanceChange(sensor_id, "source", None, current.describe())
            )
            continue
        if current is None:
            changes.append(
                ProvenanceChange(sensor_id, "source", previous.describe(), None)
            )
            continue

        for field in _COMPARED_FIELDS:
            was = getattr(previous, field)
            now = getattr(current, field)
            if was != now:
                changes.append(
                    ProvenanceChange(sensor_id, field, _render(was), _render(now))
                )

    return tuple(changes)


def _render(value: object) -> str:
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)
