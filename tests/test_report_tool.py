"""Tests for the reporting command line tool.

The tool is what a person actually runs at three in the morning when they want
to know whether the recorder is still recording, so its exit codes are part of
its contract and are asserted here.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from geopilot.domain import DataQuality, Measurement
from geopilot.sqlite_historian import SqliteMeasurementHistorian

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from geopilot_report import (  # noqa: E402
    EXIT_NO_DATA,
    EXIT_OK,
    EXIT_USAGE,
    build_parser,
    format_duration,
    main,
    parse_interval,
    parse_moment,
)

START = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)


def database_with(
    tmp_path: Path,
    *,
    sensor_id: str = "sensor_loop_in",
    unit: str = "degC",
    values: tuple[float, ...] = (20.0,),
) -> Path:
    database = tmp_path / "geopilot.sqlite3"
    with SqliteMeasurementHistorian(database) as historian:
        for index, value in enumerate(values):
            moment = START + timedelta(minutes=index)
            historian.append(
                Measurement(
                    id=f"source_bus:{sensor_id}:{index}",
                    sensor_id=sensor_id,
                    observed_at=moment,
                    received_at=moment,
                    value=value,
                    unit=unit,
                    quality=DataQuality.GOOD,
                    source_id="source_bus",
                )
            )
    return database


def test_coverage_is_reported_by_default(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    database = database_with(tmp_path, values=(20.0, 21.0))

    assert main(["--database", str(database)]) == EXIT_OK

    output = capsys.readouterr().out
    assert "sensor_loop_in" in output
    assert "last observation" in output


def test_a_missing_database_is_a_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--database", str(tmp_path / "absent.sqlite3")]) == EXIT_USAGE
    assert "not found" in capsys.readouterr().err


def test_an_unparsable_window_is_a_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    database = database_with(tmp_path)

    assert main(["--database", str(database), "--since", "last tuesday"]) == EXIT_USAGE
    assert "--since" in capsys.readouterr().err


def test_an_empty_database_reports_no_data(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An empty database is not an error, but it is not success either."""

    database = database_with(tmp_path, values=())

    assert main(["--database", str(database)]) == EXIT_NO_DATA
    assert "no measurements" in capsys.readouterr().out


