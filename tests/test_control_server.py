"""Control surface tests.

The guard's own rules are covered in `test_control.py`. What is tested here is
the doorway: who is allowed to knock, what a malformed knock does, and that the
state on the page came from the equipment rather than from memory.

No test here opens a serial port. The block at the bottom does open a real
socket, deliberately: the one bug that reached main lived between the threaded
server and the journal, where no socketless test could see it.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from http import HTTPStatus
from http.client import HTTPConnection
from pathlib import Path
from typing import Any

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
    serve,
)
from geopilot.modbus_write import FakeModbusWriteTransport
from geopilot.sqlite_journal import SqliteCommandJournal

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


# --- Through a real socket ----------------------------------------------------
#
# Everything above tests the decisions; these test the doorway itself, because
# the one bug that reached main — the journal raising from a request thread —
# was invisible to any test that never started the ThreadingHTTPServer.


@pytest.fixture
def live_server(
    tmp_path: Path,
) -> Iterator[tuple[str, int, FakeModbusWriteTransport, SqliteCommandJournal]]:
    """A real server on an ephemeral loopback port, with the real journal."""

    transport = FakeModbusWriteTransport()
    journal = SqliteCommandJournal(tmp_path / "commands.sqlite3")
    policy = ControlPolicy(enabled=True, targets=(target(),))
    made = ControlSurface(
        ControlService(policy, transport, journal=journal),
        policy,
        page=lambda token: f"<html>{token}</html>",
        token=TOKEN,
    )
    server = serve(made, host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield str(server.server_address[0]), server.server_address[1], transport, journal
    finally:
        server.shutdown()
        server.server_close()
        journal.close()


def request(
    host: str,
    port: int,
    method: str,
    path: str,
    *,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, Any]]:
    connection = HTTPConnection(host, port, timeout=5)
    try:
        sent = {"Host": f"127.0.0.1:{port}", "X-GeoPilot-Token": TOKEN}
        sent.update(headers or {})
        connection.request(method, path, body=body, headers=sent)
        response = connection.getresponse()
        return response.status, json.loads(response.read() or b"{}")
    finally:
        connection.close()


def test_a_command_over_http_is_applied_and_journalled(
    live_server: tuple[str, int, FakeModbusWriteTransport, SqliteCommandJournal],
) -> None:
    """The regression that reached main: the request thread is not the thread
    that opened the journal, and the record must land anyway."""

    host, port, transport, journal = live_server

    status, body = request(
        host,
        port,
        "POST",
        "/api/command",
        body=json.dumps(
            {"target_id": "target_zone_1", "closed": True, "reason": "socket test"}
        ).encode(),
    )

    assert status == HTTPStatus.OK
    assert body["record"]["status"] == "applied"
    assert len(transport.writes) == 1
    assert journal.count() == 1
    assert journal.recent()[0].reason == "socket test"


def test_a_negative_content_length_is_refused(
    live_server: tuple[str, int, FakeModbusWriteTransport, SqliteCommandJournal],
) -> None:
    """read(-1) on a socket reads until the peer closes it: one header must not
    become an unbounded allocation."""

    host, port, transport, _ = live_server

    status, body = request(
        host, port, "POST", "/api/command", body=b"", headers={"Content-Length": "-1"}
    )

    assert status == HTTPStatus.BAD_REQUEST
    assert "Content-Length" in body["error"]
    assert transport.writes == []


def test_a_non_ascii_token_reads_as_wrong_not_as_a_crash(
    live_server: tuple[str, int, FakeModbusWriteTransport, SqliteCommandJournal],
) -> None:
    """`secrets.compare_digest` raises TypeError on non-ASCII strings, and a
    header is attacker-shaped input."""

    host, port, transport, _ = live_server

    status, body = request(
        host,
        port,
        "POST",
        "/api/command",
        body=b"{}",
        headers={"X-GeoPilot-Token": "jeton-piégé-é"},
    )

    assert status == HTTPStatus.FORBIDDEN
    assert body["error"] == "missing or invalid token"
    assert transport.writes == []
