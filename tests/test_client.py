"""HTTP, authentication, redirect, and read-only endpoint tests."""

from __future__ import annotations

import json
import logging
import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar
from urllib.error import URLError

import pytest

from codex_lb_status.client import (
    ALLOWED_REQUESTS,
    AuthenticationError,
    AuthenticationRequired,
    CodexLBClient,
    ContentTypeFailure,
    ContractFailure,
    HTTPFailure,
    JsonFailure,
    NetworkError,
    RedirectFailure,
    RequestTimeout,
    ResponseTooLarge,
    TLSFailure,
    TotpRequired,
    _safe_body,
)
from codex_lb_status.sessions import SessionCookieStore


def session_json(
    authenticated: bool,
    role: str = "admin",
    *,
    password_required: bool = True,
    totp_required: bool = False,
) -> dict[str, object]:
    return {
        "authenticated": authenticated,
        "passwordRequired": password_required,
        "totpRequiredOnLogin": totp_required,
        "totpConfigured": totp_required,
        "bootstrapRequired": False,
        "bootstrapTokenConfigured": False,
        "authMode": "standard",
        "passwordManagementEnabled": True,
        "passwordSessionActive": authenticated and role == "admin",
        "role": role,
        "permissions": ["read", "write"] if role == "admin" else ["read"],
        "guestAccessEnabled": True,
        "guestPasswordRequired": False,
    }


class DashboardHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    requests: ClassVar[list[tuple[str, str, bytes, dict[str, str]]]] = []
    require_totp = False
    no_auth = False
    send_redirect = False
    error_content_type = False
    error_status = 200
    error_retry_after: str | None = None
    invalid_session_body = False
    session_permissions: ClassVar[list[str] | None] = None
    response_extensions: ClassVar[dict[str, object]] = {}
    accounts_response_override: ClassVar[dict[str, object] | None] = None
    admin_response_override: dict[str, object] | None = None
    guest_response_override: dict[str, object] | None = None
    totp_response_override: dict[str, object] | None = None

    def log_message(self, format, *args):
        return

    def _body(self) -> bytes:
        length = int(self.headers.get("Content-Length", "0"))
        return self.rfile.read(length)

    def _send(
        self,
        status: int,
        body: object,
        cookie: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        if isinstance(body, dict):
            body = {**body, **self.response_extensions}
        if (
            isinstance(body, dict)
            and "authenticated" in body
            and self.session_permissions is not None
        ):
            body = {**body, "permissions": self.session_permissions}
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header(
            "Content-Type",
            "text/plain" if self.error_content_type else "application/json",
        )
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("X-App-Version", "test-server")
        if cookie:
            self.send_header(
                "Set-Cookie",
                f"codex_lb_dashboard_session={cookie}; Path=/",
            )
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(payload)

    def _record(self, body: bytes) -> None:
        self.requests.append(
            (
                self.command,
                self.path,
                body,
                {key.lower(): value for key, value in self.headers.items()},
            )
        )

    def do_GET(self):
        body = b""
        self._record(body)
        if self.send_redirect:
            self.send_response(302)
            self.send_header("Location", "/api/accounts")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        authenticated = "codex_lb_dashboard_session=valid" in self.headers.get(
            "Cookie", ""
        )
        if self.path == "/api/dashboard-auth/session":
            if self.error_status != 200:
                self._send(
                    self.error_status,
                    {"password": "secret"},
                    headers=(
                        {"Retry-After": self.error_retry_after}
                        if self.error_retry_after
                        else None
                    ),
                )
                return
            if self.invalid_session_body:
                self._send(200, {"unexpected": True})
                return
            self._send(
                200,
                session_json(
                    authenticated or self.no_auth,
                    password_required=not self.no_auth,
                ),
            )
        elif self.path == "/api/accounts":
            if not self.no_auth and not authenticated:
                self._send(401, {"error": "login required"})
            else:
                self._send(200, self.accounts_response_override or {"accounts": []})
        else:
            self._send(404, {"error": "unknown"})

    def do_POST(self):
        body = self._body()
        self._record(body)
        payload = json.loads(body) if body else None
        if self.path == "/api/dashboard-auth/password/login":
            if payload != {"password": "secret"}:
                self._send(
                    401,
                    {
                        "error": {
                            "code": "invalid_credentials",
                            "message": "Invalid credentials",
                        }
                    },
                )
            elif self.admin_response_override is not None:
                self._send(200, self.admin_response_override, "valid")
            elif self.require_totp:
                self._send(
                    200,
                    session_json(False, totp_required=True),
                    "intermediate",
                )
            else:
                self._send(200, session_json(True), "valid")
        elif self.path == "/api/dashboard-auth/totp/verify":
            if payload != {"code": "123456"}:
                self._send(
                    400,
                    {
                        "error": {
                            "code": "invalid_totp_code",
                            "message": "Invalid TOTP code",
                        }
                    },
                )
            elif self.totp_response_override is not None:
                self._send(200, self.totp_response_override, "valid")
            else:
                self._send(200, session_json(True), "valid")
        elif self.path == "/api/dashboard-auth/guest/login":
            if payload not in (None, {"password": "guest"}):
                self._send(
                    401,
                    {
                        "error": {
                            "code": "invalid_credentials",
                            "message": "Invalid guest credentials",
                        }
                    },
                )
            elif self.guest_response_override is not None:
                self._send(200, self.guest_response_override, "valid")
            else:
                self._send(200, session_json(True, "guest"), "valid")
        else:
            self._send(404, {"error": "unknown"})


@pytest.fixture
def server():
    DashboardHandler.requests = []
    DashboardHandler.require_totp = False
    DashboardHandler.no_auth = False
    DashboardHandler.send_redirect = False
    DashboardHandler.error_content_type = False
    DashboardHandler.error_status = 200
    DashboardHandler.error_retry_after = None
    DashboardHandler.invalid_session_body = False
    DashboardHandler.session_permissions = None
    DashboardHandler.response_extensions = {}
    DashboardHandler.accounts_response_override = None
    DashboardHandler.admin_response_override = None
    DashboardHandler.guest_response_override = None
    DashboardHandler.totp_response_override = None
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), DashboardHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}", DashboardHandler
    finally:
        httpd.shutdown()
        thread.join(timeout=2)
        httpd.server_close()