def test_a_sensor_summary_is_printed(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    database = database_with(tmp_path, values=(10.0, 20.0, 30.0))

    assert main(["--database", str(database), "--sensor", "sensor_loop_in"]) == EXIT_OK

    output = capsys.readouterr().out
    assert "min    : 10" in output
    assert "max    : 30" in output
    assert "mean   : 20" in output


def test_an_unknown_sensor_reports_no_data(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    database = database_with(tmp_path)

    assert main(["--database", str(database), "--sensor", "sensor_absent"]) == EXIT_NO_DATA
    assert "no measurements for sensor_absent" in capsys.readouterr().out


def test_a_state_sensor_also_reports_its_duty_cycle(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    database = database_with(
        tmp_path,
        sensor_id="sensor_zone_1",
        unit="state",
        values=(1, 0, 1, 1),
    )

    assert main(["--database", str(database), "--sensor", "sensor_zone_1"]) == EXIT_OK

    output = capsys.readouterr().out
    assert "asserted in 75.0% of samples" in output
    assert "not of time" in output


def test_a_temperature_sensor_reports_no_duty_cycle(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    database = database_with(tmp_path)

    main(["--database", str(database), "--sensor", "sensor_loop_in"])

    assert "asserted" not in capsys.readouterr().out


def test_a_sensor_recorded_in_two_units_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    database = tmp_path / "geopilot.sqlite3"
    with SqliteMeasurementHistorian(database) as historian:
        for index, unit in enumerate(("degC", "degF")):
            moment = START + timedelta(minutes=index)
            historian.append(
                Measurement(
                    id=f"source_bus:sensor_loop_in:{index}",
                    sensor_id="sensor_loop_in",
                    observed_at=moment,
                    received_at=moment,
                    value=20.0,
                    unit=unit,
                    quality=DataQuality.GOOD,
                    source_id="source_bus",
                )
            )

    assert main(["--database", str(database), "--sensor", "sensor_loop_in"]) == EXIT_USAGE
    assert "different units" in capsys.readouterr().err


def test_a_window_without_an_offset_is_read_as_utc() -> None:
    """A naive input is assumed UTC rather than silently taking the host zone."""

    assert parse_moment("2026-01-01", "--since") == START


def test_an_explicit_offset_is_preserved() -> None:
    moment = parse_moment("2026-01-01T00:00:00-05:00", "--since")

    assert moment is not None
    assert moment.utcoffset() == timedelta(hours=-5)


def test_buckets_are_printed_as_a_table(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    database = database_with(tmp_path, values=(10.0, 20.0, 30.0))

    exit_code = main(
        ["--database", str(database), "--sensor", "sensor_loop_in", "--bucket", "1h", "--utc"]
    )

    output = capsys.readouterr().out
    assert exit_code == EXIT_OK
    assert "2026-01-01T00:00:00+00:00" in output
    assert "an absent interval is a gap, not a zero" in output


def test_buckets_can_be_written_as_csv(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    database = database_with(tmp_path, values=(10.0, 20.0, 30.0))

    exit_code = main(
        [
            "--database",
            str(database),
            "--sensor",
            "sensor_loop_in",
            "--bucket",
            "1h",
            "--utc",
            "--csv",
        ]
    )

    lines = capsys.readouterr().out.splitlines()
    assert exit_code == EXIT_OK
    assert lines[0] == "starts_at,count,min,max,mean"
    assert lines[1] == "2026-01-01T00:00:00+00:00,3,10.0,30.0,20.0"


def test_bucketing_without_a_sensor_is_a_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    database = database_with(tmp_path)

    assert main(["--database", str(database), "--bucket", "1h"]) == EXIT_USAGE
    assert "--bucket needs --sensor" in capsys.readouterr().err


def test_an_unusable_interval_is_a_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    database = database_with(tmp_path)

    exit_code = main(
        ["--database", str(database), "--sensor", "sensor_loop_in", "--bucket", "7h"]
    )

    assert exit_code == EXIT_USAGE
    assert "drift" in capsys.readouterr().err


def test_bucketing_an_unknown_sensor_reports_no_data(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    database = database_with(tmp_path)

    exit_code = main(
        ["--database", str(database), "--sensor", "sensor_absent", "--bucket", "1h"]
    )

    assert exit_code == EXIT_NO_DATA
    assert "no measurements for sensor_absent" in capsys.readouterr().out


def loop_database(tmp_path: Path, *, lag_seconds: int = 3) -> Path:
    """Loop-in and loop-out, read seconds apart, delta of exactly 3 degrees."""

    database = tmp_path / "loop.sqlite3"
    with SqliteMeasurementHistorian(database) as historian:
        for index in range(3):
            moment = START + timedelta(minutes=index)
            for sensor_id, value, offset in (
                ("sensor_loop_in", 2.0, timedelta()),
                ("sensor_loop_out", -1.0, timedelta(seconds=lag_seconds)),
            ):
                stamped = moment + offset
                historian.append(
                    Measurement(
                        id=f"source_bus:{sensor_id}:{index}",
                        sensor_id=sensor_id,
                        observed_at=stamped,
                        received_at=stamped,
                        value=value,
                        unit="degC",
                        quality=DataQuality.GOOD,
                        source_id="source_bus",
                    )
                )
    return database


def test_a_delta_is_printed(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    database = loop_database(tmp_path)

    exit_code = main(
        [
            "--database",
            str(database),
            "--sensor",
            "sensor_loop_in",
            "--minus",
            "sensor_loop_out",
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == EXIT_OK
    assert "delta  : sensor_loop_in minus sensor_loop_out" in output
    assert "pairs  : 3" in output
    assert "mean   : 3" in output
    assert "unpaired" not in output


def test_unpaired_readings_are_surfaced(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Three readings each, but only the first pair is inside a 5-second reach."""

    database = tmp_path / "ragged.sqlite3"
    lags = (timedelta(seconds=2), timedelta(seconds=40), timedelta(seconds=40))
    with SqliteMeasurementHistorian(database) as historian:
        for index, lag in enumerate(lags):
            moment = START + timedelta(minutes=index)
            for sensor_id, value, offset in (
                ("sensor_loop_in", 2.0, timedelta()),
                ("sensor_loop_out", -1.0, lag),
            ):
                stamped = moment + offset
                historian.append(
                    Measurement(
                        id=f"source_bus:{sensor_id}:{index}",
                        sensor_id=sensor_id,
                        observed_at=stamped,
                        received_at=stamped,
                        value=value,
                        unit="degC",
                        quality=DataQuality.GOOD,
                        source_id="source_bus",
                    )
                )

    exit_code = main(
        [
            "--database",
            str(database),
            "--sensor",
            "sensor_loop_in",
            "--minus",
            "sensor_loop_out",
            "--tolerance",
            "5s",
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == EXIT_OK
    assert "pairs  : 1" in output
    assert "unpaired: 2 of sensor_loop_in, 2 of sensor_loop_out" in output


def test_no_pair_at_all_reports_no_data(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    database = loop_database(tmp_path, lag_seconds=20)

    exit_code = main(
        [
            "--database",
            str(database),
            "--sensor",
            "sensor_loop_in",
            "--minus",
            "sensor_loop_out",
            "--tolerance",
            "5s",
        ]
    )

    assert exit_code == EXIT_NO_DATA
    assert "no paired readings" in capsys.readouterr().out


def test_a_delta_can_be_bucketed(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    database = loop_database(tmp_path)

    exit_code = main(
        [
            "--database",
            str(database),
            "--sensor",
            "sensor_loop_in",
            "--minus",
            "sensor_loop_out",
            "--bucket",
            "1h",
            "--utc",
            "--csv",
        ]
    )

    lines = capsys.readouterr().out.splitlines()
    assert exit_code == EXIT_OK
    assert lines[1] == "2026-01-01T00:00:00+00:00,3,3.0,3.0,3.0"


def test_a_delta_without_a_sensor_is_a_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    database = loop_database(tmp_path)

    exit_code = main(["--database", str(database), "--minus", "sensor_loop_out"])

    assert exit_code == EXIT_USAGE
    assert "--minus needs --sensor" in capsys.readouterr().err


def test_comparing_incompatible_sensors_is_a_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    database = tmp_path / "mixed.sqlite3"
    with SqliteMeasurementHistorian(database) as historian:
        for index, (sensor_id, value, unit) in enumerate(
            (("sensor_loop_in", 2.0, "degC"), ("sensor_zone_1", 1, "state"))
        ):
            moment = START + timedelta(seconds=index)
            historian.append(
                Measurement(
                    id=f"source_bus:{sensor_id}:{index}",
                    sensor_id=sensor_id,
                    observed_at=moment,
                    received_at=moment,
                    value=value,
                    unit=unit,
                    quality=DataQuality.GOOD,
                    source_id="source_bus",
                )
            )

    exit_code = main(
        ["--database", str(database), "--sensor", "sensor_loop_in", "--minus", "sensor_zone_1"]
    )

    assert exit_code == EXIT_USAGE
    assert "not recorded in the same unit" in capsys.readouterr().err


def test_intervals_are_parsed_from_their_unit() -> None:
    assert parse_interval("30s") == timedelta(seconds=30)
    assert parse_interval("15m") == timedelta(minutes=15)
    assert parse_interval("6h") == timedelta(hours=6)
    assert parse_interval("7d") == timedelta(days=7)


def test_a_bare_number_is_refused_rather_than_guessed() -> None:
    """`--bucket 60` could mean a minute or an hour. Guessing would be silent."""

    with pytest.raises(ValueError, match="needs a unit"):
        parse_interval("60")


def test_a_non_numeric_interval_is_refused() -> None:
    with pytest.raises(ValueError, match="whole number"):
        parse_interval("1.5h")


def test_the_database_argument_is_required() -> None:
    """There is no default path, so a report is never produced about the wrong file."""

    with pytest.raises(SystemExit):
        build_parser().parse_args([])


def test_durations_are_rendered_in_readable_units() -> None:
    assert format_duration(timedelta(seconds=45)) == "45s"
    assert format_duration(timedelta(minutes=2, seconds=5)) == "2m 5s"
    assert format_duration(timedelta(hours=3, minutes=7)) == "3h 7m"
    assert format_duration(timedelta(days=4, hours=2)) == "4d 2h"
