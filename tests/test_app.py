"""Application-service interaction tests."""

from __future__ import annotations

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QMessageBox, QWidget

from codex_lb_status.app import ApplicationService


class FakeClient:
    def __init__(self) -> None:
        self.clear_count = 0

    def clear_session(self) -> None:
        self.clear_count += 1


class FakeCoordinator:
    def __init__(self, starts_refresh: bool = True) -> None:
        self.starts_refresh = starts_refresh
        self.refresh_count = 0

    def request_refresh(self) -> bool:
        self.refresh_count += 1
        return self.starts_refresh


class FakeDetails:
    def __init__(self, *, minimized: bool = False, hidden: bool = False) -> None:
        self.tray_attached = None
        self.minimized = minimized
        self.hidden = hidden

    def set_tray_attached(self, attached: bool) -> None:
        self.tray_attached = attached

    def isMinimized(self) -> bool:
        return self.minimized

    def isHidden(self) -> bool:
        return self.hidden


def service_for_sign_out(starts_refresh: bool = True) -> ApplicationService:
    service = ApplicationService.__new__(ApplicationService)
    service.client = FakeClient()
    service.coordinator = FakeCoordinator(starts_refresh)
    service._sign_out_refresh_pending = False
    return service


def test_confirmed_sign_out_clears_session_and_refreshes() -> None:
    service = service_for_sign_out()

    service._sign_out_confirmed(QMessageBox.StandardButton.Yes.value)

    assert service.client.clear_count == 1
    assert service.coordinator.refresh_count == 1
    assert not service._sign_out_refresh_pending


def test_sign_out_confirmation_explains_local_scope(qtbot) -> None:
    service = service_for_sign_out()
    service.details = QWidget()
    service._sign_out_dialog = None
    qtbot.addWidget(service.details)

    service.confirm_sign_out()

    dialog = service._sign_out_dialog
    assert dialog is not None
    assert dialog.windowTitle() == "Sign out"
    assert dialog.layout().columnMinimumWidth(1) == 340
    qtbot.waitUntil(lambda: dialog.width() >= 340)
    assert "browser session is not affected" in dialog.informativeText()
    assert not dialog.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    assert dialog.windowHandle().transientParent() == service.details.windowHandle()
    sign_out = dialog.button(QMessageBox.StandardButton.Yes)
    assert sign_out.text() == "Sign out"
    assert sign_out.icon().isNull()
    assert dialog.button(QMessageBox.StandardButton.Cancel).icon().isNull()
    sign_out.click()
    qtbot.waitUntil(lambda: service.client.clear_count == 1, timeout=500)
    assert service.coordinator.refresh_count == 1


def test_cancelled_sign_out_preserves_session() -> None:
    service = service_for_sign_out()

    service._sign_out_confirmed(QMessageBox.StandardButton.Cancel.value)

    assert service.client.clear_count == 0
    assert service.coordinator.refresh_count == 0


def test_sign_out_defers_refresh_when_one_is_already_running(qtbot) -> None:
    service = service_for_sign_out(starts_refresh=False)
    service._sign_out_confirmed(QMessageBox.StandardButton.Yes.value)
    assert service._sign_out_refresh_pending

    service.coordinator.starts_refresh = True
    service._refresh_after_sign_out(None)

    qtbot.waitUntil(lambda: service.coordinator.refresh_count == 2, timeout=500)
    assert not service._sign_out_refresh_pending


def test_explicit_show_presents_details_and_existing_dialogs() -> None:
    service = ApplicationService.__new__(ApplicationService)
    service.details = FakeDetails()
    service.tray = type("Tray", (), {"host_available": True})()
    service._settings_dialog = object()
    service._sign_out_dialog = None
    service._login_dialog = object()
    service._totp_dialog = None
    service._message_box = None
    service._details_should_be_visible = False
    presented = []
    service._present_window = presented.append

    service.show_details()

    assert service.details.tray_attached
    assert presented == [
        service.details,
        service._settings_dialog,
        service._login_dialog,
    ]


def test_present_window_restores_a_minimized_window() -> None:
    events = []

    class Window:
        def isMinimized(self):
            return True

        def showNormal(self):
            events.append("restore")

        def show(self):
            events.append("show")

        def raise_(self):
            events.append("raise")

        def activateWindow(self):
            events.append("activate")

    service = ApplicationService.__new__(ApplicationService)
    service._position_near_indicator = lambda _window: events.append("position")

    service._present_window(Window())

    assert events == ["restore", "position", "raise", "activate"]


def test_present_window_uses_details_as_anchor_for_secondary_windows() -> None:
    events = []

    class Window:
        def isMinimized(self):
            return False

        def show(self):
            events.append("show")

        def raise_(self):
            events.append("raise")

        def activateWindow(self):
            events.append("activate")

    service = ApplicationService.__new__(ApplicationService)
    service.details = object()
    service._position_near_indicator = lambda _window: events.append("tray")
    service._position_near_details = lambda _window: events.append("details")

    service._present_window(Window())

    assert events == ["show", "details", "raise", "activate"]


def test_tray_request_toggles_details_open_and_closed(qtbot) -> None:
    from codex_lb_status.config import AppConfig
    from codex_lb_status.ui import DetailsWindow

    service = ApplicationService.__new__(ApplicationService)
    service.details = DetailsWindow(
        config=AppConfig(),
        tray_available=lambda: True,
    )
    qtbot.addWidget(service.details)
    service.tray = type("Tray", (), {"host_available": True})()
    service._details_should_be_visible = False
    service._settings_dialog = None
    service._sign_out_dialog = None
    service._login_dialog = None
    service._totp_dialog = None
    service._message_box = None
    service._position_near_indicator = lambda _window: None
    service.details.dismissed.connect(service._details_dismissed)

    service.show_details()
    assert service.details.isVisible()
    assert service._details_should_be_visible

    service.toggle_details()
    assert service.details.isHidden()
    assert not service._details_should_be_visible

    service.toggle_details()
    assert service.details.isVisible()
    assert service._details_should_be_visible


def test_closing_details_rejects_all_owned_and_nested_dialogs(qtbot) -> None:
    from codex_lb_status.config import AppConfig
    from codex_lb_status.ui import DetailsWindow, PasswordDialog, SettingsDialog

    service = ApplicationService.__new__(ApplicationService)
    service.details = DetailsWindow(config=AppConfig())
    service._details_should_be_visible = True
    qtbot.addWidget(service.details)
    service.details.dismissed.connect(service._details_dismissed)
    service.details.show()

    settings = SettingsDialog(config=AppConfig(), parent=service.details)
    login = PasswordDialog("Sign in", "Enter password", service.details)
    qtbot.addWidget(settings)
    qtbot.addWidget(login)
    settings.show()
    login.show()
    settings.confirm_restore_defaults()
    confirmation = settings.findChild(QMessageBox)
    assert confirmation is not None
    qtbot.waitUntil(
        lambda: all(dialog.isVisible() for dialog in (settings, login, confirmation))
    )

    service.details.close()

    assert service.details.isHidden()
    assert not service._details_should_be_visible
    assert all(dialog.isHidden() for dialog in (settings, login, confirmation))
    assert all(
        dialog.result() == QDialog.DialogCode.Rejected.value
        for dialog in (settings, login, confirmation)
    )
