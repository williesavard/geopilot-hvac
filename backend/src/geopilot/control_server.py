"""A local HTTP surface for operating relays.

This is the first thing in GeoPilot that **listens**, and everything about it is
shaped by that. A static page can display; it cannot command, because a file has
no back channel. Commanding needs a process on a socket, and a socket that can
close a contactor deserves more care than one that serves a chart.

What protects it, in order of what actually stops an attack:

- **it binds to the loopback interface.** Nothing off the machine can reach it
  unless somebody deliberately changes that, and the tool says so loudly if they
  do;
- **it checks `Host`.** A browser can be tricked into resolving an attacker's
  domain to 127.0.0.1 — DNS rebinding — and then it is *the browser* making the
  request, from inside. A `Host` header that is not a loopback name is refused;
- **it checks `Origin`.** Any page on the internet can submit a form to
  `http://127.0.0.1:8000/`, and the browser will send it. Cross-origin requests
  are refused rather than obeyed;
- **it requires a token** minted at startup and embedded in the page it serves.
  A request that never saw the page cannot have it.

Beyond the door, nothing here decides anything. Every command goes through
`ControlService`, which is where the policy, the whitelist, the rate limit and
the audit journal live. This module's job is to be a careful doorway.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit

from geopilot.control import (
    CommandRecord,
    CommandRequest,
    CommandStatus,
    ControlPolicy,
    ControlService,
    InMemoryCommandJournal,
)

LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "[::1]", "::1"})
"""Host names that mean this machine.

A request arriving with any other `Host` reached us through a name we did not
expect, which is what DNS rebinding looks like from the inside.
"""

MAX_BODY_BYTES = 8 * 1024
"""A command is a few hundred bytes. Anything larger is not one."""

CONTENT_SECURITY_POLICY = (
    "default-src 'none'; "
    "style-src 'unsafe-inline'; "
    "script-src 'unsafe-inline'; "
    "connect-src 'self'; "
    "frame-ancestors 'none'"
)
"""What the page is allowed to do, which is almost nothing.

`unsafe-inline` looks alarming and is the honest description: the styles and the
script are inlined so the page stays one file. What matters here is the rest —
`default-src 'none'` means it can fetch nothing, `connect-src 'self'` means its
only back channel is this server, and `frame-ancestors 'none'` means no other
page can wrap it and click through it.
"""


class ControlSurfaceError(RuntimeError):
    """Raised when the surface cannot be built."""


@dataclass(frozen=True, slots=True)
class TargetView:
    """One relay as the page sees it.

    `state` is what the device just said, or None when it could not be asked.
    **It is never what was last commanded.** A controller that shows its own
    intentions back to itself cannot notice that a contact did not move.
    """

    target_id: str
    description: str
    state: bool | None
    detail: str


StateReader = Callable[[str], bool | None]
"""Reads a target's actual coil back from the bus. None when unreachable."""

Prober = Callable[[], list[dict[str, Any]]]
"""Reads every configured sensor from the hardware right now.

Injected rather than built here, because probing needs serial ports and this
module deliberately knows nothing about them.
"""

PageBuilder = Callable[[str], str]
"""Builds the HTML for the surface, given the session token."""


