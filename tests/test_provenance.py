"""Provenance tests.

Each of the first three tests is one of the ways a year of recording quietly
stops meaning one thing: a recalibration, a swapped probe, a corrected polarity
flag. The point of the journal is that an engineer can tell those apart from a
heat pump actually changing behaviour, so that is what is asserted.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from geopilot.configuration import CONFIGURATION_VERSION, parse_configuration
from geopilot.provenance import (
    ProvenanceKind,
    SensorProvenance,
    compare,
    fingerprint,
    provenance_from,
)
from geopilot.sqlite_provenance import (
    ProvenanceStorageError,
    SqliteProvenanceJournal,
    provenance_path,
)

SEPTEMBER = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)
STAMP = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)


def installation() -> dict[str, Any]:
    """A configuration exercising all three ways a value is corrected."""

    return {
        "version": CONFIGURATION_VERSION,
        "storage": {"database": ":memory:"},
        "residence": {
            "id": "residence_home",
            "name": "Home",
            "timezone": "America/Toronto",
        },
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
                "id": name,
                "equipment_id": "equipment_hp",
                "name": name,
                "measurement_kind": kind,
                "sensor_kind": kind,
                "unit": unit,
                "source_id": source,
            }
            for name, kind, unit, source in (
                ("sensor_loop_in", "temperature", "degC", "source_probes"),
                ("sensor_supply_air", "temperature", "degC", "source_bus"),
                ("sensor_compressor", "state", "state", "source_bus"),
            )
        ],
        "source": [{"id": "source_bus", "port": "/dev/cu.fake"}],
        "onewire_source": [{"id": "source_probes", "root": "/sys/bus/w1/devices"}],
        "onewire_read": [
            {
                "id": "read_loop_in",
                "source_id": "source_probes",
                "sensor_id": "sensor_loop_in",
                "device_id": "28-000005e2fdc3",
                "unit": "degC",
                "offset_celsius": 0.31,
                "source_reference": "bath calibration 2026-08-18",
            }
        ],
        "read": [
            {
                "id": "read_supply_air",
                "source_id": "source_bus",
                "sensor_id": "sensor_supply_air",
                "unit_id": 1,
                "register": "input",
                "address": 1,
                "data_type": "int16",
                "unit": "degC",
                "scale": 0.1,
                "source_reference": "XY-MD02 manual page 4",
            }
        ],
        "bit_read": [
            {
                "id": "read_compressor",
                "source_id": "source_bus",
                "sensor_id": "sensor_compressor",
                "unit_id": 2,
                "bit": "discrete_input",
                "address": 0,
                "inverted": True,
                "source_reference": "relay panel mapping",
            }
        ],
    }


def test_every_correction_in_a_configuration_is_captured() -> None:
    """The three arithmetic corrections a stored value can carry — a probe
    offset, a register scale, a polarity flip — must all reach the record, or
    the epoch understates what changed."""

    derived = provenance_from(parse_configuration(installation(), created_at=STAMP))

    by_id = {entry.sensor_id: entry for entry in derived}
    assert set(by_id) == {"sensor_loop_in", "sensor_supply_air", "sensor_compressor"}

    assert by_id["sensor_loop_in"].kind is ProvenanceKind.ONEWIRE
    assert by_id["sensor_loop_in"].reference == "28-000005e2fdc3"
    assert by_id["sensor_loop_in"].offset == 0.31

    assert by_id["sensor_supply_air"].kind is ProvenanceKind.REGISTER
    assert by_id["sensor_supply_air"].reference == "1:input:1"
    assert by_id["sensor_supply_air"].scale == 0.1

    assert by_id["sensor_compressor"].kind is ProvenanceKind.BIT
    assert by_id["sensor_compressor"].inverted is True


def test_the_same_configuration_always_fingerprints_the_same() -> None:
    """Two loads of one file must agree, or every restart looks like a change."""

    document = installation()
    first = provenance_from(parse_configuration(document, created_at=STAMP))
    second = provenance_from(parse_configuration(document, created_at=STAMP))

    assert fingerprint(first) == fingerprint(second)


def probe(
    sensor_id: str = "sensor_loop_in",
    *,
    device: str = "28-000005e2fdc3",
    offset: float = 0.0,
) -> SensorProvenance:
    return SensorProvenance(
        sensor_id=sensor_id,
        kind=ProvenanceKind.ONEWIRE,
        reference=device,
        unit="degC",
        offset=offset,
    )


def loop() -> tuple[SensorProvenance, ...]:
    return (
        probe("sensor_loop_in", device="28-aaaa", offset=0.31),
        probe("sensor_loop_out", device="28-bbbb", offset=-0.12),
    )


# --- The three ways a series stops being comparable ---------------------------


def test_a_recalibration_is_visible_as_a_change(tmp_path: Path) -> None:
    """December's loop delta and February's are on different scales, and the
    journal is the only thing that can say so."""

    journal = SqliteProvenanceJournal(tmp_path / "p.sqlite3")
    journal.record(loop(), at=SEPTEMBER)

    recalibrated = (
        probe("sensor_loop_in", device="28-aaaa", offset=0.44),
        probe("sensor_loop_out", device="28-bbbb", offset=-0.12),
    )
    january = SEPTEMBER + timedelta(days=120)
    assert journal.record(recalibrated, at=january) is not None

    changed = journal.changes_between(SEPTEMBER, january + timedelta(days=1))

    assert len(changed) == 1
    epoch, changes = changed[0]
    assert epoch.recorded_at == january
    assert [change.describe() for change in changes] == [
        "sensor_loop_in: offset 0.31 → 0.44"
    ]
    journal.close()


def test_two_swapped_probes_are_visible(tmp_path: Path) -> None:
    """Device ids are 64-bit hex on identical cables. Swapping loop entry and
    loop exit reverses the delta's sign and changes nothing else."""

    journal = SqliteProvenanceJournal(tmp_path / "p.sqlite3")
    journal.record(loop(), at=SEPTEMBER)

    swapped = (
        probe("sensor_loop_in", device="28-bbbb", offset=-0.12),
        probe("sensor_loop_out", device="28-aaaa", offset=0.31),
    )
    later = SEPTEMBER + timedelta(days=30)
    journal.record(swapped, at=later)

    _, changes = journal.changes_between(SEPTEMBER, later + timedelta(days=1))[0]

    assert {change.sensor_id for change in changes} == {
        "sensor_loop_in",
        "sensor_loop_out",
    }
    assert {change.field for change in changes} == {"reference", "offset"}
    journal.close()


