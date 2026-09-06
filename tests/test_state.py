"""Small application-state invariants independent of Qt execution."""

from __future__ import annotations

from datetime import UTC, datetime

from codex_lb_status.models import (
    AccountSummary,
    ApplicationState,
    ApplicationStateKind,
)


def test_loading_state_is_empty_and_not_stale() -> None:
    state = ApplicationState.loading()
    assert state.kind is ApplicationStateKind.LOADING
    assert state.accounts == ()
    assert not state.has_data


def test_state_keeps_successful_data_metadata() -> None:
    account = AccountSummary(
        account_id="a",
        email="a@example.com",
        display_name="A",
        plan_type="plus",
        routing_policy="normal",
        status="active",
    )
    refreshed = datetime(2026, 9, 4, tzinfo=UTC)
    state = ApplicationState(
        ApplicationStateKind.READY,
        accounts=(account,),
        refreshed_at=refreshed,
        server_version="1.2.3",
    )
    assert state.has_data
    assert state.refreshed_at == refreshed
    assert state.server_version == "1.2.3"
