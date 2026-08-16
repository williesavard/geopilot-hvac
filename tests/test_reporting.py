"""Reporting tests.

Every test writes a real database through the historian rather than inserting
SQL directly, so the reports are proven against the schema the recorder
actually produces.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from geopilot.domain import DataQuality, Measurement
from geopilot.reporting import (
    ReportingError,
    bucketed,
    bucketed_delta,
    bucketed_runs,
    coverage,
    delta,
    duty_cycle,
    open_readonly,
    runs,
    summarize,
    summarize_runs,
)
from geopilot.sqlite_historian import SqliteMeasurementHistorian

START = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)


def measurement(
    *,
    index: int,
    sensor_id: str = "sensor_loop_in",
    value: int | float = 20.0,
    unit: str = "degC",
    observed_at: datetime | None = None,
) -> Measurement:
    moment = observed_at if observed_at is not None else START + timedelta(minutes=index)
    return Measurement(
        id=f"source_bus:{sensor_id}:{index}",
        sensor_id=sensor_id,
        observed_at=moment,
        received_at=moment,
        value=value,
        unit=unit,
        quality=DataQuality.GOOD,
        source_id="source_bus",
    )


def recorded(tmp_path: Path, measurements: list[Measurement]) -> sqlite3.Connection:
    database = tmp_path / "geopilot.sqlite3"
    with SqliteMeasurementHistorian(database) as historian:
        for item in measurements:
            historian.append(item)
    return open_readonly(database)


def test_a_missing_database_is_refused_rather_than_created(tmp_path: Path) -> None:
    """Reporting on a path that does not exist must not create an empty one."""

    absent = tmp_path / "nothing.sqlite3"

    with pytest.raises(ReportingError, match="not found"):
        open_readonly(absent)

    assert not absent.exists()


def test_the_connection_cannot_write(tmp_path: Path) -> None:
    connection = recorded(tmp_path, [measurement(index=0)])

    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        connection.execute("DELETE FROM measurements")


def test_coverage_reports_one_row_per_sensor(tmp_path: Path) -> None:
    connection = recorded(
        tmp_path,
        [
            measurement(index=0, sensor_id="sensor_loop_in"),
            measurement(index=1, sensor_id="sensor_loop_in"),
            measurement(index=2, sensor_id="sensor_loop_out"),
        ],
    )

    reports = coverage(connection)

    assert [report.sensor_id for report in reports] == [
        "sensor_loop_in",
        "sensor_loop_out",
    ]
    assert reports[0].count == 2
    assert reports[1].count == 1


def test_coverage_reports_the_recorded_span(tmp_path: Path) -> None:
    connection = recorded(
        tmp_path,
        [measurement(index=0), measurement(index=60)],
    )

    report = coverage(connection)[0]

    assert report.first_observed_at == START
    assert report.last_observed_at == START + timedelta(minutes=60)
    assert report.span == timedelta(hours=1)


def test_coverage_finds_the_gap_a_total_count_hides(tmp_path: Path) -> None:
    """Three days of silence leaves a healthy-looking count. The gap is the tell."""

    connection = recorded(
        tmp_path,
        [
            measurement(index=0),
            measurement(index=1),
            measurement(index=2, observed_at=START + timedelta(days=3)),
            measurement(index=3, observed_at=START + timedelta(days=3, minutes=1)),
        ],
    )

    report = coverage(connection)[0]

    assert report.count == 4
    assert report.largest_gap == timedelta(days=3) - timedelta(minutes=1)


def test_a_single_observation_has_no_gap(tmp_path: Path) -> None:
    connection = recorded(tmp_path, [measurement(index=0)])

    assert coverage(connection)[0].largest_gap == timedelta(0)


def test_coverage_of_an_empty_database_is_empty(tmp_path: Path) -> None:
    connection = recorded(tmp_path, [])

    assert coverage(connection) == ()


def test_summary_reports_the_statistics(tmp_path: Path) -> None:
    connection = recorded(
        tmp_path,
        [
            measurement(index=0, value=10.0),
            measurement(index=1, value=20.0),
            measurement(index=2, value=30.0),
        ],
    )

    summary = summarize(connection, "sensor_loop_in")

    assert summary is not None
    assert (summary.count, summary.minimum, summary.maximum, summary.mean) == (
        3,
        10.0,
        30.0,
        20.0,
    )
    assert summary.unit == "degC"


def test_the_window_start_is_inclusive_and_the_end_exclusive(tmp_path: Path) -> None:
    """A half-open window lets consecutive days tile without double counting."""

    connection = recorded(
        tmp_path,
        [
            measurement(index=0, value=1.0),
            measurement(index=1, value=2.0),
            measurement(index=2, value=3.0),
        ],
    )

    summary = summarize(
        connection,
        "sensor_loop_in",
        start=START + timedelta(minutes=1),
        end=START + timedelta(minutes=2),
    )

    assert summary is not None
    assert summary.count == 1
    assert summary.mean == 2.0


def test_an_empty_window_reports_nothing_rather_than_zero(tmp_path: Path) -> None:
    """Zero samples and a mean of zero are different facts."""

    connection = recorded(tmp_path, [measurement(index=0)])

    assert summarize(connection, "sensor_loop_in", start=START + timedelta(days=1)) is None


def test_an_unknown_sensor_reports_nothing(tmp_path: Path) -> None:
    connection = recorded(tmp_path, [measurement(index=0)])

    assert summarize(connection, "sensor_absent") is None


def test_a_summary_covers_only_the_named_sensor(tmp_path: Path) -> None:
    connection = recorded(
        tmp_path,
        [
            measurement(index=0, sensor_id="sensor_loop_in", value=10.0),
            measurement(index=1, sensor_id="sensor_loop_out", value=1000.0),
        ],
    )

    summary = summarize(connection, "sensor_loop_in")

    assert summary is not None
    assert summary.maximum == 10.0


def test_mixed_units_are_refused_rather_than_averaged(tmp_path: Path) -> None:
    """An average of Celsius and Fahrenheit is a number with no meaning."""

    connection = recorded(
        tmp_path,
        [
            measurement(index=0, value=20.0, unit="degC"),
            measurement(index=1, value=68.0, unit="degF"),
        ],
    )

    with pytest.raises(ReportingError, match="different units"):
        summarize(connection, "sensor_loop_in")


def test_a_narrower_window_can_avoid_the_unit_change(tmp_path: Path) -> None:
    connection = recorded(
        tmp_path,
        [
            measurement(index=0, value=20.0, unit="degC"),
            measurement(index=1, value=68.0, unit="degF"),
        ],
    )

    summary = summarize(connection, "sensor_loop_in", end=START + timedelta(minutes=1))

    assert summary is not None
    assert summary.unit == "degC"


def test_duty_cycle_is_the_asserted_fraction(tmp_path: Path) -> None:
    connection = recorded(
        tmp_path,
        [
            measurement(index=0, sensor_id="sensor_zone_1", value=1, unit="state"),
            measurement(index=1, sensor_id="sensor_zone_1", value=0, unit="state"),
            measurement(index=2, sensor_id="sensor_zone_1", value=1, unit="state"),
            measurement(index=3, sensor_id="sensor_zone_1", value=0, unit="state"),
        ],
    )

    assert duty_cycle(connection, "sensor_zone_1") == 0.5


def test_a_state_never_asserted_has_a_duty_cycle_of_zero(tmp_path: Path) -> None:
    """Zero is a result. It is not the same as no samples."""

    connection = recorded(
        tmp_path,
        [measurement(index=0, sensor_id="sensor_zone_4", value=0, unit="state")],
    )

    assert duty_cycle(connection, "sensor_zone_4") == 0.0


def test_duty_cycle_without_samples_is_none(tmp_path: Path) -> None:
    connection = recorded(tmp_path, [measurement(index=0)])

    assert duty_cycle(connection, "sensor_zone_1") is None


def test_duty_cycle_honours_the_window(tmp_path: Path) -> None:
    connection = recorded(
        tmp_path,
        [
            measurement(index=0, sensor_id="sensor_zone_1", value=1, unit="state"),
            measurement(index=1, sensor_id="sensor_zone_1", value=0, unit="state"),
            measurement(index=2, sensor_id="sensor_zone_1", value=0, unit="state"),
        ],
    )

    assert duty_cycle(connection, "sensor_zone_1", start=START + timedelta(minutes=1)) == 0.0


def test_buckets_aggregate_each_interval(tmp_path: Path) -> None:
    connection = recorded(
        tmp_path,
        [measurement(index=index, value=float(index)) for index in range(120)],
    )

    buckets = bucketed(connection, "sensor_loop_in", interval=timedelta(hours=1))

    assert len(buckets) == 2
    assert buckets[0].count == 60
    assert (buckets[0].minimum, buckets[0].maximum, buckets[0].mean) == (0.0, 59.0, 29.5)
    assert buckets[1].mean == 89.5


def test_a_bucket_starts_at_the_interval_not_the_first_sample(tmp_path: Path) -> None:
    """A bucket holding one reading taken at 14:47 still starts at 14:00."""

    connection = recorded(
        tmp_path,
        [measurement(index=0, observed_at=START + timedelta(hours=14, minutes=47))],
    )

    bucket = bucketed(connection, "sensor_loop_in", interval=timedelta(hours=1), local=False)[0]

    assert bucket.starts_at == START + timedelta(hours=14)


def test_buckets_come_back_oldest_first(tmp_path: Path) -> None:
    connection = recorded(
        tmp_path,
        [
            measurement(index=0, observed_at=START + timedelta(days=2)),
            measurement(index=1, observed_at=START),
            measurement(index=2, observed_at=START + timedelta(days=1)),
        ],
    )

    buckets = bucketed(connection, "sensor_loop_in", interval=timedelta(days=1), local=False)

    assert [bucket.starts_at for bucket in buckets] == [
        START,
        START + timedelta(days=1),
        START + timedelta(days=2),
    ]


def test_an_empty_interval_is_absent_rather_than_invented(tmp_path: Path) -> None:
    """A gap in the data is honest. A synthesized point is not."""

    connection = recorded(
        tmp_path,
        [
            measurement(index=0, observed_at=START),
            measurement(index=1, observed_at=START + timedelta(days=3)),
        ],
    )

    buckets = bucketed(connection, "sensor_loop_in", interval=timedelta(days=1), local=False)

    assert len(buckets) == 2
    assert buckets[1].starts_at == START + timedelta(days=3)


def test_a_state_bucket_mean_is_its_duty_cycle(tmp_path: Path) -> None:
    connection = recorded(
        tmp_path,
        [
            measurement(index=index, sensor_id="sensor_zone_1", unit="state", value=value)
            for index, value in enumerate((1, 1, 1, 0))
        ],
    )

    bucket = bucketed(connection, "sensor_zone_1", interval=timedelta(hours=1), local=False)[0]

    assert bucket.mean == 0.75
    assert bucket.mean == duty_cycle(connection, "sensor_zone_1")


def test_local_buckets_follow_the_wall_clock_where_readings_were_taken(tmp_path: Path) -> None:
    """A daily bucket must be a local day, not one running 19:00 to 19:00."""

    eastern = timezone(timedelta(hours=-5))
    evening = datetime(2026, 1, 15, 22, 0, tzinfo=eastern)
    connection = recorded(
        tmp_path,
        [
            measurement(index=index, observed_at=evening + timedelta(hours=index))
            for index in range(8)
        ],
    )

    buckets = bucketed(connection, "sensor_loop_in", interval=timedelta(days=1))

    assert [bucket.starts_at.isoformat() for bucket in buckets] == [
        "2026-01-15T00:00:00-05:00",
        "2026-01-16T00:00:00-05:00",
    ]
    assert [bucket.count for bucket in buckets] == [2, 6]


def test_utc_alignment_would_have_merged_those_two_days(tmp_path: Path) -> None:
    """The same readings, aligned to UTC, become one day. That is the point."""

    eastern = timezone(timedelta(hours=-5))
    evening = datetime(2026, 1, 15, 22, 0, tzinfo=eastern)
    connection = recorded(
        tmp_path,
        [
            measurement(index=index, observed_at=evening + timedelta(hours=index))
            for index in range(8)
        ],
    )

    buckets = bucketed(connection, "sensor_loop_in", interval=timedelta(days=1), local=False)

    assert len(buckets) == 1
    assert buckets[0].count == 8


def test_an_interval_that_drifts_from_midnight_is_refused(tmp_path: Path) -> None:
    connection = recorded(tmp_path, [measurement(index=0)])

    with pytest.raises(ReportingError, match="drift"):
        bucketed(connection, "sensor_loop_in", interval=timedelta(hours=7))


def test_a_whole_number_of_days_is_accepted(tmp_path: Path) -> None:
    """A week does not divide into a day, but it does tile from midnight."""

    connection = recorded(tmp_path, [measurement(index=0)])

    assert len(bucketed(connection, "sensor_loop_in", interval=timedelta(days=7))) == 1


def test_a_non_positive_interval_is_refused(tmp_path: Path) -> None:
    connection = recorded(tmp_path, [measurement(index=0)])

    for interval in (timedelta(0), timedelta(hours=-1)):
        with pytest.raises(ReportingError, match="positive"):
            bucketed(connection, "sensor_loop_in", interval=interval)


def test_buckets_honour_the_window(tmp_path: Path) -> None:
    connection = recorded(
        tmp_path,
        [measurement(index=index) for index in range(180)],
    )

    buckets = bucketed(
        connection,
        "sensor_loop_in",
        interval=timedelta(hours=1),
        start=START + timedelta(hours=1),
        end=START + timedelta(hours=2),
        local=False,
    )

    assert len(buckets) == 1
    assert buckets[0].count == 60


def test_buckets_cover_only_the_named_sensor(tmp_path: Path) -> None:
    connection = recorded(
        tmp_path,
        [
            measurement(index=0, sensor_id="sensor_loop_in", value=10.0),
            measurement(index=1, sensor_id="sensor_loop_out", value=1000.0),
        ],
    )

    bucket = bucketed(connection, "sensor_loop_in", interval=timedelta(hours=1), local=False)[0]

    assert bucket.count == 1
    assert bucket.maximum == 10.0


def test_bucketing_an_empty_window_returns_nothing(tmp_path: Path) -> None:
    connection = recorded(tmp_path, [measurement(index=0)])

    assert bucketed(connection, "sensor_absent", interval=timedelta(hours=1)) == ()


def test_bucketing_refuses_observations_stamped_before_the_epoch(tmp_path: Path) -> None:
    """SQLite truncates division toward zero, so a negative instant misbuckets."""

    connection = recorded(
        tmp_path,
        [measurement(index=0, observed_at=datetime(1969, 12, 31, 23, 0, tzinfo=UTC))],
    )

    with pytest.raises(ReportingError, match="before 1970"):
        bucketed(connection, "sensor_loop_in", interval=timedelta(hours=1), local=False)


def test_a_positive_stamp_can_still_go_negative_on_a_western_clock(tmp_path: Path) -> None:
    """A Pi with no clock and no network stamps its first readings at the epoch.

    23:00 on 1969-12-31 in Eastern time is 04:00 on 1970-01-01 in UTC. The UTC
    instant is positive and buckets fine; the local one is negative and does not.
    """

    eastern = timezone(timedelta(hours=-5))
    connection = recorded(
        tmp_path,
        [measurement(index=0, observed_at=datetime(1969, 12, 31, 23, 0, tzinfo=eastern))],
    )

    assert bucketed(connection, "sensor_loop_in", interval=timedelta(hours=1), local=False)

    with pytest.raises(ReportingError, match="before 1970"):
        bucketed(connection, "sensor_loop_in", interval=timedelta(hours=1))


def test_bucketing_refuses_mixed_units(tmp_path: Path) -> None:
    connection = recorded(
        tmp_path,
        [
            measurement(index=0, value=20.0, unit="degC"),
            measurement(index=1, value=68.0, unit="degF"),
        ],
    )

    with pytest.raises(ReportingError, match="different units"):
        bucketed(connection, "sensor_loop_in", interval=timedelta(hours=1))


def loop_pair(
    tmp_path: Path,
    *,
    inbound: tuple[float, ...],
    outbound: tuple[float, ...],
    lag: timedelta = timedelta(seconds=3),
    outbound_every: int = 1,
) -> sqlite3.Connection:
    """A loop-in and a loop-out series, read a few seconds apart as on a real bus."""

    measurements = [
        measurement(index=index, sensor_id="sensor_loop_in", value=value)
        for index, value in enumerate(inbound)
    ]
    measurements += [
        measurement(
            index=index,
            sensor_id="sensor_loop_out",
            value=value,
            observed_at=START + timedelta(minutes=index * outbound_every) + lag,
        )
        for index, value in enumerate(outbound)
    ]
    return recorded(tmp_path, measurements)


def test_the_delta_pairs_readings_taken_seconds_apart(tmp_path: Path) -> None:
    """An exact-timestamp join would find nothing; two sensors are never read at once."""

    connection = loop_pair(tmp_path, inbound=(2.0, 2.4, 2.8), outbound=(-1.0, -0.6, -0.2))

    summary = delta(connection, "sensor_loop_in", minus="sensor_loop_out")

    assert summary is not None
    assert summary.count == 3
    assert (summary.minimum, summary.maximum, summary.mean) == (3.0, 3.0, 3.0)
    assert summary.unit == "degC"
    assert (summary.unpaired, summary.unpaired_minus) == (0, 0)


def test_the_delta_is_signed_in_the_order_asked_for(tmp_path: Path) -> None:
    connection = loop_pair(tmp_path, inbound=(2.0,), outbound=(-1.0,))

    forward = delta(connection, "sensor_loop_in", minus="sensor_loop_out")
    backward = delta(connection, "sensor_loop_out", minus="sensor_loop_in")

    assert forward is not None
    assert backward is not None
    assert forward.mean == 3.0
    assert backward.mean == -3.0


def test_readings_beyond_the_tolerance_are_not_paired(tmp_path: Path) -> None:
    connection = loop_pair(
        tmp_path, inbound=(2.0,), outbound=(-1.0,), lag=timedelta(seconds=45)
    )

    assert delta(connection, "sensor_loop_in", minus="sensor_loop_out") is None


def test_a_wider_tolerance_accepts_them(tmp_path: Path) -> None:
    connection = loop_pair(
        tmp_path, inbound=(2.0,), outbound=(-1.0,), lag=timedelta(seconds=45)
    )

    summary = delta(
        connection,
        "sensor_loop_in",
        minus="sensor_loop_out",
        tolerance=timedelta(minutes=1),
    )

    assert summary is not None
    assert summary.mean == 3.0


def test_unpaired_readings_are_counted_rather_than_hidden(tmp_path: Path) -> None:
    """A delta from 2 pairs out of 6 readings is a different claim from 6 out of 6."""

    connection = loop_pair(
        tmp_path,
        inbound=(2.0, 2.0, 2.0, 2.0, 2.0, 2.0),
        outbound=(-1.0, -1.0),
        outbound_every=3,
    )

    summary = delta(connection, "sensor_loop_in", minus="sensor_loop_out")

    assert summary is not None
    assert summary.count == 2
    assert summary.unpaired == 4
    assert summary.unpaired_minus == 0


def test_a_partner_is_consumed_rather_than_reused(tmp_path: Path) -> None:
    """One stale reading must not stand in for five, or the counts mean nothing."""

    connection = loop_pair(
        tmp_path,
        inbound=(2.0, 2.0, 2.0),
        outbound=(-1.0,),
        lag=timedelta(seconds=1),
    )

    summary = delta(
        connection,
        "sensor_loop_in",
        minus="sensor_loop_out",
        tolerance=timedelta(hours=1),
    )

    assert summary is not None
    assert summary.count == 1
    assert summary.unpaired == 2


def test_the_nearest_partner_is_chosen(tmp_path: Path) -> None:
    connection = recorded(
        tmp_path,
        [
            measurement(index=0, sensor_id="sensor_loop_in", value=10.0),
            measurement(
                index=0,
                sensor_id="sensor_loop_out",
                value=1.0,
                observed_at=START - timedelta(seconds=20),
            ),
            measurement(
                index=1,
                sensor_id="sensor_loop_out",
                value=2.0,
                observed_at=START + timedelta(seconds=2),
            ),
        ],
    )

    summary = delta(connection, "sensor_loop_in", minus="sensor_loop_out")

    assert summary is not None
    assert summary.count == 1
    assert summary.mean == 8.0


def test_comparing_sensors_in_different_units_is_refused(tmp_path: Path) -> None:
    connection = recorded(
        tmp_path,
        [
            measurement(index=0, sensor_id="sensor_loop_in", value=20.0, unit="degC"),
            measurement(index=1, sensor_id="sensor_zone_1", value=1, unit="state"),
        ],
    )

    with pytest.raises(ReportingError, match="not recorded in the same unit"):
        delta(connection, "sensor_loop_in", minus="sensor_zone_1")


def test_comparing_a_sensor_against_itself_is_refused(tmp_path: Path) -> None:
    connection = loop_pair(tmp_path, inbound=(2.0,), outbound=(-1.0,))

    with pytest.raises(ReportingError, match="itself"):
        delta(connection, "sensor_loop_in", minus="sensor_loop_in")


def test_a_negative_tolerance_is_refused(tmp_path: Path) -> None:
    connection = loop_pair(tmp_path, inbound=(2.0,), outbound=(-1.0,))

    with pytest.raises(ReportingError, match="negative"):
        delta(
            connection,
            "sensor_loop_in",
            minus="sensor_loop_out",
            tolerance=timedelta(seconds=-1),
        )


def test_a_delta_without_any_pair_is_none(tmp_path: Path) -> None:
    connection = recorded(tmp_path, [measurement(index=0, sensor_id="sensor_loop_in")])

    assert delta(connection, "sensor_loop_in", minus="sensor_loop_out") is None


def test_the_delta_honours_the_window(tmp_path: Path) -> None:
    connection = loop_pair(
        tmp_path,
        inbound=(2.0, 5.0, 9.0),
        outbound=(-1.0, -1.0, -1.0),
    )

    summary = delta(
        connection,
        "sensor_loop_in",
        minus="sensor_loop_out",
        start=START + timedelta(minutes=1),
        end=START + timedelta(minutes=2),
    )

    assert summary is not None
    assert summary.count == 1
    assert summary.mean == 6.0


def test_delta_buckets_aggregate_the_pairs_not_the_bucket_means(tmp_path: Path) -> None:
    """The smallest difference is not the difference of the smallest readings."""

    connection = loop_pair(
        tmp_path,
        inbound=(10.0, 2.0),
        outbound=(9.0, 0.0),
    )

    bucket = bucketed_delta(
        connection,
        "sensor_loop_in",
        minus="sensor_loop_out",
        interval=timedelta(hours=1),
        local=False,
    )[0]

    # Pairwise the deltas are 1.0 and 2.0. Subtracting the bucket minima would
    # have claimed a minimum of 2.0 - 0.0 = 2.0, which never occurred.
    assert (bucket.minimum, bucket.maximum, bucket.mean) == (1.0, 2.0, 1.5)


def test_delta_buckets_are_ordered_and_split_by_interval(tmp_path: Path) -> None:
    connection = loop_pair(
        tmp_path,
        inbound=(2.0,) * 90,
        outbound=(-1.0,) * 90,
    )

    buckets = bucketed_delta(
        connection,
        "sensor_loop_in",
        minus="sensor_loop_out",
        interval=timedelta(hours=1),
        local=False,
    )

    assert [bucket.count for bucket in buckets] == [60, 30]
    assert buckets[0].starts_at == START
    assert buckets[1].starts_at == START + timedelta(hours=1)


def test_delta_buckets_align_to_the_local_wall_clock(tmp_path: Path) -> None:
    eastern = timezone(timedelta(hours=-5))
    evening = datetime(2026, 1, 15, 22, 0, tzinfo=eastern)
    measurements = []
    for index in range(4):
        moment = evening + timedelta(hours=index)
        measurements.append(
            measurement(index=index, sensor_id="sensor_loop_in", value=2.0, observed_at=moment)
        )
        measurements.append(
            measurement(
                index=index,
                sensor_id="sensor_loop_out",
                value=-1.0,
                observed_at=moment + timedelta(seconds=3),
            )
        )

    buckets = bucketed_delta(
        recorded(tmp_path, measurements),
        "sensor_loop_in",
        minus="sensor_loop_out",
        interval=timedelta(days=1),
    )

    assert [bucket.starts_at.isoformat() for bucket in buckets] == [
        "2026-01-15T00:00:00-05:00",
        "2026-01-16T00:00:00-05:00",
    ]
    assert [bucket.count for bucket in buckets] == [2, 2]


def test_delta_buckets_refuse_an_interval_that_drifts(tmp_path: Path) -> None:
    connection = loop_pair(tmp_path, inbound=(2.0,), outbound=(-1.0,))

    with pytest.raises(ReportingError, match="drift"):
        bucketed_delta(
            connection,
            "sensor_loop_in",
            minus="sensor_loop_out",
            interval=timedelta(hours=7),
        )


def test_delta_buckets_refuse_mismatched_units_before_pairing(tmp_path: Path) -> None:
    connection = recorded(
        tmp_path,
        [
            measurement(index=0, sensor_id="sensor_loop_in", value=20.0, unit="degC"),
            measurement(index=1, sensor_id="sensor_zone_1", value=1, unit="state"),
        ],
    )

    with pytest.raises(ReportingError, match="not recorded in the same unit"):
        bucketed_delta(
            connection,
            "sensor_loop_in",
            minus="sensor_zone_1",
            interval=timedelta(hours=1),
        )


def test_delta_buckets_without_pairs_are_empty(tmp_path: Path) -> None:
    connection = recorded(tmp_path, [measurement(index=0, sensor_id="sensor_loop_in")])

    assert (
        bucketed_delta(
            connection,
            "sensor_loop_in",
            minus="sensor_loop_out",
            interval=timedelta(hours=1),
        )
        == ()
    )


def gated_loop(
    tmp_path: Path,
    *,
    running: tuple[bool, ...],
    gate_unit: str = "state",
    gate_lag: timedelta = timedelta(seconds=6),
) -> sqlite3.Connection:
    """A loop whose delta is 3.0 while running and 0.1 while idle.

    The three sensors are stamped seconds apart, as a real acquisition cycle
    stamps them, so nothing here lines up on an exact instant.
    """

    measurements = []
    for index, is_running in enumerate(running):
        moment = START + timedelta(minutes=index)
        spread = 3.0 if is_running else 0.1
        measurements.append(
            measurement(index=index, sensor_id="sensor_loop_in", value=2.0, observed_at=moment)
        )
        measurements.append(
            measurement(
                index=index,
                sensor_id="sensor_loop_out",
                value=2.0 - spread,
                observed_at=moment + timedelta(seconds=3),
            )
        )
        measurements.append(
            measurement(
                index=index,
                sensor_id="sensor_compressor",
                value=1 if is_running else 0,
                unit=gate_unit,
                observed_at=moment + gate_lag,
            )
        )
    return recorded(tmp_path, measurements)


def test_a_gated_delta_describes_only_the_running_moments(tmp_path: Path) -> None:
    """Ungated, the mean is diluted by every idle hour. That is the whole point."""

    connection = gated_loop(tmp_path, running=(True, True, False, False))

    ungated = delta(connection, "sensor_loop_in", minus="sensor_loop_out")
    gated = delta(
        connection,
        "sensor_loop_in",
        minus="sensor_loop_out",
        while_asserted="sensor_compressor",
    )

    assert ungated is not None
    assert gated is not None
    # approx, not equality: the idle delta is 0.1, which no float represents
    # exactly, and Python 3.12 changed sum() to compensated summation — so the
    # last bit of this mean differs between interpreters.
    assert ungated.mean == pytest.approx(1.55)
    assert gated.mean == 3.0
    assert gated.count == 2


def test_a_gated_delta_counts_what_it_dropped(tmp_path: Path) -> None:
    """Excluded and unpaired say different things and are kept apart."""

    connection = gated_loop(tmp_path, running=(True, False, False, False))

    gated = delta(
        connection,
        "sensor_loop_in",
        minus="sensor_loop_out",
        while_asserted="sensor_compressor",
    )

    assert gated is not None
    assert (gated.count, gated.excluded, gated.unpaired) == (1, 3, 0)


def test_an_ungated_result_reports_nothing_excluded(tmp_path: Path) -> None:
    connection = gated_loop(tmp_path, running=(True, False))

    summary = delta(connection, "sensor_loop_in", minus="sensor_loop_out")

    assert summary is not None
    assert summary.excluded == 0


def test_a_gate_that_never_asserts_yields_no_result(tmp_path: Path) -> None:
    connection = gated_loop(tmp_path, running=(False, False))

    assert (
        delta(
            connection,
            "sensor_loop_in",
            minus="sensor_loop_out",
            while_asserted="sensor_compressor",
        )
        is None
    )


def test_a_state_reading_is_reused_rather_than_consumed(tmp_path: Path) -> None:
    """A state is a level: one reading legitimately describes every moment near it."""

    measurements = [
        measurement(
            index=index,
            sensor_id="sensor_loop_in",
            value=float(index),
            observed_at=START + timedelta(seconds=index),
        )
        for index in range(4)
    ]
    measurements.append(
        measurement(
            index=0,
            sensor_id="sensor_compressor",
            value=1,
            unit="state",
            observed_at=START + timedelta(seconds=2),
        )
    )

    summary = summarize(
        recorded(tmp_path, measurements),
        "sensor_loop_in",
        while_asserted="sensor_compressor",
    )

    assert summary is not None
    assert summary.count == 4


def test_a_gate_does_not_reach_beyond_its_tolerance(tmp_path: Path) -> None:
    """Beyond the tolerance the signal is unobserved, and unobserved is not asserted."""

    connection = gated_loop(tmp_path, running=(True,), gate_lag=timedelta(seconds=45))

    assert (
        delta(
            connection,
            "sensor_loop_in",
            minus="sensor_loop_out",
            while_asserted="sensor_compressor",
        )
        is None
    )

    assert (
        delta(
            connection,
            "sensor_loop_in",
            minus="sensor_loop_out",
            while_asserted="sensor_compressor",
            tolerance=timedelta(minutes=1),
        )
        is not None
    )


def test_gating_on_a_sensor_that_is_not_a_state_is_refused(tmp_path: Path) -> None:
    connection = gated_loop(tmp_path, running=(True,))

    with pytest.raises(ReportingError, match="not state"):
        delta(
            connection,
            "sensor_loop_in",
            minus="sensor_loop_out",
            while_asserted="sensor_loop_out",
        )


def test_gating_on_an_unknown_sensor_is_refused(tmp_path: Path) -> None:
    """A typo must not quietly look like an installation that never ran."""

    connection = gated_loop(tmp_path, running=(True,))

    with pytest.raises(ReportingError, match="no observations at all"):
        delta(
            connection,
            "sensor_loop_in",
            minus="sensor_loop_out",
            while_asserted="sensor_compresor",
        )


def test_gating_on_a_sensor_absent_from_the_window_is_refused(tmp_path: Path) -> None:
    connection = gated_loop(tmp_path, running=(True, True))

    with pytest.raises(ReportingError, match="inside that window"):
        delta(
            connection,
            "sensor_loop_in",
            minus="sensor_loop_out",
            while_asserted="sensor_compressor",
            start=START + timedelta(days=1),
        )


def test_a_gated_summary_restricts_the_statistics(tmp_path: Path) -> None:
    connection = gated_loop(tmp_path, running=(True, True, False, False))

    summary = summarize(connection, "sensor_loop_out", while_asserted="sensor_compressor")

    assert summary is not None
    assert (summary.count, summary.mean, summary.excluded) == (2, -1.0, 2)


def test_a_gated_summary_of_nothing_is_none(tmp_path: Path) -> None:
    connection = gated_loop(tmp_path, running=(False, False))

    assert summarize(connection, "sensor_loop_out", while_asserted="sensor_compressor") is None


def test_gated_buckets_keep_only_the_running_moments(tmp_path: Path) -> None:
    connection = gated_loop(tmp_path, running=(True, False, True, False))

    buckets = bucketed(
        connection,
        "sensor_loop_out",
        interval=timedelta(hours=1),
        while_asserted="sensor_compressor",
        local=False,
    )

    assert len(buckets) == 1
    assert buckets[0].count == 2
    assert buckets[0].mean == -1.0


def test_a_bucket_with_no_running_moment_is_absent(tmp_path: Path) -> None:
    """Equipment off all afternoon and recorder off all afternoon look the same."""

    running = (True,) + (False,) * 60 + (True,)
    connection = gated_loop(tmp_path, running=running)

    buckets = bucketed(
        connection,
        "sensor_loop_out",
        interval=timedelta(hours=1),
        while_asserted="sensor_compressor",
        local=False,
    )

    assert [bucket.count for bucket in buckets] == [1, 1]
    assert buckets[1].starts_at == START + timedelta(hours=1)


def test_gated_delta_buckets_report_the_running_delta(tmp_path: Path) -> None:
    connection = gated_loop(tmp_path, running=(True, False, True, False))

    buckets = bucketed_delta(
        connection,
        "sensor_loop_in",
        minus="sensor_loop_out",
        interval=timedelta(hours=1),
        while_asserted="sensor_compressor",
        local=False,
    )

    assert len(buckets) == 1
    assert (buckets[0].count, buckets[0].mean) == (2, 3.0)


def test_the_inverse_gate_keeps_the_idle_moments(tmp_path: Path) -> None:
    """What the loop does while recovering is a different question from under load."""

    connection = gated_loop(tmp_path, running=(True, True, False, False))

    working = delta(
        connection,
        "sensor_loop_in",
        minus="sensor_loop_out",
        while_asserted="sensor_compressor",
    )
    recovering = delta(
        connection,
        "sensor_loop_in",
        minus="sensor_loop_out",
        while_not_asserted="sensor_compressor",
    )

    assert working is not None
    assert recovering is not None
    assert working.mean == 3.0
    assert recovering.mean == pytest.approx(0.1)
    assert working.count == recovering.count == 2
    assert working.excluded == recovering.excluded == 2


def test_the_two_senses_partition_the_pairs(tmp_path: Path) -> None:
    connection = gated_loop(tmp_path, running=(True, False, False, True, False))

    ungated = delta(connection, "sensor_loop_in", minus="sensor_loop_out")
    asserted = delta(
        connection,
        "sensor_loop_in",
        minus="sensor_loop_out",
        while_asserted="sensor_compressor",
    )
    idle = delta(
        connection,
        "sensor_loop_in",
        minus="sensor_loop_out",
        while_not_asserted="sensor_compressor",
    )

    assert ungated is not None
    assert asserted is not None
    assert idle is not None
    assert asserted.count + idle.count == ungated.count


def test_an_unobserved_state_admits_nothing_in_either_direction(tmp_path: Path) -> None:
    """A hole in the state record must not be read as idle time."""

    connection = gated_loop(tmp_path, running=(False,), gate_lag=timedelta(seconds=45))

    assert (
        delta(
            connection,
            "sensor_loop_in",
            minus="sensor_loop_out",
            while_not_asserted="sensor_compressor",
        )
        is None
    )


def test_asking_for_both_senses_at_once_is_refused(tmp_path: Path) -> None:
    connection = gated_loop(tmp_path, running=(True,))

    with pytest.raises(ReportingError, match="one sense or the other"):
        delta(
            connection,
            "sensor_loop_in",
            minus="sensor_loop_out",
            while_asserted="sensor_compressor",
            while_not_asserted="sensor_compressor",
        )


def test_the_inverse_gate_is_validated_like_the_forward_one(tmp_path: Path) -> None:
    connection = gated_loop(tmp_path, running=(True,))

    with pytest.raises(ReportingError, match="not state"):
        summarize(connection, "sensor_loop_in", while_not_asserted="sensor_loop_out")

    with pytest.raises(ReportingError, match="no observations at all"):
        summarize(connection, "sensor_loop_in", while_not_asserted="sensor_compresor")


def test_an_inverse_gated_summary_restricts_the_statistics(tmp_path: Path) -> None:
    connection = gated_loop(tmp_path, running=(True, False, False))

    summary = summarize(connection, "sensor_loop_out", while_not_asserted="sensor_compressor")

    assert summary is not None
    assert summary.count == 2
    assert summary.mean == pytest.approx(1.9)
    assert summary.excluded == 1


def test_inverse_gated_buckets_report_the_recovery(tmp_path: Path) -> None:
    connection = gated_loop(tmp_path, running=(True, False, True, False))

    buckets = bucketed_delta(
        connection,
        "sensor_loop_in",
        minus="sensor_loop_out",
        interval=timedelta(hours=1),
        while_not_asserted="sensor_compressor",
        local=False,
    )

    assert len(buckets) == 1
    assert buckets[0].count == 2
    assert buckets[0].mean == pytest.approx(0.1)


def state_series(
    tmp_path: Path,
    pattern: str,
    *,
    every: timedelta = timedelta(minutes=1),
    sensor_id: str = "sensor_compressor",
    unit: str = "state",
) -> sqlite3.Connection:
    """Record a state sensor from a string like "111001", one character per sample.

    A dot skips a sample, which is how a recording gap is written.
    """

    measurements = []
    for index, character in enumerate(pattern):
        if character == ".":
            continue
        measurements.append(
            measurement(
                index=index,
                sensor_id=sensor_id,
                value=int(character),
                unit=unit,
                observed_at=START + index * every,
            )
        )
    return recorded(tmp_path, measurements)


def test_runs_split_a_series_at_every_transition(tmp_path: Path) -> None:
    connection = state_series(tmp_path, "1110011000")

    found = runs(connection, "sensor_compressor")

    assert [(run.asserted, run.samples) for run in found] == [
        (True, 3),
        (False, 2),
        (True, 2),
        (False, 3),
    ]


def test_a_run_spans_its_first_and_last_observation(tmp_path: Path) -> None:
    """The real transitions happened in the sampling gaps; nothing is extrapolated."""

    connection = state_series(tmp_path, "1110")

    first = runs(connection, "sensor_compressor")[0]

    assert first.starts_at == START
    assert first.ends_at == START + timedelta(minutes=2)
    assert first.duration == timedelta(minutes=2)


def test_a_run_seen_once_has_no_duration(tmp_path: Path) -> None:
    connection = state_series(tmp_path, "010")

    middle = runs(connection, "sensor_compressor")[1]

    assert middle.samples == 1
    assert middle.duration == timedelta(0)


def test_one_sense_can_be_selected(tmp_path: Path) -> None:
    connection = state_series(tmp_path, "1110011000")

    assert len(runs(connection, "sensor_compressor", asserted=True)) == 2
    assert len(runs(connection, "sensor_compressor", asserted=False)) == 2
    assert len(runs(connection, "sensor_compressor")) == 4


def test_the_first_and_last_runs_are_truncated(tmp_path: Path) -> None:
    """Their real edges lie outside the window, so their durations are lower bounds."""

    connection = state_series(tmp_path, "110011")

    found = runs(connection, "sensor_compressor")

    assert [run.truncated for run in found] == [True, False, True]


def test_a_gap_ends_a_run_even_when_the_value_holds(tmp_path: Path) -> None:
    """Assuming a signal held across an outage is the mistake this refuses."""

    connection = state_series(tmp_path, "11..........11")

    found = runs(connection, "sensor_compressor")

    assert len(found) == 2
    assert all(run.asserted for run in found)
    assert all(run.truncated for run in found)


def test_a_short_hole_does_not_end_a_run(tmp_path: Path) -> None:
    """One missed cycle is an ordinary hiccup, not an outage."""

    connection = state_series(tmp_path, "11.11")

    found = runs(connection, "sensor_compressor")

    assert len(found) == 1
    assert found[0].samples == 4
    assert found[0].duration == timedelta(minutes=4)


def test_the_break_threshold_is_adjustable(tmp_path: Path) -> None:
    connection = state_series(tmp_path, "11.11")

    assert len(runs(connection, "sensor_compressor", max_gap=timedelta(minutes=1))) == 2


def test_a_zero_break_threshold_is_refused(tmp_path: Path) -> None:
    connection = state_series(tmp_path, "11")

    with pytest.raises(ReportingError, match="cannot be broken"):
        runs(connection, "sensor_compressor", max_gap=timedelta(0))


def test_runs_refuse_a_sensor_that_is_not_a_state(tmp_path: Path) -> None:
    connection = state_series(tmp_path, "11", unit="degC")

    with pytest.raises(ReportingError, match="not state"):
        runs(connection, "sensor_compressor")


def test_a_run_summary_describes_length_and_frequency(tmp_path: Path) -> None:
    connection = state_series(tmp_path, "0111011110")

    summary = summarize_runs(connection, "sensor_compressor", asserted=True)

    assert summary is not None
    assert summary.count == 2
    assert summary.shortest == timedelta(minutes=2)
    assert summary.longest == timedelta(minutes=3)
    assert summary.mean == timedelta(minutes=2, seconds=30)
    assert summary.total == timedelta(minutes=5)
    assert summary.truncated == 0


def test_a_run_summary_counts_the_truncated_ones(tmp_path: Path) -> None:
    connection = state_series(tmp_path, "1101")

    summary = summarize_runs(connection, "sensor_compressor", asserted=True)

    assert summary is not None
    assert summary.truncated == 2


def test_a_sense_that_never_occurs_has_no_summary(tmp_path: Path) -> None:
    connection = state_series(tmp_path, "1111")

    assert summarize_runs(connection, "sensor_compressor", asserted=False) is None


def test_run_buckets_count_starts_per_interval(tmp_path: Path) -> None:
    """This is the number that separates 22 long cycles from 38 short ones."""

    connection = state_series(tmp_path, "10" * 40, every=timedelta(minutes=1))

    buckets = bucketed_runs(
        connection,
        "sensor_compressor",
        asserted=True,
        interval=timedelta(hours=1),
        local=False,
    )

    assert [bucket.count for bucket in buckets] == [30, 10]


def test_run_bucket_values_are_durations_in_seconds(tmp_path: Path) -> None:
    connection = state_series(tmp_path, "0111011110")

    bucket = bucketed_runs(
        connection,
        "sensor_compressor",
        asserted=True,
        interval=timedelta(hours=1),
        local=False,
    )[0]

    assert (bucket.minimum, bucket.maximum, bucket.mean) == (120.0, 180.0, 150.0)


def test_a_run_falls_in_the_bucket_it_started_in(tmp_path: Path) -> None:
    """A cycle spanning midnight belongs to the day it began."""

    connection = state_series(tmp_path, "0" * 59 + "1" * 5, every=timedelta(minutes=1))

    buckets = bucketed_runs(
        connection,
        "sensor_compressor",
        asserted=True,
        interval=timedelta(hours=1),
        local=False,
    )

    assert len(buckets) == 1
    assert buckets[0].starts_at == START
    assert buckets[0].count == 1


def test_runs_and_duty_cycle_answer_different_questions(tmp_path: Path) -> None:
    """Identical duty cycles, opposite cycling behaviour. The duty cycle cannot tell."""

    steady_path = tmp_path / "steady"
    chattering_path = tmp_path / "chattering"
    steady_path.mkdir()
    chattering_path.mkdir()

    steady = state_series(steady_path, "1" * 20 + "0" * 20)
    chattering = state_series(chattering_path, "10" * 20)

    assert duty_cycle(steady, "sensor_compressor") == duty_cycle(
        chattering, "sensor_compressor"
    )
    assert len(runs(steady, "sensor_compressor", asserted=True)) == 1
    assert len(runs(chattering, "sensor_compressor", asserted=True)) == 20


def test_a_report_can_be_produced_while_recording_continues(tmp_path: Path) -> None:
    """WAL permits concurrent readers, which is what makes a live check possible."""

    database = tmp_path / "geopilot.sqlite3"

    with SqliteMeasurementHistorian(database) as historian:
        historian.append(measurement(index=0))

        with closing(open_readonly(database)) as reader:
            assert coverage(reader)[0].count == 1

        historian.append(measurement(index=1))

        with closing(open_readonly(database)) as reader:
            assert coverage(reader)[0].count == 2