def test_a_corrected_polarity_flag_is_visible(tmp_path: Path) -> None:
    """Every cycle count before the correction meant the opposite of every one
    after it."""

    before = (
        SensorProvenance(
            "sensor_compressor", ProvenanceKind.BIT, "1:discrete_input:0", "state"
        ),
    )
    after = (
        SensorProvenance(
            "sensor_compressor",
            ProvenanceKind.BIT,
            "1:discrete_input:0",
            "state",
            inverted=True,
        ),
    )

    journal = SqliteProvenanceJournal(tmp_path / "p.sqlite3")
    journal.record(before, at=SEPTEMBER)
    journal.record(after, at=SEPTEMBER + timedelta(days=2))

    _, changes = journal.changes_between(SEPTEMBER, SEPTEMBER + timedelta(days=3))[0]

    assert [change.describe() for change in changes] == [
        "sensor_compressor: inverted False → True"
    ]
    journal.close()


# --- Recording behaviour ------------------------------------------------------


def test_an_unchanged_configuration_records_nothing(tmp_path: Path) -> None:
    """This is called every time the recorder starts, which on a timer is once
    a minute for a year. It must not write a row unless something moved."""

    journal = SqliteProvenanceJournal(tmp_path / "p.sqlite3")

    assert journal.record(loop(), at=SEPTEMBER) is not None
    for minute in range(1, 6):
        assert journal.record(loop(), at=SEPTEMBER + timedelta(minutes=minute)) is None

    assert journal.count() == 1
    journal.close()


def test_the_fingerprint_ignores_ordering(tmp_path: Path) -> None:
    """Two loads of the same file must agree, whatever order the reads came in."""

    forward = loop()
    assert fingerprint(forward) == fingerprint(tuple(reversed(forward)))


def test_a_naive_timestamp_is_refused(tmp_path: Path) -> None:
    """An epoch boundary has to be readable as the wall clock somebody edited a
    file on, which a naive datetime cannot express."""

    journal = SqliteProvenanceJournal(tmp_path / "p.sqlite3")

    with pytest.raises(ProvenanceStorageError, match="aware datetime"):
        journal.record(loop(), at=datetime(2026, 9, 1, 8, 0))

    journal.close()


# --- Querying -----------------------------------------------------------------


def test_the_epoch_in_effect_is_the_one_before_the_moment(tmp_path: Path) -> None:
    journal = SqliteProvenanceJournal(tmp_path / "p.sqlite3")
    journal.record(loop(), at=SEPTEMBER)
    second = (probe("sensor_loop_in", device="28-aaaa", offset=0.5),)
    journal.record(second, at=SEPTEMBER + timedelta(days=10))

    early = journal.at(SEPTEMBER + timedelta(days=5))
    late = journal.at(SEPTEMBER + timedelta(days=15))

    assert early is not None and late is not None
    assert early.sensor("sensor_loop_in") == probe(
        "sensor_loop_in", device="28-aaaa", offset=0.31
    )
    assert late.sensor("sensor_loop_in") == probe(
        "sensor_loop_in", device="28-aaaa", offset=0.5
    )
    journal.close()


def test_a_recording_older_than_the_journal_says_so(tmp_path: Path) -> None:
    """A database written before this journal existed has no epoch, and guessing
    the configuration backwards would be inventing evidence."""

    journal = SqliteProvenanceJournal(tmp_path / "p.sqlite3")
    journal.record(loop(), at=SEPTEMBER)

    assert journal.at(SEPTEMBER - timedelta(days=1)) is None
    journal.close()


def test_a_window_carries_the_epoch_that_opened_it(tmp_path: Path) -> None:
    """Corrections set months earlier are still the corrections in effect."""

    journal = SqliteProvenanceJournal(tmp_path / "p.sqlite3")
    journal.record(loop(), at=SEPTEMBER)

    spanning = journal.spanning(
        SEPTEMBER + timedelta(days=100), SEPTEMBER + timedelta(days=130)
    )

    assert len(spanning) == 1
    assert spanning[0].recorded_at == SEPTEMBER
    journal.close()


def test_added_and_removed_sensors_are_reported() -> None:
    before = (probe("sensor_loop_in"),)
    after = (probe("sensor_loop_in"), probe("sensor_tank", device="28-cccc"))

    added = compare(before, after)
    removed = compare(after, before)

    assert [change.describe() for change in added] == [
        "sensor_tank: added (source from 28-cccc)"
    ]
    assert [change.describe() for change in removed] == [
        "sensor_tank: removed (was source from 28-cccc)"
    ]


# --- Wiring -------------------------------------------------------------------


def test_an_in_memory_database_gets_an_in_memory_journal() -> None:
    """A library that writes provenance.sqlite3 into whatever directory the
    process started in is a library people stop trusting with paths."""

    assert provenance_path(":memory:") == ":memory:"
    assert provenance_path("/var/lib/geopilot/db.sqlite3") == (
        "/var/lib/geopilot/provenance.sqlite3"
    )