def make_client(base_url: str, tmp_path: Path) -> CodexLBClient:
    return CodexLBClient(base_url, SessionCookieStore(tmp_path / "sessions"))


def test_no_auth_dashboard_loads_without_prompting(server, tmp_path) -> None:
    base_url, handler = server
    handler.no_auth = True
    client = make_client(base_url, tmp_path)
    payload = client.refresh()
    assert payload.accounts.accounts == ()
    assert not any(path.endswith("password/login") for _, path, *_ in handler.requests)


@pytest.mark.parametrize("mode", ["disabled", "admin", "totp", "guest"])
@pytest.mark.parametrize("scoped_permissions", [False, True], ids=["legacy", "beta9"])
def test_refresh_and_login_accept_legacy_and_scoped_permissions(
    server, tmp_path, mode, scoped_permissions
) -> None:
    base_url, handler = server
    permissions = ["read"]
    if mode != "guest":
        permissions += ["write"]
    if scoped_permissions:
        permissions += ["accounts:read:all", "dashboard:read:all"]
        if mode != "guest":
            permissions += ["accounts:write:all", "users:manage:all"]
    handler.session_permissions = permissions
    client = make_client(base_url, tmp_path)
    if mode == "disabled":
        handler.no_auth = True
    elif mode == "guest":
        assert client.login_guest().permissions == tuple(permissions)
    elif mode == "totp":
        handler.require_totp = True
        pending = client.start_admin_login("secret")
        assert pending.totp_required_on_login
        assert pending.permissions == tuple(permissions)
        assert not list(client.session_store.load(base_url))
        assert client.verify_totp("123456").permissions == tuple(permissions)
    else:
        assert client.login_admin("secret").permissions == tuple(permissions)

    payload = client.refresh()

    assert payload.session.authenticated
    assert payload.session.permissions == tuple(permissions)
    assert payload.accounts.accounts == ()


def test_beta9_expired_session_exposes_login_required(server, tmp_path) -> None:
    base_url, handler = server
    handler.session_permissions = ["read", "write", "accounts:read:all"]
    client = make_client(base_url, tmp_path)

    with pytest.raises(AuthenticationRequired) as raised:
        client.refresh()

    assert raised.value.session is not None
    assert not raised.value.session.authenticated
    assert raised.value.session.password_required
    assert raised.value.session.permissions == tuple(handler.session_permissions)


