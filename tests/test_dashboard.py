"""Dashboard rendering tests.

The page is a single file that has to work with no network, so what is asserted
here is mostly what is *absent*: no external references, no live-fetching, no
claim the data does not support.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from geopilot.dashboard import DeltaPair, render
from geopilot.domain import DataQuality, Measurement
from geopilot.reporting import ReportingError, open_readonly
from geopilot.sqlite_historian import SqliteMeasurementHistorian

START = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)


def recorded(
    tmp_path: Path,
    *,
    samples: int = 120,
    with_state: bool = True,
    tzinfo: timezone = UTC,
) -> sqlite3.Connection:
    database = tmp_path / "geopilot.sqlite3"
    origin = START.astimezone(tzinfo)

    with SqliteMeasurementHistorian(database) as historian:
        for index in range(samples):
            moment = origin + timedelta(minutes=index)
            rows = [
                ("sensor_loop_in", 2.0 + index * 0.01, "degC", 0),
                ("sensor_loop_out", -1.0 + index * 0.01, "degC", 3),
            ]
            if with_state:
                rows.append(("sensor_compressor", index % 4 < 2, "state", 6))

            for sensor_id, value, unit, lag in rows:
                stamped = moment + timedelta(seconds=lag)
                historian.append(
                    Measurement(
                        id=f"source_bus:{sensor_id}:{index}",
                        sensor_id=sensor_id,
                        observed_at=stamped,
                        received_at=stamped,
                        value=int(value) if unit == "state" else value,
                        unit=unit,
                        quality=DataQuality.GOOD,
                        source_id="source_bus",
                    )
                )
    return open_readonly(database)


def embedded(page: str) -> dict[str, object]:
    match = re.search(r"window\.GEOPILOT=(\{.*?\});</script>", page, re.DOTALL)
    assert match is not None
    return dict(json.loads(match.group(1).replace("<\\/", "</")))


def test_the_page_reaches_for_nothing_outside_itself(tmp_path: Path) -> None:
    """It has to work from a USB stick and from an email attachment."""

    page = render(recorded(tmp_path))

    assert "<link" not in page
    assert "src=" not in page
    assert "href=" not in page
    assert "fetch(" not in page
    assert "XMLHttpRequest" not in page
    assert "import(" not in page

    # The one URL in the file is the SVG namespace, which names a dialect and
    # is never resolved. Anything else would be a request.
    urls = re.findall(r"https?://[^\"'\s)]+", page)
    assert set(urls) == {"http://www.w3.org/2000/svg"}


def test_the_styles_and_script_are_inlined(tmp_path: Path) -> None:
    page = render(recorded(tmp_path))

    assert "<style>" in page
    assert "--paper" in page
    assert "window.GEOPILOT" in page
    assert "getBoundingClientRect" in page


def test_every_sensor_appears_in_the_health_table(tmp_path: Path) -> None:
    page = render(recorded(tmp_path))

    assert "Is it still recording?" in page
    for sensor_id in ("sensor_loop_in", "sensor_loop_out", "sensor_compressor"):
        assert sensor_id in page


def test_each_numeric_sensor_gets_a_panel(tmp_path: Path) -> None:
    panels = embedded(render(recorded(tmp_path)))["panels"]

    assert isinstance(panels, dict)
    assert "sensor:sensor_loop_in" in panels
    assert "sensor:sensor_loop_out" in panels


def test_a_state_sensor_is_charted_as_cycles_not_as_a_temperature(tmp_path: Path) -> None:
    panels = embedded(render(recorded(tmp_path)))["panels"]

    assert isinstance(panels, dict)
    assert "sensor:sensor_compressor" not in panels
    assert panels["runs:sensor_compressor"]["kind"] == "bars"


def test_a_delta_panel_is_added_only_when_asked_for(tmp_path: Path) -> None:
    connection = recorded(tmp_path)
    pair = DeltaPair(sensor_id="sensor_loop_in", minus="sensor_loop_out")

    without = embedded(render(connection))["panels"]
    with_delta = embedded(render(connection, deltas=(pair,)))["panels"]

    assert isinstance(without, dict)
    assert isinstance(with_delta, dict)
    assert not any(key.startswith("delta:") for key in without)
    assert "delta:sensor_loop_in:sensor_loop_out" in with_delta


def test_every_panel_carries_all_three_intervals(tmp_path: Path) -> None:
    """They are precomputed, so switching view costs no query and no network."""

    panels = embedded(render(recorded(tmp_path)))["panels"]

    assert isinstance(panels, dict)
    for spec in panels.values():
        assert set(spec["views"]) == {"hour", "6 hours", "day"}


def test_a_gate_is_named_on_the_page(tmp_path: Path) -> None:
    """A restricted chart that does not say so is a chart that misleads."""

    connection = recorded(tmp_path)
    pair = DeltaPair(sensor_id="sensor_loop_in", minus="sensor_loop_out")

    page = render(connection, deltas=(pair,), while_asserted="sensor_compressor")

    assert "sensor_compressor" in page
    assert "was asserted" in page


def test_an_empty_database_is_refused(tmp_path: Path) -> None:
    database = tmp_path / "empty.sqlite3"
    with SqliteMeasurementHistorian(database):
        pass

    with pytest.raises(ReportingError, match="nothing to show"):
        render(open_readonly(database))


def test_the_page_carries_its_own_caveats(tmp_path: Path) -> None:
    """Everything the docs insist on has to survive the trip to the browser."""

    page = render(recorded(tmp_path))

    assert "none of them says why" in page
    assert "wall clock" in page
    assert "lower bounds" in page


def test_times_are_rendered_in_the_recording_wall_clock(tmp_path: Path) -> None:
    """A page that prints UTC while promising local time is lying in its footer."""

    eastern = timezone(timedelta(hours=-5))
    page = render(recorded(tmp_path, tzinfo=eastern))

    assert "-05:00" in page
    assert "+00:00" not in page


def test_a_sensor_name_cannot_break_out_of_the_markup(tmp_path: Path) -> None:
    database = tmp_path / "hostile.sqlite3"
    hostile = "<script>alert(1)</script>"

    with SqliteMeasurementHistorian(database) as historian:
        for index in range(2):
            moment = START + timedelta(minutes=index)
            historian.append(
                Measurement(
                    id=f"source_bus:x:{index}",
                    sensor_id=hostile,
                    observed_at=moment,
                    received_at=moment,
                    value=1.0,
                    unit="degC",
                    quality=DataQuality.GOOD,
                    source_id="source_bus",
                )
            )

    page = render(open_readonly(database))

    assert hostile not in page
    assert "&lt;script&gt;" in page


def test_a_sensor_name_cannot_close_the_data_block(tmp_path: Path) -> None:
    """The payload is JSON, but it lands inside HTML, where `</script>` ends it."""

    database = tmp_path / "closing.sqlite3"

    with SqliteMeasurementHistorian(database) as historian:
        for index in range(2):
            moment = START + timedelta(minutes=index)
            historian.append(
                Measurement(
                    id=f"source_bus:y:{index}",
                    sensor_id="a</script>b",
                    observed_at=moment,
                    received_at=moment,
                    value=1.0,
                    unit="degC",
                    quality=DataQuality.GOOD,
                    source_id="source_bus",
                )
            )

    page = render(open_readonly(database))
    payload = page.split("window.GEOPILOT=")[1]

    assert "</script>" not in payload.split(";</script>")[0]


def test_a_missing_interval_is_absent_from_the_series(tmp_path: Path) -> None:
    """A hole must reach the browser as a hole, not as a value of zero."""

    database = tmp_path / "gappy.sqlite3"
    with SqliteMeasurementHistorian(database) as historian:
        for index, offset in enumerate((timedelta(), timedelta(days=3))):
            moment = START + offset
            historian.append(
                Measurement(
                    id=f"source_bus:sensor_loop_in:{index}",
                    sensor_id="sensor_loop_in",
                    observed_at=moment,
                    received_at=moment,
                    value=2.0,
                    unit="degC",
                    quality=DataQuality.GOOD,
                    source_id="source_bus",
                )
            )

    panels = embedded(render(open_readonly(database)))["panels"]

    assert isinstance(panels, dict)
    series = panels["sensor:sensor_loop_in"]["views"]["day"]
    assert len(series) == 2


def test_the_static_page_has_no_controls_at_all(tmp_path: Path) -> None:
    """Not hidden — absent. A file has no back channel, so a button would lie."""

    page = render(recorded(tmp_path))

    assert "<h2>Control</h2>" not in page
    assert 'id="control"' not in page
    assert "controlToken" in page  # present as null, so the script can tell
    assert "/api/command" not in page


def test_the_served_page_carries_the_controls_and_the_token(tmp_path: Path) -> None:
    page = render(recorded(tmp_path), control_token="a-token")

    assert "<h2>Control</h2>" in page
    assert 'id="control"' in page
    assert "a-token" in page
    assert "/api/command" in page