class ControlSurface:
    """The decisions behind the doorway, with no HTTP in them.

    Kept apart from the request handler so every rule below can be tested by
    calling a method, without a socket.
    """

    def __init__(
        self,
        service: ControlService,
        policy: ControlPolicy,
        *,
        page: PageBuilder,
        read_state: StateReader | None = None,
        probe: Prober | None = None,
        token: str | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._service = service
        self._policy = policy
        self._page = page
        self._read_state = read_state
        self._probe = probe
        self._token = token or secrets.token_urlsafe(32)
        self._clock = clock or _utc_now

    @property
    def token(self) -> str:
        """The secret the page is served with and commands must return."""

        return self._token

    def html(self) -> str:
        """Render the page, with the token embedded."""

        return self._page(self._token)

    def targets(self) -> tuple[TargetView, ...]:
        """Report every permitted target, asking the bus for its actual state."""

        views = []
        for target in self._policy.targets:
            state: bool | None = None
            detail = "not read back"
            if self._read_state is not None:
                try:
                    state = self._read_state(target.target_id)
                    detail = "" if state is not None else "unreachable"
                except Exception as error:  # noqa: BLE001 - a bus fault is data here
                    detail = f"unreachable: {error}"
            views.append(
                TargetView(
                    target_id=target.target_id,
                    description=target.description,
                    state=state,
                    detail=detail,
                )
            )
        return tuple(views)

    def state(self) -> dict[str, Any]:
        """The whole picture the page needs, in one response."""

        return {
            "enabled": self._policy.enabled,
            "generated_at": self._clock().isoformat(),
            "targets": [
                {
                    "target_id": view.target_id,
                    "description": view.description,
                    "state": view.state,
                    "detail": view.detail,
                }
                for view in self.targets()
            ],
            "journal": [record.to_dict() for record in self.recent()],
        }

    def probe(self) -> tuple[HTTPStatus, dict[str, Any]]:
        """Read every configured sensor from the hardware, now.

        A read, not a command, so it does not go through the guard — but it does
        go through the same doorway, because it holds the serial port for a
        moment and anything that can do that should have to prove it loaded the
        page.

        A bus fault is the answer, not an exception: the whole point is to find
        out what is broken.
        """

        if self._probe is None:
            return HTTPStatus.NOT_IMPLEMENTED, {
                "error": "this surface was started without a prober"
            }

        try:
            results = self._probe()
        except Exception as error:  # noqa: BLE001 - a bus fault is the answer here
            return HTTPStatus.OK, {
                "results": [],
                "error": f"the probe itself failed: {error}",
            }

        return HTTPStatus.OK, {"results": results, "probed_at": self._clock().isoformat()}

    def recent(self, limit: int = 20) -> tuple[CommandRecord, ...]:
        """The last few command attempts, newest last."""

        journal = self._service.journal
        records = getattr(journal, "records", None)
        if records is None:
            return ()
        return tuple(records[-limit:])

    def command(self, payload: dict[str, Any]) -> tuple[HTTPStatus, dict[str, Any]]:
        """Validate a request body and hand it to the guard.

        Malformed input is rejected here. Everything well formed is passed on,
        including commands that will be refused: a refusal is an outcome worth
        journalling, and swallowing it early would hide it.
        """

        target_id = payload.get("target_id")
        closed = payload.get("closed")
        reason = payload.get("reason")

        if not isinstance(target_id, str) or not target_id.strip():
            return HTTPStatus.BAD_REQUEST, {"error": "target_id is required"}
        if not isinstance(closed, bool):
            return HTTPStatus.BAD_REQUEST, {"error": "closed must be true or false"}
        if not isinstance(reason, str) or not reason.strip():
            return HTTPStatus.BAD_REQUEST, {
                "error": "reason is required; a command with no stated reason is undebuggable"
            }

        record = self._service.execute(
            CommandRequest(
                command_id=f"ui-{secrets.token_hex(8)}",
                target_id=target_id,
                closed=closed,
                reason=reason.strip(),
            )
        )

        status = HTTPStatus.OK if record.status is CommandStatus.APPLIED else HTTPStatus.CONFLICT
        return status, {"record": record.to_dict()}

    def authorised(self, *, host: str | None, origin: str | None, token: str | None) -> str | None:
        """Return None when a request may proceed, or why it may not.

        Order matters only for the message. All three tests must pass.
        """

        if not _is_loopback(host):
            return "unexpected Host header"
        if origin is not None and not _is_loopback(urlsplit(origin).netloc):
            return "cross-origin request"
        if token is None or not secrets.compare_digest(token, self._token):
            return "missing or invalid token"
        return None


def _is_loopback(host: str | None) -> bool:
    if not host:
        return False
    name = host.rsplit(":", 1)[0] if host.count(":") == 1 else host
    return name.strip().lower() in LOOPBACK_HOSTS


def build_handler(surface: ControlSurface) -> type[BaseHTTPRequestHandler]:
    """Build a request handler bound to one surface."""

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "GeoPilot"
        sys_version = ""

        def do_GET(self) -> None:  # noqa: N802 - http.server's contract
            path = urlsplit(self.path).path

            if path == "/":
                # The page itself carries the token, so it cannot require one.
                # It is still Host-checked, and it commands nothing by loading.
                if not _is_loopback(self.headers.get("Host")):
                    self._json(HTTPStatus.FORBIDDEN, {"error": "unexpected Host header"})
                    return
                self._send(HTTPStatus.OK, "text/html; charset=utf-8", surface.html().encode())
                return

            if path == "/api/state":
                if not self._guard():
                    return
                self._json(HTTPStatus.OK, surface.state())
                return

            self._json(HTTPStatus.NOT_FOUND, {"error": "no such resource"})

        def do_POST(self) -> None:  # noqa: N802 - http.server's contract
            path = urlsplit(self.path).path

            if path == "/api/probe":
                if not self._guard():
                    return
                # POST because it reaches out to hardware. A GET would be fair
                # game for a prefetcher, and this one occupies a serial bus.
                status, body = surface.probe()
                self._json(status, body)
                return

            if path != "/api/command":
                self._json(HTTPStatus.NOT_FOUND, {"error": "no such resource"})
                return
            if not self._guard():
                return

            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self._json(HTTPStatus.BAD_REQUEST, {"error": "bad Content-Length"})
                return
            if length > MAX_BODY_BYTES:
                self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "body too large"})
                return

            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
            except (ValueError, OSError):
                self._json(HTTPStatus.BAD_REQUEST, {"error": "body must be JSON"})
                return
            if not isinstance(payload, dict):
                self._json(HTTPStatus.BAD_REQUEST, {"error": "body must be a JSON object"})
                return

            status, body = surface.command(payload)
            self._json(status, body)

        def _guard(self) -> bool:
            refusal = surface.authorised(
                host=self.headers.get("Host"),
                origin=self.headers.get("Origin"),
                token=self.headers.get("X-GeoPilot-Token"),
            )
            if refusal is None:
                return True
            self._json(HTTPStatus.FORBIDDEN, {"error": refusal})
            return False

        def _json(self, status: HTTPStatus, body: dict[str, Any]) -> None:
            self._send(status, "application/json", json.dumps(body).encode())

        def _send(self, status: HTTPStatus, content_type: str, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            # The page loads nothing and belongs in no frame; saying so is cheap.
            self.send_header("Content-Security-Policy", CONTENT_SECURITY_POLICY)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            # http.server logs to stderr by default, which under systemd means
            # every poll of the page lands in the journal. Silence by default.
            return

    return Handler


def serve(
    surface: ControlSurface,
    *,
    host: str = "127.0.0.1",
    port: int = 8322,
) -> ThreadingHTTPServer:
    """Build a server. The caller starts it, so tests can drive it directly."""

    return ThreadingHTTPServer((host, port), build_handler(surface))


def build_service(
    policy: ControlPolicy,
    transport: Any = None,
    *,
    journal: Any = None,
) -> ControlService:
    """Assemble a guard with an in-memory journal by default."""

    return ControlService(policy, transport, journal=journal or InMemoryCommandJournal())


def open_database(path: str) -> sqlite3.Connection:
    """Open the recording read-only for the charts the surface also serves."""

    from geopilot.reporting import open_readonly

    return open_readonly(path)


def _utc_now() -> datetime:
    return datetime.now(UTC)