@pytest.mark.parametrize("mode", ["disabled", "admin", "totp", "guest"])
def test_api_additions_do_not_block_refresh_or_sign_in(server, tmp_path, mode) -> None:
    base_url, handler = server
    handler.response_extensions = {"futureField": {"new": [1, None, True]}}
    handler.session_permissions = ["read", "future_permission", "accounts:read:team"]
    handler.accounts_response_override = {
        "accounts": [
            {
                "accountId": "future",
                "email": "future@example.com",
                "displayName": "Future account",
                "planType": "future_plan",
                "status": "future_status",
                "routingPolicy": "future_policy",
                "usage": {"primaryRemainingPercent": 50, "futureWindow": {}},
                "futureField": {"unknown": []},
            }
        ]
    }
    client = make_client(base_url, tmp_path)
    if mode == "disabled":
        handler.no_auth = True
    elif mode == "guest":
        assert client.login_guest().authenticated
    elif mode == "totp":
        handler.require_totp = True
        assert client.start_admin_login("secret").totp_required_on_login
        assert client.verify_totp("123456").authenticated
    else:
        assert client.login_admin("secret").authenticated

    payload = client.refresh()

    assert payload.session.permissions == tuple(handler.session_permissions)
    assert payload.accounts.accounts[0].status == "future_status"
    assert payload.accounts.accounts[0].routing_policy == "future_policy"
    assert payload.accounts.accounts[0].usage.primary_remaining_percent == 50


@pytest.mark.parametrize("field", ["role", "authMode"])
def test_refresh_accepts_new_session_metadata_labels(server, tmp_path, field) -> None:
    base_url, handler = server
    handler.no_auth = True
    handler.response_extensions = {field: "future_value"}

    payload = make_client(base_url, tmp_path).refresh()

    attribute = "role" if field == "role" else "auth_mode"
    assert getattr(payload.session, attribute) == "future_value"
    assert payload.session.authenticated


def test_admin_login_persists_cookie_only_after_success(server, tmp_path) -> None:
    base_url, _ = server
    client = make_client(base_url, tmp_path)
    session = client.login_admin("secret")
    assert session.authenticated
    assert list(client.session_store.load(base_url))


def test_clear_session_signs_out_only_the_local_companion(server, tmp_path) -> None:
    base_url, handler = server
    client = make_client(base_url, tmp_path)
    assert client.login_admin("secret").authenticated
    assert list(client.session_store.load(base_url))

    client.clear_session()

    assert list(client.session_store.load(base_url)) == []
    assert not client.get_session().authenticated
    assert not any(path.endswith("logout") for _, path, *_ in handler.requests)


def test_totp_requires_code_and_failed_code_is_not_persisted(server, tmp_path) -> None:
    base_url, handler = server
    handler.require_totp = True
    client = make_client(base_url, tmp_path)
    with pytest.raises(TotpRequired):
        client.login_admin("secret")
    assert list(client.session_store.load(base_url)) == []
    with pytest.raises(AuthenticationError) as raised:
        client.verify_totp("wrong")
    assert raised.value.status_code == 400
    assert raised.value.error_code == "invalid_totp_code"
    assert list(client.session_store.load(base_url)) == []
    client.start_admin_login("secret")
    assert client.verify_totp("123456").authenticated
    assert list(client.session_store.load(base_url))


def test_passwordless_and_password_guest_login_have_expected_bodies(
    server, tmp_path
) -> None:
    base_url, handler = server
    client = make_client(base_url, tmp_path)
    client.login_guest()
    client.login_guest("guest")
    guest_requests = [
        item for item in handler.requests if item[1].endswith("guest/login")
    ]
    assert guest_requests[0][2] == b""
    assert json.loads(guest_requests[1][2]) == {"password": "guest"}


def test_401_clears_session_and_exposes_login_required(
    server, tmp_path, caplog
) -> None:
    base_url, _ = server
    client = make_client(base_url, tmp_path)
    caplog.set_level(logging.INFO, logger="codex_lb_status")
    with pytest.raises(AuthenticationRequired):
        client.refresh()
    assert list(client.session_store.load(base_url)) == []
    events = [record.diagnostic_event for record in caplog.records]
    assert "refresh_authentication_failure" in events
    assert "session_local_state_cleared" in events
    assert all("login required" not in record.getMessage() for record in caplog.records)


def test_redirects_are_rejected(server, tmp_path) -> None:
    base_url, handler = server
    handler.send_redirect = True
    with pytest.raises(RedirectFailure):
        make_client(base_url, tmp_path).get_session()


def test_non_json_success_is_rejected(server, tmp_path) -> None:
    base_url, handler = server
    handler.error_content_type = True
    with pytest.raises(ContentTypeFailure):
        make_client(base_url, tmp_path).get_session()


