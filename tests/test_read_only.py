"""Guard the closed, read-only HTTP surface."""

from __future__ import annotations

from pathlib import Path

from codex_lb_status.client import ALLOWED_REQUESTS


def test_client_has_only_the_five_allowed_request_pairs() -> None:
    assert len(ALLOWED_REQUESTS) == 5
    assert all(method in {"GET", "POST"} for method, _path in ALLOWED_REQUESTS)
    assert not any(
        "/pause" in path
        or "/reactivate" in path
        or "routing-policy" in path
        or "/settings" in path
        for _method, path in ALLOWED_REQUESTS
    )


def test_no_account_mutation_routes_are_present_in_application_source() -> None:
    source = "\n".join(
        path.read_text() for path in Path("src/codex_lb_status").glob("*.py")
    )
    assert "/pause" not in source
    assert "/reactivate" not in source
    assert "routing-policy" not in source
