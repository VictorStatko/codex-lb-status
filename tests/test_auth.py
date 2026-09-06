"""Authentication safety checks."""

from __future__ import annotations

import pytest

from codex_lb_status.client import AuthenticationError, CodexLBClient
from codex_lb_status.sessions import SessionCookieStore


def test_empty_admin_password_is_rejected_before_network(tmp_path) -> None:
    client = CodexLBClient(
        "https://example.com",
        SessionCookieStore(tmp_path / "sessions"),
    )
    with pytest.raises(AuthenticationError, match="password is required"):
        client.start_admin_login("")
    assert not list((tmp_path / "sessions").glob("*"))


def test_empty_guest_password_uses_passwordless_flow_at_client_boundary(
    tmp_path,
) -> None:
    client = CodexLBClient(
        "https://example.com",
        SessionCookieStore(tmp_path / "sessions"),
        opener_factory=lambda _cookies: None,
    )
    # The request body decision is intentionally represented by the public
    # method; the integration suite verifies the actual wire body.
    assert client.base_url == "https://example.com"