def test_http_error_does_not_expose_password(server, tmp_path) -> None:
    base_url, handler = server
    handler.error_status = 500
    client = make_client(base_url, tmp_path)
    with pytest.raises(HTTPFailure) as raised:
        client.get_session()
    assert "secret" not in str(raised.value)


def test_error_redaction_is_recursive_and_rejects_unstructured_text() -> None:
    body = json.dumps(
        {"error": {"context": [{"accessToken": "nested-secret"}]}}
    ).encode()

    assert "nested-secret" not in _safe_body(body)
    assert "plain-text-secret" not in _safe_body(b"plain-text-secret")


def test_dashboard_error_preserves_status_code_and_retry_after(
    server, tmp_path
) -> None:
    base_url, handler = server
    handler.error_status = 429
    handler.error_retry_after = "17"
    with pytest.raises(HTTPFailure) as raised:
        make_client(base_url, tmp_path).get_session()
    assert raised.value.status_code == 429
    assert raised.value.retry_after == "17"


def test_login_cookies_require_the_expected_authenticated_role(
    server, tmp_path
) -> None:
    base_url, handler = server

    handler.admin_response_override = session_json(True, "guest")
    admin = make_client(base_url, tmp_path / "admin")
    with pytest.raises(AuthenticationError):
        admin.login_admin("secret")
    assert list(admin.session_store.load(base_url)) == []

    handler.admin_response_override = None
    handler.guest_response_override = session_json(True, "admin")
    guest = make_client(base_url, tmp_path / "guest")
    with pytest.raises(AuthenticationError):
        guest.login_guest()
    assert list(guest.session_store.load(base_url)) == []

    handler.guest_response_override = None
    handler.require_totp = True
    handler.totp_response_override = session_json(False, "admin")
    totp = make_client(base_url, tmp_path / "totp")
    totp.start_admin_login("secret")
    with pytest.raises(AuthenticationError):
        totp.verify_totp("123456")
    assert list(totp.session_store.load(base_url)) == []


def test_invalid_json_contract_and_oversized_responses_are_rejected(
    server, tmp_path
) -> None:
    base_url, handler = server
    handler.invalid_session_body = True
    with pytest.raises(ContractFailure):
        make_client(base_url, tmp_path).get_session()

    class LargeHandler(DashboardHandler):
        def _send(self, status, body, cookie=None):
            payload = b"{" + b'"x":"' + b"x" * (1_048_576 + 1) + b'"}'
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    large = ThreadingHTTPServer(("127.0.0.1", 0), LargeHandler)
    thread = threading.Thread(target=large.serve_forever, daemon=True)
    thread.start()
    try:
        client = make_client(f"http://127.0.0.1:{large.server_port}", tmp_path)
        with pytest.raises(ResponseTooLarge):
            client.get_session()
    finally:
        large.shutdown()
        thread.join(timeout=2)
        large.server_close()


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (TimeoutError(), RequestTimeout),
        (URLError(TimeoutError()), RequestTimeout),
        (URLError(ssl.SSLError("bad tls")), TLSFailure),
        (URLError("dns failure"), NetworkError),
        (OSError("network"), NetworkError),
    ],
)
def test_transport_failures_are_mapped_without_details(
    tmp_path, failure, expected
) -> None:
    class FailingOpener:
        def open(self, request, timeout):
            raise failure

    client = CodexLBClient(
        "https://example.com",
        SessionCookieStore(tmp_path / "sessions"),
        opener_factory=lambda _cookies: FailingOpener(),
    )
    with pytest.raises(expected):
        client.get_session()


def test_json_failure_is_mapped() -> None:
    from email.message import Message

    class Response:
        status = 200
        headers = Message()
        closed = False

        def __init__(self):
            self.headers["Content-Type"] = "application/json"

        def read(self, limit):
            return b"not json"

        def close(self):
            self.closed = True

    class Opener:
        def open(self, request, timeout):
            return response

    response = Response()
    client = CodexLBClient(
        "https://example.com",
        opener_factory=lambda _cookies: Opener(),
    )
    with pytest.raises(JsonFailure):
        client.get_session()
    assert response.closed


def test_endpoint_allowlist_is_exactly_read_only_five_requests() -> None:
    assert {
        ("GET", "/api/dashboard-auth/session"),
        ("GET", "/api/accounts"),
        ("POST", "/api/dashboard-auth/password/login"),
        ("POST", "/api/dashboard-auth/guest/login"),
        ("POST", "/api/dashboard-auth/totp/verify"),
    } == ALLOWED_REQUESTS
