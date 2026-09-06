"""Single-worker refresh coordination for the Qt application."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import CancelledError, Future, ThreadPoolExecutor
from datetime import UTC, datetime

from .client import AuthenticationRequired
from .models import ApplicationState, ApplicationStateKind
from .presentation import sanitize_text

try:
    from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal
except ImportError:  # pragma: no cover - exercised only without the GUI extra.
    QObject = None


REFRESH_INTERVAL_MS = 60_000


if QObject is None:

    class RefreshCoordinator:
        """Placeholder that explains the missing desktop dependency."""

        def __init__(self, *args, **kwargs):
            raise RuntimeError("PyQt6 >= 6.6 is required for refresh coordination")

else:

    class _ResultEmitter(QObject):
        completed = pyqtSignal(object, object)
        operation = pyqtSignal(object, object)

    class RefreshCoordinator(QObject):
        """Keep all blocking client calls off the Qt GUI thread."""

        state_changed = pyqtSignal(object)
        refresh_started = pyqtSignal()
        refresh_finished = pyqtSignal(object)
        operation_finished = pyqtSignal(object, object)

        def __init__(
            self,
            client,
            parent: QObject | None = None,
            now_provider: Callable[[], datetime] | None = None,
        ):
            super().__init__(parent)
            self.client = client
            self._now_provider = now_provider or (lambda: datetime.now(UTC))
            self._executor = ThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix="codex-lb-refresh",
            )
            self._emitter = _ResultEmitter(self)
            self._emitter.completed.connect(
                self._deliver,
                Qt.ConnectionType.QueuedConnection,
            )
            self._emitter.operation.connect(
                self._deliver_operation,
                Qt.ConnectionType.QueuedConnection,
            )
            self._timer = QTimer(self)
            self._timer.setInterval(REFRESH_INTERVAL_MS)
            self._timer.timeout.connect(self.request_refresh)
            self._state = ApplicationState.loading()
            self._active = False
            self._shutdown = False

        @property
        def state(self) -> ApplicationState:
            return self._state

        @property
        def timer(self) -> QTimer:
            return self._timer

        @property
        def is_refreshing(self) -> bool:
            return self._active

        def start(self) -> None:
            if self._shutdown:
                return
            self._timer.start()
            self.request_refresh()

        def request_refresh(self) -> bool:
            if self._shutdown or self._active:
                return False
            self._active = True
            self.refresh_started.emit()
            future = self._executor.submit(self._fetch)
            future.add_done_callback(self._future_done)
            return True

        def run_operation(self, operation: Callable[[], object]) -> bool:
            """Queue a non-refresh client operation on the same worker."""

            if self._shutdown:
                return False
            future = self._executor.submit(operation)
            future.add_done_callback(self._operation_done)
            return True

        def _fetch(self):
            try:
                return self.client.refresh(), None
            except Exception as error:  # worker boundary; delivery is typed below.
                return None, error

        def _future_done(self, future: Future) -> None:
            try:
                result, error = future.result()
            except CancelledError:
                return
            self._emitter.completed.emit(result, error)

        def _operation_done(self, future: Future) -> None:
            try:
                result = future.result()
            except CancelledError:
                return
            except Exception as exception:
                result = None
                error = exception
            else:
                error = None
            self._emitter.operation.emit(result, error)

        def _deliver_operation(self, result, error) -> None:
            if not self._shutdown:
                self.operation_finished.emit(result, error)

        def _deliver(self, payload, error) -> None:
            if self._shutdown:
                return
            self._active = False
            if error is None:
                self._set_success(payload)
            else:
                self._set_failure(error)
            self.refresh_finished.emit(self._state)
            self.state_changed.emit(self._state)

        def _set_success(self, payload) -> None:
            accounts_response = payload.accounts
            accounts = tuple(accounts_response.accounts)
            kind = (
                ApplicationStateKind.READY if accounts else ApplicationStateKind.EMPTY
            )
            server_version = getattr(self.client, "server_version", None)
            self._state = ApplicationState(
                kind=kind,
                accounts=accounts,
                refreshed_at=self._now_provider(),
                server_version=server_version,
                session=payload.session,
            )

        def _set_failure(self, error: Exception) -> None:
            old = self._state
            message = sanitize_text(str(error), 240) or "refresh failed"
            if isinstance(error, AuthenticationRequired):
                kind = ApplicationStateKind.LOGIN_REQUIRED
                session = error.session or old.session
            elif old.has_data:
                kind = ApplicationStateKind.STALE
                session = old.session
            else:
                kind = ApplicationStateKind.ERROR
                session = old.session
            self._state = ApplicationState(
                kind=kind,
                accounts=old.accounts,
                refreshed_at=old.refreshed_at,
                server_version=old.server_version,
                error_message=message,
                session=session,
            )

        def shutdown(self) -> None:
            if self._shutdown:
                return
            self._shutdown = True
            self._timer.stop()
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._active = False


__all__ = ["REFRESH_INTERVAL_MS", "RefreshCoordinator"]
