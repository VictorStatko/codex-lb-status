"""Portable Qt system-tray indicator with double-click activation."""

from __future__ import annotations

import shutil
import subprocess
import time

from .models import ApplicationState, ApplicationStateKind
from .presentation import (
    quota_tone,
    round_percentage,
    summarize_accounts,
)
from .theme import COLORS

try:
    from PyQt6.QtCore import QObject, QPointF, QRectF, Qt, QTimer, pyqtSignal
    from PyQt6.QtGui import (
        QColor,
        QFont,
        QFontMetrics,
        QIcon,
        QPainter,
        QPen,
        QPixmap,
    )
    from PyQt6.QtWidgets import QApplication, QSystemTrayIcon
except ImportError:  # pragma: no cover - exercised only without PyQt6.
    QObject = None


HOST_CHECK_INTERVAL_MS = 2_000
ACTIVATION_DEBOUNCE_MARGIN_MS = 50
OUTDATED_DATA_DELAY_MINUTES = 5
OUTDATED_DATA_DELAY_MS = OUTDATED_DATA_DELAY_MINUTES * 60_000


def _notify_without_tray(title: str, message: str) -> None:
    notify_send = shutil.which("notify-send")
    if notify_send is None:
        return
    try:
        subprocess.run(
            [notify_send, title, message[:240]],
            check=False,
            timeout=2,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return


if QObject is None:

    def icon_for_tone(tone: str):
        raise RuntimeError("PyQt6 >= 6.6 is required for the tray indicator")

    def icon_for_quotas(primary: float | None, weekly: float | None):
        raise RuntimeError("PyQt6 >= 6.6 is required for the tray indicator")

    class TrayIndicator:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("PyQt6 >= 6.6 is required for the tray indicator")

else:
    _TONE_COLORS = {
        "green": QColor(COLORS["green"]),
        "amber": QColor("#d28a2d"),
        "red": QColor(COLORS["red"]),
        "gray": QColor(COLORS["gray"]),
        "attention": QColor(COLORS["focus"]),
    }

    def _tone_color(tone: str) -> QColor:
        return _TONE_COLORS.get(tone, _TONE_COLORS["gray"])

    def _draw_icon(tone: str) -> QIcon:
        color = _tone_color(tone)
        icon = QIcon()
        for size in (16, 24, 32, 48, 64):
            pixmap = QPixmap(size, size)
            pixmap.fill(QColor(0, 0, 0, 0))
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(QPen(color, max(2, size // 10)))
            painter.setBrush(color)
            margin = max(1, size // 8)
            painter.drawEllipse(
                margin,
                margin,
                size - margin * 2,
                size - margin * 2,
            )
            painter.setPen(QPen(QColor("white"), max(1, size // 12)))
            painter.setBrush(QColor("white"))
            if tone == "green":
                painter.drawLine(size // 3, size // 2, size // 2 - 1, size * 2 // 3)
                painter.drawLine(size // 2 - 1, size * 2 // 3, size * 2 // 3, size // 3)
            elif tone == "red":
                painter.drawLine(size // 3, size // 3, size * 2 // 3, size * 2 // 3)
                painter.drawLine(size * 2 // 3, size // 3, size // 3, size * 2 // 3)
            elif tone in ("amber", "attention"):
                painter.drawLine(size // 2, size // 3, size // 2, size * 2 // 3)
                painter.drawPoint(size // 2, size * 3 // 4)
            else:
                painter.drawLine(size // 3, size // 2, size * 2 // 3, size // 2)
            painter.end()
            icon.addPixmap(pixmap)
        return icon

    def icon_for_tone(tone: str) -> QIcon:
        return _draw_icon(tone)

    _QUOTA_TEXT_COLORS = {
        "green": QColor("#55d98b"),
        "amber": QColor("#f0ac48"),
        "red": QColor("#f06b68"),
        "gray": QColor("#aeb5c0"),
    }

    def _quota_label(value: float | None) -> str:
        rounded = round_percentage(value)
        return "–" if rounded is None else str(max(0, min(100, rounded)))

    def _fit_quota_font(
        font: QFont,
        segments: tuple[str, ...],
        *,
        maximum_pixel_size: int,
        available_width: float,
        available_height: float,
    ) -> QFont:
        """Return the largest condensed bold font that fits the icon bounds."""

        font.setBold(True)
        font.setStretch(QFont.Stretch.Condensed)
        for pixel_size in range(maximum_pixel_size, 2, -1):
            font.setPixelSize(pixel_size)
            metrics = QFontMetrics(font)
            if (
                sum(metrics.horizontalAdvance(segment) for segment in segments)
                <= available_width
                and metrics.height() <= available_height
            ):
                return font
        font.setPixelSize(3)
        return font

    def _draw_quota_icon(primary: float | None, weekly: float | None) -> QIcon:
        primary_label = _quota_label(primary)
        weekly_label = _quota_label(weekly)
        separator = "/"
        primary_color = _QUOTA_TEXT_COLORS[quota_tone(primary).value]
        weekly_color = _QUOTA_TEXT_COLORS[quota_tone(weekly).value]
        icon = QIcon()
        for size in (16, 20, 22, 24, 32, 48, 64, 96):
            pixmap = QPixmap(size, size)
            pixmap.fill(QColor(0, 0, 0, 0))
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

            inset = max(0.5, size * 0.045)
            bounds = QRectF(inset, inset, size - inset * 2, size - inset * 2)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#1b1f24"))
            radius = size * 0.22
            painter.drawRoundedRect(bounds, radius, radius)

            font = _fit_quota_font(
                painter.font(),
                (primary_label, separator, weekly_label),
                maximum_pixel_size=max(3, round(size * 0.72)),
                available_width=bounds.width(),
                available_height=bounds.height(),
            )
            painter.setFont(font)
            metrics = QFontMetrics(font)
            segments = (
                (primary_label, primary_color),
                (separator, QColor("#d8dde4")),
                (weekly_label, weekly_color),
            )
            widths = tuple(metrics.horizontalAdvance(text) for text, _color in segments)
            x = (size - sum(widths)) / 2
            baseline = (size - metrics.height()) / 2 + metrics.ascent()
            for (text, color), width in zip(segments, widths, strict=True):
                painter.setPen(color)
                painter.drawText(QPointF(x, baseline), text)
                x += width
            painter.end()
            icon.addPixmap(pixmap)
        return icon

    def icon_for_quotas(primary: float | None, weekly: float | None) -> QIcon:
        """Render the exact remaining 5-hour/weekly percentages on one line."""

        return _draw_quota_icon(primary, weekly)

    class TrayIndicator(QObject):
        """Own one menu-free tray icon with native double-click activation."""

        toggle_details_requested = pyqtSignal()
        host_available_changed = pyqtSignal(bool)

        def __init__(
            self,
            parent: QObject | None = None,
            background_launch: bool = False,
            outdated_after_ms: int = OUTDATED_DATA_DELAY_MS,
        ):
            super().__init__(parent)
            self.tray = QSystemTrayIcon(self)
            self.tray.activated.connect(self._activated)
            self._state = ApplicationState.loading()
            self._outdated_after_ms = max(0, outdated_after_ms)
            self._data_outdated = False
            self._outdated_timer = QTimer(self)
            self._outdated_timer.setSingleShot(True)
            self._outdated_timer.timeout.connect(self._mark_data_outdated)
            self._last_activation_at: float | None = None
            self._activation_debounce_seconds = (
                QApplication.doubleClickInterval() + ACTIVATION_DEBOUNCE_MARGIN_MS
            ) / 1_000
            self._available = QSystemTrayIcon.isSystemTrayAvailable()
            self._host_timer = QTimer(self)
            self._host_timer.setInterval(HOST_CHECK_INTERVAL_MS)
            self._host_timer.timeout.connect(self._check_host)
            # QSystemTrayIcon warns and some hosts ignore the item when it is
            # made visible before an icon has been assigned.  The loading
            # state is replaced by set_state as soon as the service starts.
            self.tray.setIcon(icon_for_tone("gray"))
            if self._available:
                self.tray.show()
            else:
                self._host_timer.start()
                if background_launch:
                    _notify_without_tray(
                        "Codex LB Status",
                        "No system-tray host is available; status will remain "
                        "accessible from the details window.",
                    )

        @property
        def host_available(self) -> bool:
            return self._available

        @property
        def anchor_geometry(self):
            """Return the tray icon rectangle in global screen coordinates."""

            return self.tray.geometry()

        @property
        def state(self) -> ApplicationState:
            return self._state

        def set_state(self, state: ApplicationState) -> None:
            self._state = state
            if state.kind is ApplicationStateKind.STALE and state.has_data:
                self._start_outdated_timer()
            else:
                self._clear_outdated_state()

            summary = summarize_accounts(state.accounts)
            if state.kind is ApplicationStateKind.READY and (
                summary.primary is not None or summary.secondary is not None
            ):
                icon = icon_for_quotas(summary.primary, summary.secondary)
            elif (
                state.kind is ApplicationStateKind.STALE
                and state.has_data
                and not self._data_outdated
            ):
                # Keep the last useful numbers visible while the stale-data
                # grace period is running.
                if summary.primary is not None or summary.secondary is not None:
                    icon = icon_for_quotas(summary.primary, summary.secondary)
                else:
                    icon = icon_for_tone(summary.tone.value)
            else:
                icon = icon_for_tone(self._tone_for_state(state, summary))
            self.tray.setIcon(icon)

        def mark_data_outdated(self) -> None:
            """Start the stale-data grace period for an in-flight refresh."""

            if self._state.has_data:
                self._start_outdated_timer()

        def _start_outdated_timer(self) -> None:
            if self._data_outdated or self._outdated_timer.isActive():
                return
            self._outdated_timer.start(self._outdated_after_ms)

        def _mark_data_outdated(self) -> None:
            if not self._state.has_data:
                return
            self._data_outdated = True
            self.tray.setIcon(icon_for_tone("amber"))

        def _clear_outdated_state(self) -> None:
            self._outdated_timer.stop()
            self._data_outdated = False

        def _tone_for_state(self, state, summary) -> str:
            if state.kind in (
                ApplicationStateKind.LOGIN_REQUIRED,
                ApplicationStateKind.ERROR,
                ApplicationStateKind.STALE,
            ):
                return {
                    ApplicationStateKind.LOGIN_REQUIRED: "attention",
                    ApplicationStateKind.ERROR: "red",
                    ApplicationStateKind.STALE: "amber",
                }[state.kind]
            return summary.tone.value

        def _activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
            # StatusNotifier has only a generic Activate method. Ubuntu GNOME
            # invokes it after a user double-click, which Qt reports as
            # Trigger. Native tray backends can report DoubleClick directly.
            if reason in (
                QSystemTrayIcon.ActivationReason.Trigger,
                QSystemTrayIcon.ActivationReason.DoubleClick,
            ):
                activated_at = time.monotonic()
                if (
                    self._last_activation_at is not None
                    and activated_at - self._last_activation_at
                    < self._activation_debounce_seconds
                ):
                    return
                self._last_activation_at = activated_at
                self.toggle_details_requested.emit()

        def _check_host(self) -> None:
            available = QSystemTrayIcon.isSystemTrayAvailable()
            if available == self._available:
                return
            self._available = available
            self.host_available_changed.emit(available)
            if available:
                self.tray.show()
                self._host_timer.stop()
            else:
                self.tray.hide()

        def close(self) -> None:
            self._host_timer.stop()
            self.tray.hide()


__all__ = [
    "ACTIVATION_DEBOUNCE_MARGIN_MS",
    "OUTDATED_DATA_DELAY_MINUTES",
    "OUTDATED_DATA_DELAY_MS",
    "TrayIndicator",
    "icon_for_quotas",
    "icon_for_tone",
]
