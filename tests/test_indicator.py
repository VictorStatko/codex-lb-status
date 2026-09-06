"""System-tray indicator tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

pytest.importorskip("PyQt6")

from codex_lb_status.indicator import (
    OUTDATED_DATA_DELAY_MS,
    TrayIndicator,
    _fit_quota_font,
    icon_for_quotas,
    icon_for_tone,
)
from codex_lb_status.models import (
    AccountSummary,
    AccountUsage,
    ApplicationState,
    ApplicationStateKind,
)


def account(
    index: int,
    *,
    status: str = "active",
    usage: AccountUsage | None = None,
    reset_credits: int = 0,
) -> AccountSummary:
    return AccountSummary(
        account_id=str(index),
        email=f"{index}@example.com",
        display_name=f"Account {index}",
        plan_type="plus",
        routing_policy="normal",
        status=status,
        usage=usage or AccountUsage(80, 80, None),
        available_reset_credits=reset_credits,
    )


def test_each_tone_is_distinguishable_with_the_same_round_silhouette(qapp) -> None:
    tones = ("green", "amber", "red", "gray", "attention")
    icons = [icon_for_tone(tone) for tone in tones]
    assert all(not icon.isNull() for icon in icons)
    assert len({icon.cacheKey() for icon in icons}) == len(tones)
    images = [icon.pixmap(64, 64).toImage() for icon in icons]
    alpha_masks = [
        tuple(
            image.pixelColor(x, y).alpha()
            for y in range(image.height())
            for x in range(image.width())
        )
        for image in images
    ]
    assert all(mask == alpha_masks[0] for mask in alpha_masks)


def test_quota_icon_contains_both_exact_quota_values(qapp) -> None:
    base = icon_for_quotas(82, 47).pixmap(64, 64).toImage()
    different_primary = icon_for_quotas(23, 47).pixmap(64, 64).toImage()
    different_weekly_same_tone = icon_for_quotas(82, 48).pixmap(64, 64).toImage()
    assert base != different_primary
    assert base != different_weekly_same_tone


@pytest.mark.parametrize("label", ("5/7", "5/56", "56/78", "56/100", "100/100"))
def test_quota_font_is_the_largest_size_that_fits(qapp, label: str) -> None:
    from PyQt6.QtGui import QFont, QFontMetrics

    maximum = 16
    font = _fit_quota_font(
        QFont(),
        label.partition("/"),
        maximum_pixel_size=maximum,
        available_width=20,
        available_height=20,
    )
    metrics = QFontMetrics(font)
    width = sum(metrics.horizontalAdvance(segment) for segment in label.partition("/"))
    assert width <= 20
    assert metrics.height() <= 20
    if font.pixelSize() < maximum:
        larger = QFont(font)
        larger.setPixelSize(font.pixelSize() + 1)
        larger_metrics = QFontMetrics(larger)
        assert (
            sum(
                larger_metrics.horizontalAdvance(segment)
                for segment in label.partition("/")
            )
            > 20
            or larger_metrics.height() > 20
        )


def test_tray_has_no_tooltip_or_menu() -> None:
    indicator = TrayIndicator()
    try:
        state = ApplicationState(
            ApplicationStateKind.READY,
            accounts=tuple(account(index, reset_credits=index) for index in range(10)),
            server_version="1.25.0",
        )
        indicator.set_state(state)

        assert indicator.tray.contextMenu() is None
        assert indicator.tray.toolTip() == ""
        expected_icon = icon_for_quotas(80, 80).pixmap(64, 64).toImage()
        actual_icon = indicator.tray.icon().pixmap(64, 64).toImage()
        assert actual_icon == expected_icon
    finally:
        indicator.close()


def test_refresh_in_progress_keeps_quota_numbers_during_stale_grace_period(
    qtbot,
) -> None:
    indicator = TrayIndicator(outdated_after_ms=50)
    try:
        state = ApplicationState(
            ApplicationStateKind.READY,
            accounts=(account(1),),
            refreshed_at=datetime.now(UTC),
        )
        indicator.set_state(state)
        quota_icon = indicator.tray.icon().pixmap(64, 64).toImage()

        indicator.mark_data_outdated()
        indicator.set_state(
            ApplicationState(
                ApplicationStateKind.STALE,
                accounts=state.accounts,
                refreshed_at=state.refreshed_at,
            )
        )

        assert indicator.tray.icon().pixmap(64, 64).toImage() == quota_icon
        qtbot.wait(100)
        warning_icon = icon_for_tone("amber").pixmap(64, 64).toImage()
        assert indicator.tray.icon().pixmap(64, 64).toImage() == warning_icon
        assert warning_icon != quota_icon
    finally:
        indicator.close()


def test_repeated_refresh_starts_do_not_reset_stale_grace_period(qtbot) -> None:
    indicator = TrayIndicator(outdated_after_ms=50)
    try:
        state = ApplicationState(
            ApplicationStateKind.READY,
            accounts=(account(1),),
            refreshed_at=datetime.now(UTC),
        )
        indicator.set_state(state)

        indicator.mark_data_outdated()
        qtbot.wait(30)
        indicator.mark_data_outdated()
        qtbot.wait(40)

        assert (
            indicator.tray.icon().pixmap(64, 64).toImage()
            == icon_for_tone("amber").pixmap(64, 64).toImage()
        )
    finally:
        indicator.close()


def test_successful_refresh_cancels_pending_stale_warning(qtbot) -> None:
    indicator = TrayIndicator(outdated_after_ms=50)
    try:
        state = ApplicationState(
            ApplicationStateKind.READY,
            accounts=(account(1),),
            refreshed_at=datetime.now(UTC),
        )
        indicator.set_state(state)
        quota_icon = indicator.tray.icon().pixmap(64, 64).toImage()

        indicator.mark_data_outdated()
        qtbot.wait(20)
        indicator.set_state(state)
        qtbot.wait(60)

        assert indicator.tray.icon().pixmap(64, 64).toImage() == quota_icon
    finally:
        indicator.close()


def test_default_stale_grace_period_is_five_minutes() -> None:
    assert OUTDATED_DATA_DELAY_MS == 5 * 60_000


def test_double_click_requests_details_toggle(qtbot) -> None:
    from PyQt6.QtWidgets import QSystemTrayIcon

    indicator = TrayIndicator()
    try:
        with qtbot.waitSignal(indicator.toggle_details_requested, timeout=500):
            indicator._activated(QSystemTrayIcon.ActivationReason.DoubleClick)
    finally:
        indicator.close()


def test_status_notifier_activate_trigger_requests_details_toggle(qtbot) -> None:
    from PyQt6.QtWidgets import QSystemTrayIcon

    indicator = TrayIndicator()
    try:
        with qtbot.waitSignal(indicator.toggle_details_requested, timeout=500):
            indicator._activated(QSystemTrayIcon.ActivationReason.Trigger)
    finally:
        indicator.close()


def test_trigger_followed_by_double_click_requests_details_once() -> None:
    from PyQt6.QtTest import QSignalSpy
    from PyQt6.QtWidgets import QSystemTrayIcon

    indicator = TrayIndicator()
    try:
        signal = QSignalSpy(indicator.toggle_details_requested)
        indicator._activated(QSystemTrayIcon.ActivationReason.Trigger)
        indicator._activated(QSystemTrayIcon.ActivationReason.DoubleClick)
        assert len(signal) == 1
    finally:
        indicator.close()


def test_context_activation_does_not_open_details() -> None:
    from PyQt6.QtTest import QSignalSpy
    from PyQt6.QtWidgets import QSystemTrayIcon

    indicator = TrayIndicator()
    try:
        signal = QSignalSpy(indicator.toggle_details_requested)
        indicator._activated(QSystemTrayIcon.ActivationReason.Context)
        assert len(signal) == 0
    finally:
        indicator.close()


def test_signed_out_state_does_not_add_a_tooltip() -> None:
    indicator = TrayIndicator()
    try:
        indicator.set_state(
            ApplicationState(
                ApplicationStateKind.LOGIN_REQUIRED,
                accounts=(account(1),),
            )
        )

        assert indicator.tray.toolTip() == ""
    finally:
        indicator.close()
