"""Qt refresh behavior; skipped when the distribution GUI dependency is absent."""

from __future__ import annotations

import threading

import pytest

pytest.importorskip("PyQt6")

from codex_lb_status.client import RefreshPayload
from codex_lb_status.models import (
    AccountsResponse,
    AccountSummary,
    ApplicationStateKind,
    DashboardSession,
)
from codex_lb_status.refresh import REFRESH_INTERVAL_MS, RefreshCoordinator


def payload() -> RefreshPayload:
    return RefreshPayload(
        DashboardSession(authenticated=True),
        AccountsResponse(
            (
                AccountSummary(
                    account_id="a",
                    email="a@example.com",
                    display_name="A",
                    plan_type="plus",
                    routing_policy="normal",
                    status="active",
                ),
            )
        ),
    )


class FakeClient:
    server_version = "test"

    def __init__(self):
        self.results = [payload()]
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls = 0

    def refresh(self):
        self.calls += 1
        self.started.set()
        if self.calls == 1:
            self.release.wait(2)
            return self.results[0]
        result = self.results[min(self.calls - 1, len(self.results) - 1)]
        if isinstance(result, Exception):
            raise result
        return result


def test_refresh_uses_one_worker_and_ignores_overlap(qtbot) -> None:
    client = FakeClient()
    coordinator = RefreshCoordinator(client)
    try:
        coordinator.start()
        assert client.started.wait(1)
        assert not coordinator.request_refresh()
        with qtbot.waitSignal(coordinator.state_changed, timeout=2):
            client.release.set()
        assert coordinator.state.kind is ApplicationStateKind.READY
        assert client.calls == 1
        assert coordinator.timer.interval() == REFRESH_INTERVAL_MS
    finally:
        coordinator.shutdown()


def test_transient_error_keeps_successful_data(qtbot) -> None:
    client = FakeClient()
    client.results = [payload(), ConnectionError("offline")]
    coordinator = RefreshCoordinator(client)
    try:
        coordinator.start()
        with qtbot.waitSignal(coordinator.state_changed, timeout=2):
            client.release.set()
        assert coordinator.request_refresh()
        with qtbot.waitSignal(coordinator.state_changed, timeout=2):
            pass
        assert coordinator.state.kind is ApplicationStateKind.STALE
        assert coordinator.state.accounts
    finally:
        coordinator.shutdown()


def test_failed_async_operation_is_delivered_on_the_qt_thread(qtbot) -> None:
    coordinator = RefreshCoordinator(FakeClient())

    def fail() -> None:
        raise RuntimeError("operation failed")

    try:
        with qtbot.waitSignal(coordinator.operation_finished, timeout=2) as signal:
            assert coordinator.run_operation(fail)
        result, error = signal.args
        assert result is None
        assert isinstance(error, RuntimeError)
        assert str(error) == "operation failed"
    finally:
        coordinator.shutdown()
