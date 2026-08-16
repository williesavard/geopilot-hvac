"""Tests for the dashboard command line tool."""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from geopilot.dashboard import DeltaPair
from geopilot.domain import DataQuality, Measurement
from geopilot.sqlite_historian import SqliteMeasurementHistorian

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from geopilot_dashboard import (  # noqa: E402
    EXIT_OK,
    EXIT_USAGE,
    build_parser,
    main,
    parse_delta,
)

START = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)


def database_with(tmp_path: Path, *, samples: int = 60) -> Path:
    database = tmp_path / "geopilot.sqlite3"
    with SqliteMeasurementHistorian(database) as historian:
        for index in range(samples):
            moment = START + timedelta(minutes=index)
            historian.append(
                Measurement(
                    id=f"source_bus:sensor_loop_in:{index}",
                    sensor_id="sensor_loop_in",
                    observed_at=moment,
                    received_at=moment,
                    value=2.0 + index * 0.01,
                    unit="degC",
                    quality=DataQuality.GOOD,
                    source_id="source_bus",
                )
            )
    return database


def test_a_page_is_written(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    database = database_with(tmp_path)
    output = tmp_path / "page.html"

    exit_code = main(["--database", str(database), "--output", str(output)])

    assert exit_code == EXIT_OK
    assert output.read_text(encoding="utf-8").startswith("<!doctype html>")
    assert "wrote" in capsys.readouterr().out


def test_an_existing_file_is_not_replaced_by_accident(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A dashboard is cheap to regenerate; whatever was already there may not be."""

    database = database_with(tmp_path)
    output = tmp_path / "page.html"
    output.write_text("mine", encoding="utf-8")

    assert main(["--database", str(database), "--output", str(output)]) == EXIT_USAGE
    assert output.read_text(encoding="utf-8") == "mine"
    assert "--force" in capsys.readouterr().err


def test_force_replaces_it(tmp_path: Path) -> None:
    database = database_with(tmp_path)
    output = tmp_path / "page.html"
    output.write_text("mine", encoding="utf-8")

    assert main(["--database", str(database), "--output", str(output), "--force"]) == EXIT_OK
    assert output.read_text(encoding="utf-8") != "mine"


def test_a_missing_database_is_a_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(
        [
            "--database",
            str(tmp_path / "absent.sqlite3"),
            "--output",
            str(tmp_path / "page.html"),
        ]
    )

    assert exit_code == EXIT_USAGE
    assert "not found" in capsys.readouterr().err
    assert not (tmp_path / "page.html").exists()


def test_an_empty_database_is_a_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    database = tmp_path / "empty.sqlite3"
    with SqliteMeasurementHistorian(database):
        pass

    exit_code = main(
        ["--database", str(database), "--output", str(tmp_path / "page.html")]
    )

    assert exit_code == EXIT_USAGE
    assert "nothing to show" in capsys.readouterr().err


def test_a_delta_is_parsed_from_both_ends() -> None:
    assert parse_delta("a:b") == DeltaPair(sensor_id="a", minus="b")


def test_a_half_written_delta_is_refused() -> None:
    """Which way round a delta runs decides its sign; it is never guessed."""

    for value in ("a", "a:", ":b", ""):
        with pytest.raises(ValueError, match="SENSOR:MINUS"):
            parse_delta(value)


def test_an_unparsable_delta_is_a_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    database = database_with(tmp_path)

    exit_code = main(
        [
            "--database",
            str(database),
            "--output",
            str(tmp_path / "page.html"),
            "--delta",
            "sensor_loop_in",
        ]
    )

    assert exit_code == EXIT_USAGE
    assert "SENSOR:MINUS" in capsys.readouterr().err


def test_the_title_reaches_the_page(tmp_path: Path) -> None:
    database = database_with(tmp_path)
    output = tmp_path / "page.html"

    main(["--database", str(database), "--output", str(output), "--title", "Chez nous"])

    assert "<title>Chez nous</title>" in output.read_text(encoding="utf-8")


def test_both_paths_are_required() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--database", "x.sqlite3"])
