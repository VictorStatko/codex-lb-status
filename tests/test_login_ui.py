"""Non-blocking, non-persisting login dialog tests."""

from __future__ import annotations

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QLineEdit

from codex_lb_status.ui import GuestPasswordDialog, PasswordDialog, TotpDialog


def test_password_dialog_masks_and_emits_then_clears(qtbot) -> None:
    dialog = PasswordDialog("Admin", "Password")
    qtbot.addWidget(dialog)
    assert dialog.submit_button.icon().isNull()
    assert dialog.cancel_button.icon().isNull()
    received = []
    dialog.submitted.connect(received.append)
    assert dialog.password.echoMode() is QLineEdit.EchoMode.Password
    dialog.password.setText("secret")
    dialog.submit()
    assert received == ["secret"]
    assert dialog.password.text() == ""


def test_guest_dialog_supports_passwordless_submission(qtbot) -> None:
    dialog = GuestPasswordDialog()
    qtbot.addWidget(dialog)
    received = []
    dialog.submitted_optional.connect(received.append)
    dialog.submit()
    assert received == [None]


def test_totp_dialog_is_a_separate_masked_dialog(qtbot) -> None:
    dialog = TotpDialog()
    qtbot.addWidget(dialog)
    assert dialog.windowTitle() == "Two-factor verification"
    assert dialog.password.echoMode() is QLineEdit.EchoMode.Password


def test_admin_login_keeps_dialog_open_for_empty_password(qtbot) -> None:
    dialog = PasswordDialog("Admin", "Password")
    qtbot.addWidget(dialog)
    received = []
    dialog.submitted.connect(received.append)
    dialog.submit()
    assert received == []
    assert not dialog.error_label.isHidden()


def test_password_visibility_control_is_explicit(qtbot) -> None:
    dialog = PasswordDialog("Admin", "Password")
    qtbot.addWidget(dialog)
    dialog.show_password.setChecked(True)
    assert dialog.password.echoMode() is QLineEdit.EchoMode.Normal
    dialog.show_password.setChecked(False)
    assert dialog.password.echoMode() is QLineEdit.EchoMode.Password
