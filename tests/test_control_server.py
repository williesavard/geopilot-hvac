"""Control surface tests.

The guard's own rules are covered in `test_control.py`. What is tested here is
the doorway: who is allowed to knock, what a malformed knock does, and that the
state on the page came from the equipment rather than from memory.

No test opens a socket or a serial port.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from http import HTTPStatus

import pytest
from geopilot.control import (
    CommandStatus,
    ControlPolicy,
    ControlService,
    ControlTarget,
    InMemoryCommandJournal,
)
from geopilot.control_server import (
    CONTENT_SECURITY_POLICY,
    ControlSurface,
    build_handler,
)
from geopilot.modbus_write import FakeModbusWriteTransport

TOKEN = "test-token"
NOW = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)


def target(target_id: str = "target_zone_1", interval: float = 0.0) -> ControlTarget:
    return ControlTarget(
        target_id=target_id,
        unit_id=1,
        address=0,
        minimum_interval_seconds=interval,
        description="zone 1 damper",
    )


def surface(
    *,
    enabled: bool = True,
    targets: tuple[ControlTarget, ...] = (),
    transport: object | None = None,
    read_state: object = None,
) -> ControlSurface:
    policy = ControlPolicy(enabled=enabled, targets=targets or (target(),))
    service = ControlService(
        policy,
        transport if transport is not None else FakeModbusWriteTransport(),  # type: ignore[arg-type]
        journal=InMemoryCommandJournal(),
        clock=lambda: NOW,
    )
    return ControlSurface(
        service,
        policy,
        page=lambda token: f"<html>{token}</html>",
        read_state=read_state,  # type: ignore[arg-type]
        token=TOKEN,
        clock=lambda: NOW,
    )


def allowed(
    host: str | None = "127.0.0.1:8322",
    origin: str | None = None,
    token: str | None = TOKEN,
) -> str | None:
    return surface().authorised(host=host, origin=origin, token=token)


def test_a_loopback_request_with_the_token_is_allowed() -> None:
    assert allowed() is None
    assert allowed(host="localhost:8322") is None
    assert allowed(origin="http://127.0.0.1:8322") is None


def test_a_request_naming_another_host_is_refused() -> None:
    """DNS rebinding arrives from the browser, from inside, with a foreign Host."""

    assert allowed(host="evil.example.com") == "unexpected Host header"
    assert allowed(host="192.168.1.40:8322") == "unexpected Host header"
    assert allowed(host=None) == "unexpected Host header"


def test_a_cross_origin_request_is_refused() -> None:
    """Any page on the internet can post a form here. The browser will send it."""

    assert allowed(origin="https://evil.example.com") == "cross-origin request"


def test_a_request_without_the_token_is_refused() -> None:
    """A caller that never loaded the page cannot have the token."""

    assert allowed(token="") == "missing or invalid token"
    assert allowed(token="not-the-token") == "missing or invalid token"
    assert surface().authorised(host="127.0.0.1", origin=None, token=None) == (
        "missing or invalid token"
    )


def test_the_token_is_not_guessable_by_default() -> None:
    made = ControlSurface(
        ControlService(ControlPolicy()),
        ControlPolicy(),
        page=lambda token: token,
    )

    assert len(made.token) >= 32
    assert made.token != ControlSurface(
        ControlService(ControlPolicy()), ControlPolicy(), page=lambda token: token
    ).token


def test_the_page_carries_the_token() -> None:
    assert TOKEN in surface().html()


def test_state_is_read_back_from_the_bus(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never what was last commanded. That is the whole point of reading it."""

    asked: list[str] = []

    def read(target_id: str) -> bool:
        asked.append(target_id)
        return True

    made = surface(read_state=read)
    views = made.targets()

    assert asked == ["target_zone_1"]
    assert views[0].state is True
    assert views[0].detail == ""


def test_an_unreachable_relay_reads_as_unknown_not_as_open(tmp_path: object) -> None:
    """A silent bus is not an open contact, and must not be shown as one."""

    made = surface(read_state=lambda target_id: None)

    assert made.targets()[0].state is None
    assert made.targets()[0].detail == "unreachable"


def test_a_bus_fault_becomes_data_rather_than_a_crash() -> None:
    def explode(target_id: str) -> bool:
        raise OSError("port busy")

    made = surface(read_state=explode)

    assert made.targets()[0].state is None
    assert "port busy" in made.targets()[0].detail


def test_a_command_reaches_the_guard_and_is_applied() -> None:
    made = surface()

    status, body = made.command(
        {"target_id": "target_zone_1", "closed": True, "reason": "testing"}
    )

    assert status is HTTPStatus.OK
    assert body["record"]["status"] == CommandStatus.APPLIED.value


