"""Small, read-only urllib client for the Codex LB dashboard API."""

from __future__ import annotations

import json
import socket
import ssl
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from http.cookiejar import CookieJar
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import (
    HTTPCookieProcessor,
    HTTPRedirectHandler,
    Request,
    build_opener,
)

from . import __version__
from .config import normalize_base_url
from .models import (
    AccountsResponse,
    DashboardSession,
    parse_accounts_response,
    parse_dashboard_session,
)
from .sessions import SessionCookieStore, SessionError

REQUEST_TIMEOUT = 10
MAX_RESPONSE_BYTES = 1_048_576
MAX_ERROR_BODY_BYTES = 4_096
USER_AGENT = f"codex-lb-status/{__version__}"
ALLOWED_REQUESTS = frozenset(
    {
        ("GET", "/api/dashboard-auth/session"),
        ("GET", "/api/accounts"),
        ("POST", "/api/dashboard-auth/password/login"),
        ("POST", "/api/dashboard-auth/guest/login"),
        ("POST", "/api/dashboard-auth/totp/verify"),
    }
)


class ClientError(RuntimeError):
    """Base class for safe, user-displayable client failures."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        error_code: str | None = None,
        retry_after: str | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.retry_after = retry_after


class NetworkError(ClientError):
    """The server could not be reached."""


class RequestTimeout(NetworkError):
    """The request exceeded the ten-second timeout."""


class TLSFailure(NetworkError):
    """TLS negotiation or certificate validation failed."""


class RedirectFailure(ClientError):
    """The endpoint attempted an HTTP redirect."""


class HTTPFailure(ClientError):
    """The server returned a non-success HTTP status."""


class AuthenticationError(ClientError):
    """The server rejected the current session or credentials."""


class AuthenticationRequired(AuthenticationError):
    """A refresh needs an interactive login."""

    def __init__(self, session: DashboardSession | None = None):
        super().__init__("dashboard login required")
        self.session = session


class TotpRequired(AuthenticationError):
    """Admin password was accepted and a TOTP code is now required."""


class ContentTypeFailure(ClientError):
    """The server response was not JSON."""


class ResponseTooLarge(ClientError):
    """The response exceeded the bounded client response size."""


class JsonFailure(ClientError):
    """The server response was not valid JSON."""


class ContractFailure(ClientError):
    """The JSON did not match the required dashboard contract."""


@dataclass(frozen=True, slots=True)
class RefreshPayload:
    session: DashboardSession
    accounts: AccountsResponse


_SENSITIVE_FIELD_MARKERS = ("password", "token", "secret", "cookie", "code")


def _redact_sensitive_fields(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: (
                "[redacted]"
                if isinstance(key, str)
                and any(marker in key.casefold() for marker in _SENSITIVE_FIELD_MARKERS)
                else _redact_sensitive_fields(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_sensitive_fields(item) for item in value]
    return value


def _safe_body(body: bytes) -> str:
    text = body[:MAX_ERROR_BODY_BYTES].decode("utf-8", errors="replace")
    # Error responses are server-controlled. Remove common credential fields
    # before the bounded detail can reach a label, exception, or log.
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return "server returned an error"
    if isinstance(value, dict):
        safe = _redact_sensitive_fields(value)
        return json.dumps(safe, ensure_ascii=True)[:MAX_ERROR_BODY_BYTES]
    return "server returned an error"


def _dashboard_error_details(body: bytes) -> tuple[str | None, str | None]:
    try:
        value = json.loads(body[:MAX_ERROR_BODY_BYTES].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, None
    if not isinstance(value, dict) or not isinstance(value.get("error"), dict):
        return None, None
    error = value["error"]
    raw_code = error.get("code")
    raw_message = error.get("message")
    code = raw_code.strip()[:128] if isinstance(raw_code, str) else None
    message = (
        " ".join(raw_message.split())[:512] if isinstance(raw_message, str) else None
    )
    return code or None, message or None


def _http_failure(
    method: str,
    path: str,
    status_code: int,
    headers,
    body: bytes,
) -> HTTPFailure:
    error_code, error_message = _dashboard_error_details(body)
    retry_after_value = headers.get("Retry-After") if headers is not None else None
    retry_after = (
        retry_after_value.strip()[:128]
        if isinstance(retry_after_value, str) and retry_after_value.strip()
        else None
    )
    suffix = ""
    if error_message:
        suffix = f": {error_message}"
    elif body:
        detail = _safe_body(body)
        suffix = f": {detail}" if detail else ""
    code_detail = f" ({error_code})" if error_code else ""
    message = f"{method} {path} failed with HTTP {status_code}{code_detail}{suffix}"
    failure_type = (
        AuthenticationError
        if status_code == 401 or error_code == "invalid_totp_code"
        else HTTPFailure
    )
    return failure_type(
        message,
        status_code=status_code,
        error_code=error_code,
        retry_after=retry_after,
    )


class _NoRedirectHandler(HTTPRedirectHandler):
    def _reject(
        self,
        request: Request,
        _file,
        code: int,
        _message: str,
        _headers,
        _newurl=None,
    ):
        raise RedirectFailure(f"HTTP redirect rejected for {request.full_url} ({code})")

    http_error_301 = _reject
    http_error_302 = _reject
    http_error_303 = _reject
    http_error_307 = _reject
    http_error_308 = _reject


class CodexLBClient:
    """A client with an intentionally closed and read-only endpoint set."""

    def __init__(
        self,
        base_url: str,
        session_store: SessionCookieStore | None = None,
        opener_factory: Callable[[CookieJar], Any] | None = None,
    ):
        self.base_url = normalize_base_url(base_url)
        self.session_store = session_store or SessionCookieStore()
        self._opener_factory = opener_factory
        try:
            self._cookies = self.session_store.load(self.base_url)
        except SessionError:
            self.session_store.clear(self.base_url)
            self._cookies = CookieJar()
        self._pending_admin_cookies: CookieJar | None = None
        self.server_version: str | None = None

    def _make_opener(self, cookies: CookieJar):
        if self._opener_factory is not None:
            return self._opener_factory(cookies)
        return build_opener(_NoRedirectHandler, HTTPCookieProcessor(cookies))

    def _url(self, path: str) -> str:
        if not path.startswith("/") or not any(
            (method, path) in ALLOWED_REQUESTS for method in ("GET", "POST")
        ):
            raise AssertionError(f"unsupported dashboard endpoint: {path}")
        return f"{self.base_url}{path}"

    def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        cookies: CookieJar | None = None,
    ) -> Any:
        if (method, path) not in ALLOWED_REQUESTS:
            raise AssertionError(f"unsupported dashboard request: {method} {path}")
        payload = None if body is None else json.dumps(body).encode("utf-8")
        request = Request(self._url(path), data=payload, method=method)
        request.add_header("Accept", "application/json")
        request.add_header("User-Agent", USER_AGENT)
        if payload is not None:
            request.add_header("Content-Type", "application/json")
        request_cookies = self._cookies if cookies is None else cookies
        opener = self._make_opener(request_cookies)
        try:
            with closing(opener.open(request, timeout=REQUEST_TIMEOUT)) as response:
                self.server_version = response.headers.get("X-App-Version")
                response_body = response.read(MAX_RESPONSE_BYTES + 1)
                if len(response_body) > MAX_RESPONSE_BYTES:
                    raise ResponseTooLarge("server response is too large")
                status = getattr(response, "status", None)
                if status is None:
                    status = response.getcode()
                headers = response.headers
        except HTTPError as error:
            try:
                self.server_version = error.headers.get("X-App-Version")
                error_body = error.read(MAX_ERROR_BODY_BYTES + 1)
            finally:
                error.close()
            raise _http_failure(
                method, path, error.code, error.headers, error_body
            ) from None
        except RedirectFailure:
            raise
        except ResponseTooLarge:
            raise
        except ssl.SSLError as error:
            raise TLSFailure("TLS connection to the dashboard failed") from error
        except TimeoutError:
            raise RequestTimeout(
                "dashboard request timed out after 10 seconds"
            ) from None
        except URLError as error:
            reason = error.reason
            if isinstance(reason, ssl.SSLError):
                raise TLSFailure("TLS connection to the dashboard failed") from error
            if isinstance(reason, (socket.timeout, TimeoutError)):
                raise RequestTimeout(
                    "dashboard request timed out after 10 seconds"
                ) from None
            raise NetworkError("cannot reach the Codex LB dashboard") from error
        except OSError as error:
            raise NetworkError("cannot reach the Codex LB dashboard") from error
        content_type = headers.get_content_type()
        if not content_type or not (
            content_type == "application/json" or content_type.endswith("+json")
        ):
            raise ContentTypeFailure("dashboard returned a non-JSON response")
        if not 200 <= status < 300:
            raise _http_failure(method, path, status, headers, response_body)
        try:
            return json.loads(response_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise JsonFailure("dashboard returned invalid JSON") from error

    def get_session(self) -> DashboardSession:
        try:
            return parse_dashboard_session(
                self._request("GET", "/api/dashboard-auth/session")
            )
        except ValueError as error:
            raise ContractFailure(
                "dashboard session response has an invalid shape"
            ) from error

    def get_accounts(self) -> AccountsResponse:
        try:
            return parse_accounts_response(self._request("GET", "/api/accounts"))
        except ValueError as error:
            raise ContractFailure(
                "dashboard accounts response has an invalid shape"
            ) from error

    def refresh(self) -> RefreshPayload:
        """Fetch session then accounts, retrying authorization state after 401."""

        session = self.get_session()
        try:
            accounts = self.get_accounts()
        except AuthenticationError as error:
            self.clear_session()
            try:
                fresh_session = self.get_session()
            except ClientError:
                fresh_session = session
            raise AuthenticationRequired(fresh_session) from error
        return RefreshPayload(session=session, accounts=accounts)

    def _persist_authenticated_cookies(self, cookies: CookieJar) -> None:
        self.session_store.save(self.base_url, cookies)
        self._cookies = cookies

    def start_admin_login(self, password: str) -> DashboardSession:
        if not isinstance(password, str) or not password:
            raise AuthenticationError("admin password is required")
        temporary = CookieJar()
        try:
            response = self._request(
                "POST",
                "/api/dashboard-auth/password/login",
                {"password": password},
                temporary,
            )
            session = parse_dashboard_session(response)
        except ValueError as error:
            raise ContractFailure(
                "admin login response has an invalid shape"
            ) from error
        if session.totp_required_on_login:
            if session.role != "admin" or session.authenticated:
                raise AuthenticationError(
                    "admin login returned an invalid pending TOTP session"
                )
            self._pending_admin_cookies = temporary
        else:
            if not session.authenticated or session.role != "admin":
                raise AuthenticationError(
                    "admin login did not return an authenticated admin session"
                )
            self._persist_authenticated_cookies(temporary)
        return session

    def verify_totp(self, code: str) -> DashboardSession:
        if self._pending_admin_cookies is None:
            raise AuthenticationError("no pending TOTP login")
        if not isinstance(code, str) or not code:
            raise AuthenticationError("TOTP code is required")
        pending = self._pending_admin_cookies
        try:
            response = self._request(
                "POST",
                "/api/dashboard-auth/totp/verify",
                {"code": code},
                pending,
            )
            session = parse_dashboard_session(response)
            if not session.authenticated or session.role != "admin":
                raise AuthenticationError(
                    "TOTP verification did not return an authenticated admin session"
                )
            self._persist_authenticated_cookies(pending)
            return session
        except AuthenticationError:
            raise
        except ValueError as error:
            raise ContractFailure("TOTP response has an invalid shape") from error
        finally:
            self._pending_admin_cookies = None

    def login_admin(
        self, password: str, totp_code: str | None = None
    ) -> DashboardSession:
        session = self.start_admin_login(password)
        if not session.totp_required_on_login:
            return session
        if totp_code is None:
            raise TotpRequired("TOTP code required to finish admin login")
        return self.verify_totp(totp_code)

    def login_guest(self, password: str | None = None) -> DashboardSession:
        temporary = CookieJar()
        body = {"password": password} if password else None
        try:
            response = self._request(
                "POST",
                "/api/dashboard-auth/guest/login",
                body,
                temporary,
            )
            session = parse_dashboard_session(response)
        except ValueError as error:
            raise ContractFailure(
                "guest login response has an invalid shape"
            ) from error
        if not session.authenticated or session.role != "guest":
            raise AuthenticationError(
                "guest login did not return an authenticated guest session"
            )
        self._persist_authenticated_cookies(temporary)
        return session

    def clear_session(self) -> None:
        self._pending_admin_cookies = None
        self._cookies = CookieJar()
        self.session_store.clear(self.base_url)


__all__ = [
    "ALLOWED_REQUESTS",
    "MAX_ERROR_BODY_BYTES",
    "USER_AGENT",
    "AuthenticationError",
    "AuthenticationRequired",
    "ClientError",
    "CodexLBClient",
    "ContentTypeFailure",
    "ContractFailure",
    "HTTPFailure",
    "JsonFailure",
    "NetworkError",
    "RedirectFailure",
    "RefreshPayload",
    "RequestTimeout",
    "ResponseTooLarge",
    "TLSFailure",
    "TotpRequired",
]
