"""Application entry point and the initial, network-free startup shell.

Qt is deliberately imported inside run_application. Importing the package,
collecting tests, or asking for --version therefore does not create a
QApplication or require a running display server.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import MutableMapping, Sequence
from contextlib import suppress
from dataclasses import dataclass

from . import __version__

MIN_PYQT6 = (6, 6)
MIN_QT6 = (6, 4)


class QtRuntimeError(RuntimeError):
    """Raised when the installed Qt runtime cannot run the application."""


@dataclass(frozen=True, slots=True)
class CliOptions:
    """The startup intent selected by the command line."""

    background: bool = False
    settings: bool = False


def build_parser() -> argparse.ArgumentParser:
    """Create the command-line parser without importing Qt."""

    parser = argparse.ArgumentParser(
        prog="codex-lb-status",
        description="Read-only Codex LB status indicator for Ubuntu.",
    )
    startup_group = parser.add_mutually_exclusive_group()
    startup_group.add_argument(
        "--background",
        action="store_true",
        help="start the indicator without presenting the details window",
    )
    startup_group.add_argument(
        "--settings",
        action="store_true",
        help="start the application and present Settings",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"codex-lb-status {__version__}",
    )
    return parser


def parse_args(argv: Sequence[str] | None = None) -> CliOptions:
    """Parse a supported startup intent."""

    namespace = build_parser().parse_args(argv)
    return CliOptions(
        background=namespace.background,
        settings=namespace.settings,
    )


def _version_tuple(value: str) -> tuple[int, ...]:
    """Return numeric version components for comparison with minimums."""

    components: list[int] = []
    for component in value.split("."):
        digits = "".join(character for character in component if character.isdigit())
        if not digits:
            break
        components.append(int(digits))
    return tuple(components)


def validate_qt_runtime() -> None:
    """Validate supported PyQt6 and Qt 6 versions before creating Qt.

    This function is intentionally lazy with respect to PyQt6 so command-line
    parsing and package imports remain usable in build and test environments
    that do not have the desktop runtime installed.
    """

    try:
        from PyQt6.QtCore import PYQT_VERSION_STR, QT_VERSION_STR
    except ImportError as error:
        raise QtRuntimeError(
            "PyQt6 >= 6.6 is required to run codex-lb-status. Install the "
            "Ubuntu package python3-pyqt6 and try again."
        ) from error

    if _version_tuple(PYQT_VERSION_STR) < MIN_PYQT6:
        raise QtRuntimeError(
            "PyQt6 >= 6.6 is required to run codex-lb-status; found "
            f"PyQt6 {PYQT_VERSION_STR}. Install a newer python3-pyqt6 package."
        )
    if _version_tuple(QT_VERSION_STR) < MIN_QT6:
        raise QtRuntimeError(
            "Qt >= 6.4 is required to run codex-lb-status; found "
            f"Qt {QT_VERSION_STR}. Install the supported Ubuntu Qt 6 runtime."
        )


def configure_qt_platform(
    environment: MutableMapping[str, str] | None = None,
) -> bool:
    """Prefer XWayland when it is needed for deterministic window placement."""

    values = environment if environment is not None else os.environ
    if values.get("QT_QPA_PLATFORM"):
        return False
    if values.get("XDG_SESSION_TYPE", "").casefold() != "wayland":
        return False
    if not values.get("DISPLAY"):
        return False
    values["QT_QPA_PLATFORM"] = "xcb"
    return True


def run_application(options: CliOptions) -> int:
    """Start one Qt application instance for the requested intent."""

    configure_qt_platform()
    validate_qt_runtime()
    from PyQt6.QtWidgets import QApplication

    from .single_instance import SingleInstance
    from .theme import configure_application

    qt_app = QApplication.instance() or QApplication([sys.argv[0]])
    configure_application(qt_app)
    command = (
        "background"
        if options.background
        else ("settings" if options.settings else "default")
    )
    instance = SingleInstance(parent=qt_app)
    if not instance.acquire(command):
        return 0
    service = ApplicationService(qt_app, options, instance)
    service.start()
    # Keep the service reference alive for the duration of the event loop.
    return qt_app.exec()


class ApplicationService:
    """Own the current client, refresh coordinator, indicator, and windows."""

    def __init__(self, qt_app, options: CliOptions, instance):
        from .autostart import AutostartManager
        from .client import CodexLBClient
        from .config import ConfigError, default_config, load_config
        from .indicator import TrayIndicator
        from .refresh import RefreshCoordinator
        from .ui import DetailsWindow

        self.qt_app = qt_app
        self.options = options
        self.instance = instance
        self._shut_down = False
        self._message_box = None
        self._sign_out_dialog = None
        self._sign_out_refresh_pending = False
        # Keep the explicit open/closed intent separate from transient desktop
        # visibility changes. A tray double-click toggles this intent.
        self._details_should_be_visible = False
        self.autostart_manager = AutostartManager()
        try:
            self.config = load_config()
            self.configuration_error = None
        except ConfigError as error:
            self.config = default_config()
            self.configuration_error = str(error)
        self.client = CodexLBClient(self.config.base_url)
        self.coordinator = RefreshCoordinator(self.client)
        self.tray = TrayIndicator(
            parent=qt_app,
            background_launch=options.background,
        )
        self.details = DetailsWindow(
            coordinator=self.coordinator,
            config=self.config,
            autostart_manager=self.autostart_manager,
            tray_available=lambda: self.tray.host_available,
        )
        self._settings_dialog = None
        self._login_dialog = None
        self._totp_dialog = None
        self._bind_coordinator()
        self.tray.set_state(self.coordinator.state)
        self.qt_app.aboutToQuit.connect(self._shutdown)
        instance.command_received.connect(self.handle_command)
        self.tray.toggle_details_requested.connect(self.toggle_details)
        self.tray.host_available_changed.connect(self.details.set_tray_attached)
        self.details.settings_requested.connect(self.show_settings)
        self.details.login_requested.connect(self._show_requested_login)
        self.details.sign_out_requested.connect(self.confirm_sign_out)
        self.details.launch_at_login_changed.connect(self.set_launch_at_login)
        self.details.quit_requested.connect(self.quit)
        self.details.dismissed.connect(self._details_dismissed)

    def _bind_coordinator(self) -> None:
        self.coordinator.state_changed.connect(self.tray.set_state)
        self.coordinator.refresh_started.connect(self.tray.mark_data_outdated)
        self.coordinator.refresh_started.connect(
            lambda: self.details.refresh_button.setEnabled(False)
        )
        self.coordinator.refresh_finished.connect(
            lambda _state: self.details.refresh_button.setEnabled(True)
        )
        self.coordinator.refresh_finished.connect(self._refresh_after_sign_out)
        self.coordinator.operation_finished.connect(self._operation_finished)

    def start(self) -> None:
        self.qt_app.setQuitOnLastWindowClosed(False)
        self.coordinator.start()
        if self.options.settings:
            self.show_settings()
        elif not self.options.background:
            self.show_details()
        if self.configuration_error:
            from PyQt6.QtCore import QTimer

            message = self.configuration_error
            self.configuration_error = None
            QTimer.singleShot(
                0,
                lambda: self._show_message(
                    "Settings",
                    "Could not load the saved settings; defaults are in use: "
                    f"{message}",
                ),
            )

    def handle_command(self, command: str) -> None:
        if command == "default":
            self.show_details()
        elif command == "settings":
            self.show_settings()

    def show_details(self) -> None:
        """Explicitly open details and bring any active child dialogs forward."""

        self._details_should_be_visible = True
        tray = getattr(self, "tray", None)
        self.details.set_tray_attached(bool(tray and tray.host_available))
        self._present_window(self.details)
        for dialog in self._active_dialogs():
            self._present_window(dialog)

    def toggle_details(self) -> None:
        """Open closed Details, or close Details that the user left open."""

        if self._details_should_be_visible:
            self.details.close()
            return
        self.show_details()

    def _details_dismissed(self) -> None:
        """Record the close and reject every dialog owned by Details."""

        self._details_should_be_visible = False
        self._reject_details_dialogs()

    def _reject_details_dialogs(self) -> None:
        """Reject visible owned dialogs, with nested dialogs closed first."""

        from PyQt6.QtWidgets import QDialog

        details = getattr(self, "details", None)
        if details is None or not hasattr(details, "findChildren"):
            return

        def ownership_depth(dialog: QDialog) -> int:
            depth = 0
            parent = dialog.parent()
            while parent is not None:
                depth += 1
                parent = parent.parent()
            return depth

        dialogs = details.findChildren(QDialog)
        for dialog in sorted(dialogs, key=ownership_depth, reverse=True):
            if dialog.isVisible():
                dialog.reject()

    def _active_dialogs(self):
        """Yield dialogs whose non-blocking lifecycle has not finished."""

        for name in (
            "_settings_dialog",
            "_sign_out_dialog",
            "_login_dialog",
            "_totp_dialog",
            "_message_box",
        ):
            dialog = getattr(self, name, None)
            if dialog is not None:
                yield dialog

    def _present_window(self, window) -> None:
        """Restore, anchor, and raise a tray-owned window."""

        from PyQt6.QtWidgets import QDialog, QMessageBox

        from .ui import configure_modal_dialog, ensure_message_box_width

        if isinstance(window, QDialog) and window is not getattr(self, "details", None):
            configure_modal_dialog(window)
        if window.isMinimized():
            window.showNormal()
        else:
            window.show()
        if isinstance(window, QMessageBox):
            ensure_message_box_width(window)
        if window is getattr(self, "details", None):
            self._position_near_indicator(window)
        else:
            self._position_near_details(window)
        window.raise_()
        window.activateWindow()

    def _position_near_indicator(self, window) -> None:
        tray = getattr(self, "tray", None)
        if tray is None or not tray.host_available:
            return
        from PyQt6.QtCore import QTimer

        from .ui import position_window_near_anchor

        def place() -> None:
            with suppress(RuntimeError):
                position_window_near_anchor(window, tray.anchor_geometry)

        place()
        for delay in (0, 50, 200):
            QTimer.singleShot(delay, place)

    def _position_near_details(self, window) -> None:
        details = getattr(self, "details", None)
        if details is None or not details.isVisible():
            self._position_near_indicator(window)
            return

        from PyQt6.QtCore import QTimer

        from .ui import position_window_centered_on_anchor

        def place() -> None:
            with suppress(RuntimeError):
                position_window_centered_on_anchor(
                    window,
                    details.frameGeometry(),
                )

        place()
        for delay in (0, 50, 200):
            QTimer.singleShot(delay, place)

    def _clear_window_reference(self, name: str, window) -> None:
        if getattr(self, name, None) is window:
            setattr(self, name, None)

    def confirm_sign_out(self) -> None:
        """Confirm removal of the current origin's locally saved session."""

        from PyQt6.QtWidgets import QMessageBox

        from .ui import (
            configure_modal_dialog,
            open_message_box,
            remove_button_icons,
        )

        if self._sign_out_dialog is not None:
            self._present_window(self._sign_out_dialog)
            return
        dialog = QMessageBox(self.details)
        configure_modal_dialog(dialog)
        dialog.setWindowTitle("Sign out")
        dialog.setText("Sign out of Codex LB Status?")
        dialog.setInformativeText(
            "This removes the saved session for this server from the desktop "
            "companion. Your browser session is not affected."
        )
        dialog.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel
        )
        remove_button_icons(dialog)
        sign_out_button = dialog.button(QMessageBox.StandardButton.Yes)
        sign_out_button.setText("Sign out")
        dialog.setDefaultButton(QMessageBox.StandardButton.Cancel)
        dialog.finished.connect(self._sign_out_confirmed)
        dialog.finished.connect(
            lambda _result, current=dialog: self._clear_window_reference(
                "_sign_out_dialog", current
            )
        )
        self._sign_out_dialog = dialog
        open_message_box(dialog)
        self._present_window(dialog)

    def _sign_out_confirmed(self, result: int) -> None:
        from PyQt6.QtWidgets import QMessageBox

        if result != QMessageBox.StandardButton.Yes.value:
            return
        try:
            self.client.clear_session()
        except OSError as error:
            self._show_message(
                "Sign out", f"Could not remove the saved session: {error}"
            )
            return
        if not self.coordinator.request_refresh():
            self._sign_out_refresh_pending = True
        else:
            self._sign_out_refresh_pending = False

    def _refresh_after_sign_out(self, _state) -> None:
        if not self._sign_out_refresh_pending:
            return
        from PyQt6.QtCore import QTimer

        self._sign_out_refresh_pending = False
        QTimer.singleShot(0, self.coordinator.request_refresh)

    def show_settings(self) -> None:
        from .ui import SettingsDialog

        if self._settings_dialog is not None:
            self._present_window(self._settings_dialog)
            return
        dialog = SettingsDialog(
            self.config,
            self.autostart_manager,
            parent=self.details,
        )
        self._settings_dialog = dialog
        dialog.settings_saved.connect(self._settings_saved)
        dialog.finished.connect(
            lambda _result, current=dialog: self._clear_window_reference(
                "_settings_dialog", current
            )
        )
        dialog.open()
        self._present_window(dialog)

    def _settings_saved(self, config, origin_changed: bool) -> None:
        self.config = config
        self.details.set_config(config)
        self.details.set_launch_at_login(self.autostart_manager.enabled)
        if not origin_changed:
            return
        old_coordinator = self.coordinator
        old_coordinator.shutdown()
        from .client import CodexLBClient
        from .refresh import RefreshCoordinator

        self.client = CodexLBClient(config.base_url)
        self.coordinator = RefreshCoordinator(self.client)
        self.details.set_coordinator(self.coordinator)
        self._bind_coordinator()
        self.tray.set_state(self.coordinator.state)
        self.coordinator.start()

    def set_launch_at_login(self, enabled: bool) -> None:
        from .config import SettingsTransactionError, apply_settings_transaction

        try:
            apply_settings_transaction(
                self.config,
                enabled,
                self.autostart_manager,
            )
        except SettingsTransactionError as error:
            self._show_message("Settings", str(error))
        finally:
            self.details.set_launch_at_login(self.autostart_manager.enabled)

    def show_admin_login(self) -> None:
        from .ui import PasswordDialog

        if self._login_dialog is not None:
            self._present_window(self._login_dialog)
            return
        dialog = PasswordDialog(
            "Sign in",
            "Enter the dashboard administrator password.",
            self.details,
            action_label="Sign in",
        )
        self._login_dialog = dialog
        dialog.submitted.connect(self._submit_admin_password)
        dialog.finished.connect(
            lambda _result, current=dialog: self._clear_window_reference(
                "_login_dialog", current
            )
        )
        dialog.open()
        self._present_window(dialog)

    def _show_requested_login(self, login_kind: str) -> None:
        if login_kind == "guest":
            self.show_guest_login()
        else:
            self.show_admin_login()

    def _submit_admin_password(self, password: str) -> None:
        self.coordinator.run_operation(lambda: self.client.start_admin_login(password))

    def show_guest_login(self) -> None:
        from .ui import GuestPasswordDialog

        if self._login_dialog is not None:
            self._present_window(self._login_dialog)
            return
        dialog = GuestPasswordDialog(self.details)
        self._login_dialog = dialog
        dialog.submitted_optional.connect(self._submit_guest_password)
        dialog.finished.connect(
            lambda _result, current=dialog: self._clear_window_reference(
                "_login_dialog", current
            )
        )
        dialog.open()
        self._present_window(dialog)

    def _submit_guest_password(self, password: str | None) -> None:
        self.coordinator.run_operation(lambda: self.client.login_guest(password))

    def _operation_finished(self, result, error) -> None:
        if error is not None:
            self._show_message("Codex LB Login", str(error))
            return
        if getattr(result, "totp_required_on_login", False):
            self.show_totp_login()
        else:
            self.coordinator.request_refresh()

    def show_totp_login(self) -> None:
        from .ui import TotpDialog

        if self._totp_dialog is not None:
            self._present_window(self._totp_dialog)
            return
        dialog = TotpDialog(self.details)
        self._totp_dialog = dialog
        dialog.submitted.connect(self._submit_totp)
        dialog.finished.connect(
            lambda _result, current=dialog: self._clear_window_reference(
                "_totp_dialog", current
            )
        )
        dialog.open()
        self._present_window(dialog)

    def _submit_totp(self, code: str) -> None:
        self.coordinator.run_operation(lambda: self.client.verify_totp(code))

    def _show_message(self, title: str, message: str) -> None:
        from PyQt6.QtWidgets import QMessageBox

        from .ui import (
            configure_modal_dialog,
            open_message_box,
            remove_button_icons,
        )

        dialog = QMessageBox(self.details)
        configure_modal_dialog(dialog)
        self._message_box = dialog
        dialog.setWindowTitle(title)
        dialog.setText(str(message)[:500])
        dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
        remove_button_icons(dialog)
        dialog.finished.connect(
            lambda _result, current=dialog: self._clear_window_reference(
                "_message_box", current
            )
        )
        open_message_box(dialog)
        self._present_window(dialog)

    def _shutdown(self) -> None:
        if self._shut_down:
            return
        self._shut_down = True
        self.coordinator.shutdown()
        self.tray.close()
        self.instance.close()

    def quit(self) -> None:
        self._shutdown()
        self.qt_app.quit()


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command-line interface and return a process exit code."""

    parser = build_parser()
    namespace = parser.parse_args(argv)
    options = CliOptions(
        background=namespace.background,
        settings=namespace.settings,
    )
    try:
        return run_application(options)
    except QtRuntimeError as error:
        parser.error(str(error))
    return 2  # pragma: no cover - argparse.error always raises SystemExit.