def test_a_refusal_is_reported_rather_than_hidden() -> None:
    """A refusal is an outcome worth journalling, not an error to swallow."""

    made = surface(enabled=False)

    status, body = made.command(
        {"target_id": "target_zone_1", "closed": True, "reason": "testing"}
    )

    assert status is HTTPStatus.CONFLICT
    assert body["record"]["status"] == CommandStatus.REFUSED.value
    assert made.recent()[-1].status is CommandStatus.REFUSED


def test_a_command_without_a_reason_is_rejected() -> None:
    made = surface()

    status, body = made.command({"target_id": "target_zone_1", "closed": True, "reason": "  "})

    assert status is HTTPStatus.BAD_REQUEST
    assert "reason is required" in str(body["error"])
    assert made.recent() == ()


def test_a_command_with_a_missing_target_is_rejected() -> None:
    made = surface()

    status, _ = made.command({"closed": True, "reason": "testing"})

    assert status is HTTPStatus.BAD_REQUEST


def test_a_command_whose_state_is_not_a_boolean_is_rejected() -> None:
    """`closed: "on"` must not be coerced into anything."""

    made = surface()

    for value in ("on", 1, None, "true"):
        status, _ = made.command(
            {"target_id": "target_zone_1", "closed": value, "reason": "testing"}
        )
        assert status is HTTPStatus.BAD_REQUEST


def test_an_unknown_target_is_refused_by_the_guard_not_by_the_doorway() -> None:
    made = surface()

    status, body = made.command(
        {"target_id": "target_absent", "closed": True, "reason": "testing"}
    )

    assert status is HTTPStatus.CONFLICT
    assert "unknown_target" in str(body["record"]["detail"])


def test_the_state_payload_says_whether_control_is_enabled() -> None:
    assert surface(enabled=True).state()["enabled"] is True
    assert surface(enabled=False).state()["enabled"] is False


def test_the_state_payload_carries_the_journal() -> None:
    made = surface()
    made.command({"target_id": "target_zone_1", "closed": True, "reason": "testing"})

    journal = made.state()["journal"]

    assert isinstance(journal, list)
    assert journal[-1]["target_id"] == "target_zone_1"


def test_the_policy_is_the_only_source_of_targets() -> None:
    """The page cannot invent a relay; it lists what the whitelist permits."""

    made = surface(targets=(target("target_a"), target("target_b")))

    assert [view.target_id for view in made.targets()] == ["target_a", "target_b"]


def test_the_content_security_policy_forbids_fetching_and_framing() -> None:
    assert "default-src 'none'" in CONTENT_SECURITY_POLICY
    assert "frame-ancestors 'none'" in CONTENT_SECURITY_POLICY
    assert "connect-src 'self'" in CONTENT_SECURITY_POLICY


def test_a_handler_can_be_built_without_binding_a_socket() -> None:
    handler = build_handler(surface())

    assert handler.protocol_version == "HTTP/1.1"


def test_the_page_is_built_on_the_thread_that_asks_for_it() -> None:
    """Requests are served on new threads, and a SQLite connection cannot cross one.

    The surface must therefore never close over a connection. Building the page
    on another thread is how that regression shows up before a socket does.
    """

    made = surface()
    seen: list[str] = []

    worker = threading.Thread(target=lambda: seen.append(made.html()))
    worker.start()
    worker.join()

    assert seen == [f"<html>{TOKEN}</html>"]


def test_a_probe_is_returned_through_the_surface() -> None:
    made = ControlSurface(
        ControlService(ControlPolicy()),
        ControlPolicy(),
        page=lambda token: token,
        probe=lambda: [{"label": "28-aaaa", "value": 21.5, "ok": True}],
        token=TOKEN,
        clock=lambda: NOW,
    )

    status, body = made.probe()

    assert status is HTTPStatus.OK
    assert body["results"][0]["label"] == "28-aaaa"
    assert "probed_at" in body


def test_probing_works_while_control_is_disabled() -> None:
    """Probing is a read, and a disabled surface is where it matters most."""

    made = ControlSurface(
        ControlService(ControlPolicy(enabled=False)),
        ControlPolicy(enabled=False),
        page=lambda token: token,
        probe=lambda: [{"label": "28-aaaa", "ok": True}],
        token=TOKEN,
    )

    status, body = made.probe()

    assert status is HTTPStatus.OK
    assert body["results"]


def test_a_probe_that_blows_up_becomes_an_answer() -> None:
    """Finding out what is broken is the point; crashing is not an answer."""

    def explode() -> list[dict[str, object]]:
        raise OSError("[Errno 16] Device or resource busy")

    made = ControlSurface(
        ControlService(ControlPolicy()),
        ControlPolicy(),
        page=lambda token: token,
        probe=explode,
        token=TOKEN,
    )

    status, body = made.probe()

    assert status is HTTPStatus.OK
    assert body["results"] == []
    assert "busy" in str(body["error"])


def test_a_surface_without_a_prober_says_so() -> None:
    status, body = surface().probe()

    assert status is HTTPStatus.NOT_IMPLEMENTED
    assert "without a prober" in str(body["error"])
