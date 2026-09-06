"""Details-window rendering tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QPoint, QRect, Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QMessageBox,
    QPushButton,
    QToolButton,
    QWidget,
)

from codex_lb_status.autostart import AutostartManager
from codex_lb_status.config import AppConfig
from codex_lb_status.models import (
    AccountSummary,
    AccountUsage,
    ApplicationState,
    ApplicationStateKind,
    DashboardSession,
)
from codex_lb_status.ui import (
    AccountCard,
    DetailsWindow,
    PasswordDialog,
    QuotaProgress,
    SettingsDialog,
    details_window_height,
    position_window_centered_on_anchor,
    position_window_near_anchor,
)


def account(index: int) -> AccountSummary:
    return AccountSummary(
        account_id=f"account-{index}",
        email=f"account-{index}@example.com",
        display_name=f"Account {index}",
        plan_type="plus",
        routing_policy="normal",
        status="active",
        usage=AccountUsage(85, 45, None),
        reset_at_primary=datetime(2026, 9, 4, 12, tzinfo=UTC),
    )


def test_details_window_renders_ready_empty_stale_login_and_error_states(qtbot) -> None:
    window = DetailsWindow(config=AppConfig())
    qtbot.addWidget(window)
    for kind in ApplicationStateKind:
        window.set_state(ApplicationState(kind, accounts=(account(1),)))
        assert window.banner is not None
    assert window.summary_label.text().startswith("5h")
    assert window.primary_summary.text() == "85%"
    assert window.weekly_summary.text() == "45%"
    assert window.accounts_summary.text() == "1/1"
    assert window.primary_caption.text() == "5-hour"
    assert window.weekly_caption.text() == "Weekly"
    assert window.accounts_caption.text() == "Active accounts"
    window.set_state(ApplicationState(ApplicationStateKind.EMPTY))
    assert not window.banner.isHidden()


def test_details_summary_values_share_one_row(qtbot) -> None:
    window = DetailsWindow(config=AppConfig())
    qtbot.addWidget(window)
    window.set_state(
        ApplicationState(ApplicationStateKind.READY, accounts=(account(1),))
    )
    window.show()
    qtbot.waitUntil(window.isVisible)

    value_tops = {
        label.mapTo(window, QPoint(0, 0)).y()
        for label in (
            window.primary_summary,
            window.weekly_summary,
            window.accounts_summary,
        )
    }

    assert len(value_tops) == 1


def test_details_averages_show_nearest_increase_countdown_for_each_quota(
    qtbot,
    monkeypatch,
) -> None:
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 6, 8, tzinfo=tz or UTC)

    monkeypatch.setattr("codex_lb_status.ui.datetime", FixedDateTime)
    first_primary = datetime(2026, 9, 6, 10, tzinfo=UTC)
    first_weekly = datetime(2026, 9, 8, 10, tzinfo=UTC)
    later = replace(
        account(1),
        reset_at_primary=first_primary.replace(hour=12),
        reset_at_secondary=first_weekly,
    )
    earlier = replace(
        account(2),
        reset_at_primary=first_primary,
        reset_at_secondary=first_weekly.replace(hour=12),
    )
    window = DetailsWindow(config=AppConfig(display_time_zone="utc"))
    qtbot.addWidget(window)

    window.set_state(
        ApplicationState(
            ApplicationStateKind.READY,
            accounts=(later, earlier),
        )
    )

    assert window.primary_increase.text() == "Increases in 2h 0m"
    assert window.weekly_increase.text() == "Increases in 2d 2h"


def test_details_average_reports_when_no_increase_is_scheduled(qtbot) -> None:
    item = replace(
        account(1),
        reset_at_primary=None,
        reset_at_secondary=None,
    )
    window = DetailsWindow(config=AppConfig(display_time_zone="utc"))
    qtbot.addWidget(window)

    window.set_state(ApplicationState(ApplicationStateKind.READY, accounts=(item,)))

    assert window.primary_increase.text() == "No increase scheduled"
    assert window.weekly_increase.text() == "No increase scheduled"


def test_details_window_height_uses_all_available_screen_height() -> None:
    assert details_window_height(900) == 900
    assert details_window_height(600) == 600


def test_details_window_actions_do_not_use_decorative_icons(qtbot) -> None:
    window = DetailsWindow(config=AppConfig())
    qtbot.addWidget(window)
    assert window.refresh_button.icon().isNull()
    assert window.admin_login_button.icon().isNull()
    assert window.guest_login_button.icon().isNull()
    assert window.actions_button.icon().isNull()
    assert window.settings_action.icon().isNull()
    assert window.dashboard_action.icon().isNull()
    assert window.sign_out_action.icon().isNull()
    assert window.stop_action.icon().isNull()


def test_details_owned_dialogs_stay_above_details_window(qtbot) -> None:
    from codex_lb_status.app import ApplicationService

    details = DetailsWindow(config=AppConfig())
    qtbot.addWidget(details)
    details.show()
    qtbot.waitUntil(details.isVisible)

    service = ApplicationService.__new__(ApplicationService)
    service.details = details
    service._settings_dialog = None
    service._sign_out_dialog = None
    service._login_dialog = None
    service._totp_dialog = None
    service._message_box = None
    service._position_near_details = lambda _window: None
    service._position_near_indicator = lambda _window: None

    dialogs = (
        SettingsDialog(config=AppConfig(), parent=details),
        PasswordDialog("Sign in", "Enter the dashboard password.", details),
    )
    for dialog in dialogs:
        qtbot.addWidget(dialog)
        service._present_window(dialog)
        qtbot.waitUntil(dialog.isVisible)
        assert dialog.windowModality() is Qt.WindowModality.WindowModal
        assert not dialog.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
        assert dialog.parentWidget() is details
        assert dialog.windowHandle().transientParent() == details.windowHandle()
        assert dialog.isEnabled()
        assert details.isEnabled()

        dialog.close()


def test_nested_settings_confirmation_stays_above_details(qtbot) -> None:
    details = DetailsWindow(config=AppConfig())
    dialog = SettingsDialog(config=AppConfig(), parent=details)
    qtbot.addWidget(details)
    qtbot.addWidget(dialog)

    dialog.confirm_restore_defaults()
    message = dialog.findChild(QMessageBox)

    assert message is not None
    assert message.layout().columnMinimumWidth(1) == 340
    qtbot.waitUntil(lambda: message.width() >= 340)
    assert message.windowModality() is Qt.WindowModality.WindowModal
    assert not message.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    assert message.parentWidget() is dialog
    assert message.windowHandle().transientParent() == dialog.windowHandle()
    assert message.isEnabled()
    message.close()


def test_details_window_contains_actions_removed_from_tray_menu(
    qtbot, tmp_path
) -> None:
    manager = AutostartManager(tmp_path / "config-home")
    window = DetailsWindow(config=AppConfig(), autostart_manager=manager)
    qtbot.addWidget(window)
    window.set_state(
        ApplicationState(
            ApplicationStateKind.READY,
            accounts=(account(1),),
            session=DashboardSession(authenticated=True, role="admin"),
            server_version="1.25.0",
        )
    )

    assert window.sign_out_action.isVisible()
    assert window.dashboard_action.text() == "Open Codex LB 1.25.0"
    assert (
        window.actions_button.popupMode()
        is QToolButton.ToolButtonPopupMode.InstantPopup
    )
    text_width = window.actions_button.fontMetrics().horizontalAdvance("Actions")
    assert window.actions_button.sizeHint().width() - text_width >= 44
    footer = window.actions_button.parentWidget()
    assert footer.findChildren(QCheckBox) == [window.launch_at_login]
    assert footer.findChildren(QPushButton) == []
    with qtbot.waitSignal(window.sign_out_requested, timeout=500):
        window.sign_out_action.trigger()
    with qtbot.waitSignal(window.launch_at_login_changed, timeout=500) as changed:
        window.launch_at_login.setChecked(True)
    assert changed.args == [True]
    with qtbot.waitSignal(window.quit_requested, timeout=500):
        window.stop_action.trigger()

    window.set_launch_at_login(False)
    assert not window.launch_at_login.isChecked()
    window.set_state(ApplicationState(ApplicationStateKind.LOGIN_REQUIRED))
    assert not window.sign_out_action.isVisible()


def test_four_or_more_accounts_are_scrollable_cards(qtbot) -> None:
    window = DetailsWindow(config=AppConfig())
    qtbot.addWidget(window)
    window.set_state(
        ApplicationState(
            ApplicationStateKind.READY,
            accounts=tuple(account(index) for index in range(5)),
        )
    )
    cards = window.account_container.findChildren(AccountCard)
    assert len(cards) == 5
    assert all(card.details_widget.isHidden() for card in cards)
    assert window.scroll.widgetResizable()
    assert window.width() <= 500


def test_details_window_fills_screen_height_when_accounts_arrive_after_open(
    qtbot, qapp
) -> None:
    window = DetailsWindow(config=AppConfig())
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.isVisible())
    available_height = qapp.primaryScreen().availableGeometry().height()
    assert window.height() == details_window_height(available_height)

    accounts = tuple(account(index) for index in range(10))
    window.set_state(ApplicationState(ApplicationStateKind.READY, accounts=accounts))

    assert window.height() == details_window_height(available_height)
    qtbot.waitUntil(lambda: window.scroll.verticalScrollBar().isVisible(), timeout=500)


def test_manual_details_resize_is_preserved(qtbot) -> None:
    window = DetailsWindow(config=AppConfig())
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.isVisible())
    window.resize(window.width(), 560)

    window.set_state(
        ApplicationState(
            ApplicationStateKind.READY,
            accounts=tuple(account(index) for index in range(10)),
        )
    )

    assert window.height() == 560


def test_expanded_account_survives_a_state_refresh(qtbot) -> None:
    window = DetailsWindow(config=AppConfig())
    qtbot.addWidget(window)
    first_state = ApplicationState(
        ApplicationStateKind.READY,
        accounts=(account(1), account(2)),
    )
    window.set_state(first_state)
    window._account_cards["account-2"].toggle_button.setChecked(True)

    window.set_state(first_state)

    assert window._account_cards["account-2"].toggle_button.isChecked()
    assert not window._account_cards["account-1"].toggle_button.isChecked()


def test_dynamic_account_text_is_plain_text(qtbot) -> None:
    unsafe = AccountSummary(
        account_id="x",
        email="<script>bad</script>",
        display_name="<b>name</b>",
        plan_type="plus",
        routing_policy="normal",
        status="active",
    )
    window = DetailsWindow(config=AppConfig())
    qtbot.addWidget(window)
    window.set_state(ApplicationState(ApplicationStateKind.READY, accounts=(unsafe,)))
    labels = window.account_container.findChildren(type(window.summary_label))
    assert labels
    assert all(label.textFormat().name == "PlainText" for label in labels)


def test_login_required_state_exposes_direct_accessible_actions(qtbot) -> None:
    window = DetailsWindow(config=AppConfig())
    qtbot.addWidget(window)
    window.set_state(
        ApplicationState(
            ApplicationStateKind.LOGIN_REQUIRED,
            accounts=(account(1),),
            session=DashboardSession(
                authenticated=False,
                password_required=True,
                guest_access_enabled=True,
            ),
        )
    )
    assert not window.login_actions.isHidden()
    assert not window.admin_login_button.isHidden()
    assert not window.guest_login_button.isHidden()
    assert window.admin_login_button.text() == "Sign in"
    assert window.guest_login_button.text() == "Continue as guest"
    assert window.summary_panel.isHidden()
    assert window.scroll.isHidden()
    assert not window.account_container.findChildren(AccountCard)
    with qtbot.waitSignal(window.login_requested, timeout=500) as signal:
        window.guest_login_button.click()
    assert signal.args == ["guest"]


def test_account_card_exposes_text_equivalent_for_quota_colors(qtbot) -> None:
    card = AccountCard(account(1), datetime.now(UTC), "local")
    qtbot.addWidget(card)
    assert card.details_widget.isHidden()
    assert card.toggle_button.name_label.text() == "account-1@example.com"
    assert card.toggle_button.status_label.text() == "Active"
    assert card.toggle_button.primary_label.text() == "85%"
    assert card.toggle_button.weekly_label.text() == "45%"
    assert card.toggle_button.primary_reset_label.text() == "Resets in now"
    assert card.toggle_button.primary_label.property("role") == "quotaValue"
    assert card.toggle_button.primary_label.property("tone") == "green"
    assert card.toggle_button.weekly_label.property("tone") == "amber"
    assert card.toggle_button.primary_divider.objectName() == "quotaDivider"
    assert card.toggle_button.weekly_divider.objectName() == "quotaDivider"
    card.toggle_button.click()
    assert card.toggle_button.isChecked()
    assert card.toggle_button.disclosure.text() == "▾"
    assert not card.details_widget.isHidden()
    card.toggle_button.click()
    assert card.details_widget.isHidden()
    progress = card.findChildren(QuotaProgress)
    assert progress
    assert all(item.accessibleName() == "Remaining quota" for item in progress)
    assert all("% left" in item.accessibleDescription() for item in progress)


def test_collapsed_account_shows_reset_credits_and_quota_countdowns(qtbot) -> None:
    now = datetime(2026, 9, 5, 12, tzinfo=UTC)
    item = replace(
        account(1),
        reset_at_primary=datetime(2026, 9, 5, 14, 30, tzinfo=UTC),
        reset_at_secondary=datetime(2026, 9, 8, 12, tzinfo=UTC),
        available_reset_credits=3,
    )
    card = AccountCard(item, now, "local")
    qtbot.addWidget(card)

    assert card.toggle_button.primary_label.text() == "85%"
    assert card.toggle_button.weekly_label.text() == "45%"
    assert card.toggle_button.primary_reset_label.text() == "Resets in 2h 30m"
    assert card.toggle_button.weekly_reset_label.text() == "Resets in 3d 0h"
    assert card.toggle_button.reset_count_label.text() == "3 available"
    assert not card.toggle_button.reset_count_label.isHidden()
    assert "for quota resets" not in {
        label.text() for label in card.findChildren(type(card.toggle_button.name_label))
    }


def test_collapsed_account_uses_identity_and_separated_quota_blocks(qtbot) -> None:
    window = DetailsWindow(config=AppConfig())
    qtbot.addWidget(window)
    window.set_state(
        ApplicationState(
            ApplicationStateKind.READY,
            accounts=(account(1),),
        )
    )
    window.show()
    qtbot.waitUntil(lambda: window._account_cards["account-1"].height() > 0)
    button = window._account_cards["account-1"].toggle_button

    assert button.height() >= 88
    assert button.name_label.geometry().top() == button.status_label.geometry().top()
    assert button.primary_label.geometry().top() > button.name_label.geometry().top()
    assert button.weekly_label.geometry().top() == button.primary_label.geometry().top()
    assert (
        button.primary_block.geometry().height()
        == button.weekly_block.geometry().height()
    )
    assert (
        button.reset_count_block.geometry().height()
        == button.primary_block.geometry().height()
    )
    reset_font = button.primary_reset_label.font()
    reset_color = button.primary_reset_label.palette().color(
        button.primary_reset_label.foregroundRole()
    )
    for caption in (
        button.primary_caption,
        button.weekly_caption,
        button.reset_count_caption,
    ):
        assert caption.font() == reset_font
        assert not caption.font().bold()
        assert caption.palette().color(caption.foregroundRole()) == reset_color


def test_rate_limited_account_uses_non_active_status_tone(qtbot) -> None:
    limited = replace(
        account(1),
        status="rate_limited",
        usage=AccountUsage(0, 0, None),
    )
    card = AccountCard(limited, datetime.now(UTC), "local")
    qtbot.addWidget(card)
    assert card.toggle_button.status_label.property("tone") == "red"


def test_details_window_can_be_attached_to_the_tray(qtbot) -> None:
    window = DetailsWindow(config=AppConfig())
    qtbot.addWidget(window)
    window.set_tray_attached(True)
    assert window.windowType() == Qt.WindowType.Tool
    window.set_tray_attached(False)
    assert window.windowType() == Qt.WindowType.Window


def test_window_is_positioned_beside_anchor_and_inside_screen(qtbot, qapp) -> None:
    window = QWidget()
    window.resize(220, 160)
    qtbot.addWidget(window)
    window.show()
    available = qapp.primaryScreen().availableGeometry()
    anchor = QRect(available.right() - 20, available.top(), 20, 20)

    assert position_window_near_anchor(window, anchor)
    assert window.frameGeometry().left() >= available.left()
    assert window.frameGeometry().right() <= available.right()
    assert window.frameGeometry().top() >= available.top()
    assert window.frameGeometry().bottom() <= available.bottom()
    assert available.right() - window.frameGeometry().right() <= 12


def test_secondary_window_is_centered_on_details_anchor(qtbot, qapp) -> None:
    window = QWidget()
    window.resize(220, 160)
    qtbot.addWidget(window)
    window.show()
    available = qapp.primaryScreen().availableGeometry()
    anchor = QRect(
        available.center().x() - 180,
        available.center().y() - 220,
        360,
        440,
    )

    assert position_window_centered_on_anchor(window, anchor)
    assert abs(window.frameGeometry().center().x() - anchor.center().x()) <= 1
    assert abs(window.frameGeometry().center().y() - anchor.center().y()) <= 1


def test_missing_tray_geometry_falls_back_to_top_right(qtbot, qapp) -> None:
    window = QWidget()
    window.resize(220, 160)
    qtbot.addWidget(window)
    window.show()
    available = qapp.primaryScreen().availableGeometry()

    assert position_window_near_anchor(window, QRect())
    assert available.right() - window.frameGeometry().right() <= 12
    assert window.frameGeometry().top() - available.top() <= 12
