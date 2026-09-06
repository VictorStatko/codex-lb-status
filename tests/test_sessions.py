"""Origin isolation and persistence tests for dashboard sessions."""

from __future__ import annotations

import os
from http.cookiejar import Cookie

from codex_lb_status.sessions import (
    SessionCookieStore,
    SessionError,
    origin_hash,
    session_path,
)


def cookie(
    name: str,
    value: str,
    domain: str,
    expires: int | None = None,
    port: str | None = None,
    secure: bool = False,
) -> Cookie:
    return Cookie(
        version=0,
        name=name,
        value=value,
        port=port,
        port_specified=port is not None,
        domain=domain,
        domain_specified=False,
        domain_initial_dot=False,
        path="/",
        path_specified=True,
        secure=secure,
        expires=expires,
        discard=expires is None,
        comment=None,
        comment_url=None,
        rest={},
        rfc2109=False,
    )


def test_origins_get_distinct_hashes_and_cookie_files(tmp_path) -> None:
    first = "https://example.com"
    second = "https://other.example.com"
    assert origin_hash(first) != origin_hash(second)
    assert session_path(first, tmp_path) != session_path(second, tmp_path)


def test_cookie_jar_round_trips_with_restricted_permissions(tmp_path) -> None:
    store = SessionCookieStore(tmp_path / "sessions")
    jar = store.load("https://example.com")
    jar.set_cookie(cookie("session", "value", "example.com"))
    path = store.save("https://example.com", jar)
    loaded = store.load("https://example.com")
    assert [(item.name, item.value) for item in loaded] == [("session", "value")]
    assert os.stat(path.parent).st_mode & 0o777 == 0o700
    assert os.stat(path).st_mode & 0o777 == 0o600


def test_cross_origin_cookies_are_discarded(tmp_path) -> None:
    store = SessionCookieStore(tmp_path / "sessions")
    jar = store.load("https://example.com")
    jar.set_cookie(cookie("good", "1", "example.com"))
    jar.set_cookie(cookie("wrong", "2", "other.example.com"))
    store.save("https://example.com", jar)
    assert [item.name for item in store.load("https://example.com")] == ["good"]


def test_parent_domain_cookies_are_not_admitted_to_an_origin_store(tmp_path) -> None:
    store = SessionCookieStore(tmp_path / "sessions")
    jar = store.load("https://status.example.com")
    jar.set_cookie(cookie("parent", "1", ".example.com"))
    store.save("https://status.example.com", jar)

    assert list(store.load("https://status.example.com")) == []


def test_expired_cookies_are_discarded(tmp_path) -> None:
    store = SessionCookieStore(tmp_path / "sessions")
    jar = store.load("https://example.com")
    jar.set_cookie(cookie("expired", "1", "example.com", expires=1))
    store.save("https://example.com", jar)
    assert list(store.load("https://example.com")) == []


def test_invalid_cookie_file_is_rejected_without_being_sent(tmp_path) -> None:
    store = SessionCookieStore(tmp_path / "sessions")
    path = session_path("https://example.com", tmp_path / "sessions")
    path.parent.mkdir()
    path.write_text("invalid\tdata\n")

    try:
        store.load("https://example.com")
    except SessionError:
        pass
    else:
        raise AssertionError("invalid cookie file was accepted")


def test_secure_and_wrong_port_cookies_do_not_cross_origin(tmp_path) -> None:
    store = SessionCookieStore(tmp_path / "sessions")
    jar = store.load("http://127.0.0.1:2455")
    jar.set_cookie(cookie("secure", "1", "127.0.0.1", secure=True))
    jar.set_cookie(cookie("wrong-port", "2", "127.0.0.1", port="9999"))
    store.save("http://127.0.0.1:2455", jar)
    assert list(store.load("http://127.0.0.1:2455")) == []


def test_cookie_port_is_checked_against_the_default_origin_port(tmp_path) -> None:
    store = SessionCookieStore(tmp_path / "sessions")
    jar = store.load("https://example.com")
    jar.set_cookie(cookie("wrong-port", "1", "example.com", port="8443"))
    store.save("https://example.com", jar)

    assert list(store.load("https://example.com")) == []
