"""Dossier tests.

The dossier is the only GeoPilot output that leaves the machine and is read by
somebody who was not there. Two things therefore matter more than the CSV
formatting: that it never overstates what the data supports, and that it never
carries anything about the household off the machine.

Both are asserted below, alongside the ordinary "does it write the files".
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from geopilot.domain import DataQuality, Measurement
from geopilot.provenance import ProvenanceKind, SensorProvenance
from geopilot.sqlite_historian import SqliteMeasurementHistorian
from geopilot.sqlite_provenance import SqliteProvenanceJournal, provenance_path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from geopilot_dossier import (  # noqa: E402
    EXIT_NO_DATA,
    EXIT_OK,
    EXIT_USAGE,
    format_duration,
    main,
    parse_interval,
    parse_pair,
)

START = datetime(2026, 10, 1, tzinfo=UTC)


def recording(tmp_path: Path, *, hours: int = 48, gap: range | None = None) -> Path:
    """A recording of two probes, optionally with a hole in it."""

    database = tmp_path / "geopilot.sqlite3"
    with SqliteMeasurementHistorian(database) as historian:
        for hour in range(hours):
            if gap is not None and hour in gap:
                continue
            moment = START + timedelta(hours=hour)
            for sensor, base in (("sensor_loop_in", 6.0), ("sensor_loop_out", 3.2)):
                historian.append(
                    Measurement(
                        id=f"{sensor}-{hour}",
                        sensor_id=sensor,
                        observed_at=moment,
                        received_at=moment,
                        value=base,
                        unit="degC",
                        quality=DataQuality.GOOD,
                        source_id="source_probes",
                    )
                )
    return database


def calibrated(database: Path, *, recalibrate: bool = False) -> None:
    def probes(offset: float) -> tuple[SensorProvenance, ...]:
        return (
            SensorProvenance(
                "sensor_loop_in", ProvenanceKind.ONEWIRE, "28-aaaa", "degC", offset=offset
            ),
            SensorProvenance(
                "sensor_loop_out", ProvenanceKind.ONEWIRE, "28-bbbb", "degC", offset=-0.12
            ),
        )

    journal = SqliteProvenanceJournal(provenance_path(database))
    journal.record(probes(0.31), at=START - timedelta(days=1))
    if recalibrate:
        journal.record(probes(0.44), at=START + timedelta(hours=24))
    journal.close()


def build(tmp_path: Path, *extra: str, database: Path | None = None) -> tuple[int, Path]:
    source = database if database is not None else recording(tmp_path)
    into = tmp_path / "dossier"
    code = main(["--database", str(source), "--into", str(into), *extra])
    return code, into


# --- It must not overstate what the data supports ------------------------------


def test_the_limits_are_always_present(tmp_path: Path) -> None:
    """A dossier that omits its own limits is worse than no dossier: it invites
    a conclusion it cannot support."""

    code, into = build(tmp_path)
    readme = (into / "README.md").read_text(encoding="utf-8")

    assert code == EXIT_OK
    assert "±0.5 °C absolute" in readme
    assert "no flow measurement" in readme
    assert "records the configuration, not the truth" in readme
    assert "Gaps are absences, not zeros" in readme
    # And the reader is sent there before the numbers, not after.
    assert readme.index("Read [Limits]") < readme.index("## What was measured")


def test_a_recalibration_is_named_and_dated(tmp_path: Path) -> None:
    """The one thing that would silently invalidate a comparison across the
    season has to be on the page, not in an appendix CSV."""

    database = recording(tmp_path, hours=48)
    calibrated(database, recalibrate=True)

    code, into = build(tmp_path, database=database)
    readme = (into / "README.md").read_text(encoding="utf-8")

    assert code == EXIT_OK
    assert "Corrections changed during this recording" in readme
    assert "sensor_loop_in: offset 0.31 → 0.44" in readme
    assert "2026-10-02T00:00" in readme


def test_a_recording_with_no_calibration_history_says_so(tmp_path: Path) -> None:
    """Silence would let a reader assume the probes were calibrated."""

    code, into = build(tmp_path)
    readme = (into / "README.md").read_text(encoding="utf-8")

    assert code == EXIT_OK
    assert "No calibration history is available" in readme
    assert "comparisons between two sensors do not" in readme


def test_a_hole_is_called_a_hole(tmp_path: Path) -> None:
    database = recording(tmp_path, hours=24 * 8, gap=range(24, 24 * 4))

    code, into = build(tmp_path, database=database)
    readme = (into / "README.md").read_text(encoding="utf-8")

    assert code == EXIT_OK
    assert "**hole of 3d" in readme


# --- It must not carry the household off the machine ---------------------------


def test_nothing_about_the_residence_leaves_with_it(tmp_path: Path) -> None:
    """The dossier reads the measurement database, never the configuration, so
    forwarding it discloses readings and nothing about a household."""

    database = recording(tmp_path)
    calibrated(database)

    _, into = build(tmp_path, database=database)

    every_file = "\n".join(
        path.read_text(encoding="utf-8") for path in into.rglob("*") if path.is_file()
    )
    assert "No address" in every_file  # the promise is stated
    for forbidden in ("residence_", "timezone", "America/", "serial"):
        assert forbidden not in every_file.replace(
            "no equipment serial numbers", ""
        ), forbidden


# --- Ordinary behaviour --------------------------------------------------------


def test_it_writes_a_series_per_sensor_and_the_requested_delta(tmp_path: Path) -> None:
    code, into = build(tmp_path, "--delta", "sensor_loop_in:sensor_loop_out")

    assert code == EXIT_OK
    assert (into / "coverage.csv").is_file()
    assert (into / "provenance.csv").is_file()
    assert (into / "series" / "sensor_loop_in.csv").is_file()
    assert (into / "series" / "sensor_loop_out.csv").is_file()
    assert (into / "deltas" / "sensor_loop_in-minus-sensor_loop_out.csv").is_file()


def test_values_carry_no_floating_point_artefacts(tmp_path: Path) -> None:
    """`2.8000000000000003` in a deliverable claims sixteen significant digits
    from a probe whose resolution is 0.0625 degC."""

    code, into = build(tmp_path, "--delta", "sensor_loop_in:sensor_loop_out")
    written = (into / "deltas" / "sensor_loop_in-minus-sensor_loop_out.csv").read_text(
        encoding="utf-8"
    )

    assert code == EXIT_OK
    assert "2.8," in written
    assert "2.8000000000000003" not in written


def test_it_refuses_to_write_into_an_occupied_directory(tmp_path: Path) -> None:
    """A dossier is dated evidence; silently mixing two of them is how a reader
    ends up with January's README beside March's CSVs."""

    code, into = build(tmp_path)
    assert code == EXIT_OK

    again = main(["--database", str(recording(tmp_path)), "--into", str(into)])

    assert again == EXIT_USAGE


def test_force_writes_anyway(tmp_path: Path) -> None:
    code, into = build(tmp_path)
    assert code == EXIT_OK

    again = main(
        ["--database", str(recording(tmp_path)), "--into", str(into), "--force"]
    )

    assert again == EXIT_OK


def test_an_empty_database_produces_no_dossier(tmp_path: Path) -> None:
    """An evidence package with no evidence in it should not exist."""

    database = tmp_path / "empty.sqlite3"
    SqliteMeasurementHistorian(database).close()
    into = tmp_path / "dossier"

    assert main(["--database", str(database), "--into", str(into)]) == EXIT_NO_DATA
    assert not into.exists()


def test_a_backwards_window_is_a_usage_error(tmp_path: Path) -> None:
    code, _ = build(tmp_path, "--since", "2027-01-01", "--until", "2026-01-01")

    assert code == EXIT_USAGE


# --- Parsing -------------------------------------------------------------------


def test_a_bucket_without_a_unit_is_refused() -> None:
    with pytest.raises(ValueError, match="needs a unit"):
        parse_interval("60")


def test_a_delta_needs_both_ends() -> None:
    with pytest.raises(ValueError, match="SENSOR:MINUS"):
        parse_pair("sensor_loop_in")


@pytest.mark.parametrize(
    ("span", "rendered"),
    [
        (timedelta(hours=1), "1h"),
        (timedelta(hours=1, minutes=30), "1h 30m"),
        (timedelta(days=3), "3d"),
        (timedelta(days=3, hours=1), "3d 1h"),
    ],
)
def test_durations_read_the_way_a_person_says_them(
    span: timedelta, rendered: str
) -> None:
    assert format_duration(span) == rendered
