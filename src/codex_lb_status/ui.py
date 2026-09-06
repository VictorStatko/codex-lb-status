"""Qt Widgets details, settings, and authentication dialogs."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime

from .autostart import AutostartManager
from .config import (
    AppConfig,
    ConfigError,
    SettingsTransactionError,
    apply_settings_transaction,
    default_config,
    normalize_base_url,
    validate_display_time_zone,
)
from .models import ApplicationState, ApplicationStateKind
from .presentation import (
    account_connection_is_healthy,
    account_summary_lines,
    account_title,
    display_routing_policy,
    display_status,
    format_absolute_timestamp,
    format_pool_headline,
    format_reset_countdown,
    quota_tone,
    round_percentage,
    sanitize_text,
    sort_accounts,
    summarize_accounts,
    tooltip_text,
)
from .theme import apply_theme

try:
    from PyQt6.QtCore import Qt, QUrl, pyqtSignal
    from PyQt6.QtGui import QAction, QCursor, QDesktopServices, QIcon
    from PyQt6.QtWidgets import (
        QApplication,
        QCheckBox,
        QComboBox,
        QDialog,
        QDialogButtonBox,
        QFormLayout,
        QFrame,
        QGridLayout,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMainWindow,
        QMenu,
        QMessageBox,
        QProgressBar,
        QPushButton,
        QScrollArea,
        QSizePolicy,
        QToolButton,
        QVBoxLayout,
        QWidget,
    )
except ImportError:  # pragma: no cover - exercised only without PyQt6.
    QApplication = None


def _plain_label(text: str = "", parent=None):
    label = QLabel(text, parent)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    return label


def _set_safe_text(label: QLabel, text: object) -> None:
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setText(str(text))


def _set_role(label: QLabel, role: str) -> QLabel:
    label.setProperty("role", role)
    return label


def _set_dynamic_property(widget: QWidget, name: str, value: str) -> None:
    widget.setProperty(name, value)
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def remove_button_icons(widget: QWidget) -> None:
    """Prevent the platform style from adding icons to action buttons."""

    for button in widget.findChildren(QPushButton):
        button.setIcon(QIcon())


def configure_modal_dialog(dialog: QDialog) -> None:
    """Keep a dialog above its parent without making it globally topmost."""

    dialog.setWindowModality(Qt.WindowModality.WindowModal)


MESSAGE_BOX_TEXT_MIN_WIDTH = 340


def ensure_message_box_width(message: QMessageBox) -> None:
    """Keep the message-box title and primary message from being elided."""

    layout = message.layout()
    if isinstance(layout, QGridLayout):
        layout.setColumnMinimumWidth(1, MESSAGE_BOX_TEXT_MIN_WIDTH)


def open_message_box(message: QMessageBox) -> None:
    """Open a message box wide enough to show its native window title."""

    ensure_message_box_width(message)
    message.open()


def _available_geometry_size() -> tuple[int, int]:
    screen = QApplication.primaryScreen()
    if screen is None:
        return 500, 700
    geometry = screen.availableGeometry()
    return min(500, geometry.width()), max(1, geometry.height())


MIN_DETAILS_HEIGHT = 240


def details_window_height(available_height: int) -> int:
    """Use the complete usable screen height for the Details window."""

    return max(1, available_height)


def position_window_near_anchor(window, anchor, margin: int = 8) -> bool:
    """Place a top-level window at the right side of the tray's screen.

    Some StatusNotifier hosts do not expose tray geometry. The pointer's
    screen and its top-right available corner provide a deterministic fallback.
    """

    if QApplication is None:
        return False
    anchor_valid = anchor is not None and anchor.isValid() and not anchor.isNull()
    screen = (
        QApplication.screenAt(anchor.center())
        if anchor_valid
        else QApplication.screenAt(QCursor.pos())
    )
    screen = screen or QApplication.primaryScreen()
    if screen is None:
        return False

    handle = window.windowHandle()
    if handle is not None and handle.screen() is not screen:
        window.setScreen(screen)

    available = screen.availableGeometry()
    frame = window.frameGeometry()
    width = max(frame.width(), window.width())
    height = max(frame.height(), window.height())

    x = available.right() - width - margin + 1
    if anchor_valid and anchor.center().y() <= available.center().y():
        y = anchor.bottom() + margin
    elif anchor_valid:
        y = anchor.top() - height - margin
    else:
        y = available.top() + margin

    min_x = available.left() + margin
    max_x = max(min_x, available.right() - width - margin + 1)
    min_y = available.top() + margin
    max_y = max(min_y, available.bottom() - height - margin + 1)
    window.move(min(max(x, min_x), max_x), min(max(y, min_y), max_y))
    return True


def position_window_centered_on_anchor(window, anchor, margin: int = 8) -> bool:
    """Center a secondary window over an existing window or screen anchor."""

    if QApplication is None:
        return False
    anchor_valid = anchor is not None and anchor.isValid() and not anchor.isNull()
    screen = (
        QApplication.screenAt(anchor.center())
        if anchor_valid
        else QApplication.screenAt(QCursor.pos())
    )
    screen = screen or QApplication.primaryScreen()
    if screen is None:
        return False

    handle = window.windowHandle()
    if handle is not None and handle.screen() is not screen:
        window.setScreen(screen)

    available = screen.availableGeometry()
    frame = window.frameGeometry()
    width = max(frame.width(), window.width())
    height = max(frame.height(), window.height())
    anchor_center = anchor.center() if anchor_valid else available.center()

    x = anchor_center.x() - width // 2
    y = anchor_center.y() - height // 2
    min_x = available.left() + margin
    max_x = max(min_x, available.right() - width - margin + 1)
    min_y = available.top() + margin
    max_y = max(min_y, available.bottom() - height - margin + 1)
    window.move(min(max(x, min_x), max_x), min(max(y, min_y), max_y))
    return True


if QApplication is None:

    class AccountCard:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("PyQt6 >= 6.6 is required for account cards")

    class QuotaProgress:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("PyQt6 >= 6.6 is required for quota progress")

    class DetailsWindow:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("PyQt6 >= 6.6 is required for the details window")

    class SettingsDialog:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("PyQt6 >= 6.6 is required for Settings")

    class PasswordDialog:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("PyQt6 >= 6.6 is required for login dialogs")

    class GuestPasswordDialog(PasswordDialog):
        pass

    class TotpDialog(PasswordDialog):
        pass

else:

    def _status_tone(account) -> str:
        return "green" if account_connection_is_healthy(account) else "red"

    class QuotaProgress(QProgressBar):
        """Compact read-only quota meter with a non-color text equivalent."""

        def __init__(self, value: float | None, parent: QWidget | None = None):
            super().__init__(parent)
            self.setObjectName("quotaProgress")
            self.setRange(0, 100)
            self.setTextVisible(False)
            self.setFixedHeight(6)
            self.setValue(round(value or 0))
            tone = quota_tone(value).value
            self.setProperty("tone", tone)
            readable = "Quota unavailable" if value is None else f"{round(value)}% left"
            self.setAccessibleName("Remaining quota")
            self.setAccessibleDescription(readable)
            self.setToolTip(readable)

    class AccountSummaryButton(QToolButton):
        """Full-width disclosure control for one collapsed account row."""

        def __init__(
            self,
            account,
            now: datetime | None,
            parent: QWidget | None = None,
        ):
            super().__init__(parent)
            self._account_name = account_title(account)
            self.setObjectName("accountHeader")
            self.setCheckable(True)
            self.setAutoRaise(True)
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            self.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Fixed,
            )

            row = QHBoxLayout(self)
            row.setContentsMargins(13, 8, 13, 8)
            row.setSpacing(10)
            self.disclosure = _plain_label("▸")
            self.disclosure.setObjectName("disclosure")
            self.disclosure.setAlignment(Qt.AlignmentFlag.AlignCenter)
            row.addWidget(self.disclosure)

            content = QVBoxLayout()
            content.setContentsMargins(0, 0, 0, 0)
            content.setSpacing(4)
            identity_row = QHBoxLayout()
            identity_row.setContentsMargins(0, 0, 0, 0)
            identity_row.setSpacing(8)

            account_email = sanitize_text(account.email, 120)
            self.name_label = _plain_label(account_email)
            self.name_label.setObjectName("accountName")
            self.name_label.setWordWrap(False)
            self.name_label.setSizePolicy(
                QSizePolicy.Policy.Ignored,
                QSizePolicy.Policy.Preferred,
            )
            self.name_label.setToolTip(tooltip_text(account_email, 200))
            identity_row.addWidget(self.name_label, 1)

            self.status_label = _plain_label(display_status(account.status))
            self.status_label.setObjectName("accountStatus")
            self.status_label.setWordWrap(False)
            self.status_label.setProperty("tone", _status_tone(account))
            identity_row.addWidget(self.status_label)
            content.addLayout(identity_row)

            usage = account.usage
            primary = usage.primary_remaining_percent if usage else None
            secondary = usage.secondary_remaining_percent if usage else None
            (
                self.primary_block,
                self.primary_label,
                self.primary_caption,
                self.primary_reset_label,
            ) = self._quota_block(
                "5h",
                primary,
                account.reset_at_primary,
                now,
            )
            (
                self.weekly_block,
                self.weekly_label,
                self.weekly_caption,
                self.weekly_reset_label,
            ) = self._quota_block(
                "W",
                secondary,
                account.reset_at_secondary,
                now,
            )

            metadata_row = QHBoxLayout()
            metadata_row.setContentsMargins(0, 0, 0, 0)
            metadata_row.setSpacing(12)
            metadata_row.addWidget(self.primary_block, 1)
            self.primary_divider = self._quota_divider()
            metadata_row.addWidget(self.primary_divider)
            metadata_row.addWidget(self.weekly_block, 1)
            self.weekly_divider = self._quota_divider()
            metadata_row.addWidget(self.weekly_divider)

            reset_count = account.available_reset_credits
            self.reset_count_block = QWidget()
            self.reset_count_block.setObjectName("quotaColumn")
            reset_layout = QVBoxLayout(self.reset_count_block)
            reset_layout.setContentsMargins(9, 5, 9, 5)
            reset_layout.setSpacing(1)
            self.reset_count_caption = _set_role(
                _plain_label("Reset credits"), "quotaCaption"
            )
            self.reset_count_label = _set_role(
                _plain_label(f"{reset_count} available"), "quotaValue"
            )
            self.reset_count_label.setObjectName("quotaColumnValue")
            reset_layout.addWidget(self.reset_count_caption)
            reset_layout.addWidget(self.reset_count_label)
            reset_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
            self.reset_count_label.setToolTip(
                f"{reset_count} reset credit{'s' if reset_count != 1 else ''} available"
            )
            metadata_row.addWidget(self.reset_count_block, 1)
            content.addLayout(metadata_row)
            row.addLayout(content, 1)

            for label in (
                self.disclosure,
                self.name_label,
                self.status_label,
                self.primary_caption,
                self.primary_label,
                self.primary_reset_label,
                self.weekly_caption,
                self.weekly_label,
                self.weekly_reset_label,
                self.reset_count_caption,
                self.reset_count_label,
            ):
                label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            for block in (
                self.primary_block,
                self.weekly_block,
                self.reset_count_block,
                self.primary_divider,
                self.weekly_divider,
            ):
                block.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

            self.setAccessibleName(f"Account {self._account_name}")
            self.setToolTip(f"Expand details for {self._account_name}")
            self.toggled.connect(self._sync_disclosure)
            self._sync_disclosure(False)

        def _quota_block(
            self,
            name: str,
            value: float | None,
            reset_at: datetime | None,
            now: datetime | None,
        ) -> tuple[QWidget, QLabel, QLabel, QLabel]:
            formatted = "—" if value is None else f"{round_percentage(value)}%"
            countdown = format_reset_countdown(reset_at, now)
            window_name = "5-hour" if name == "5h" else "Weekly"

            block = QWidget()
            block.setObjectName("quotaColumn")
            block_layout = QVBoxLayout(block)
            block_layout.setContentsMargins(0, 2, 0, 2)
            block_layout.setSpacing(1)

            caption = _set_role(_plain_label(window_name), "quotaCaption")
            label = _set_role(
                _plain_label("Unavailable" if value is None else formatted),
                "quotaValue",
            )
            label.setObjectName("quotaColumnValue")
            _set_dynamic_property(label, "tone", quota_tone(value).value)
            reset_label = _set_role(
                _plain_label(
                    f"Resets in {countdown}" if countdown else "No reset scheduled"
                ),
                "quotaReset",
            )
            reset_label.setObjectName("quotaColumnReset")
            block_layout.addWidget(caption)
            block_layout.addWidget(label)
            block_layout.addWidget(reset_label)

            for block_label in (caption, label, reset_label):
                block_label.setWordWrap(False)
            available = "unavailable" if value is None else f"{formatted} left"
            tooltip = f"{window_name} quota: {available}"
            if countdown:
                tooltip += f"; resets in {countdown}"
            label.setToolTip(tooltip)
            reset_label.setToolTip(tooltip)
            return block, label, caption, reset_label

        def _quota_divider(self) -> QFrame:
            divider = QFrame()
            divider.setObjectName("quotaDivider")
            divider.setFrameShape(QFrame.Shape.VLine)
            return divider

        def _sync_disclosure(self, expanded: bool) -> None:
            self.disclosure.setText("▾" if expanded else "▸")
            action = "Collapse" if expanded else "Expand"
            state = "expanded" if expanded else "collapsed"
            self.setToolTip(f"{action} details for {self._account_name}")
            self.setAccessibleDescription(
                f"{state.title()}. {action} all account details."
            )

    class AccountCard(QFrame):
        """A collapsed account row with on-demand read-only details."""

        def __init__(
            self,
            account,
            now: datetime | None,
            display_time_zone: str,
            parent: QWidget | None = None,
        ):
            super().__init__(parent)
            self.setObjectName("accountCard")
            self.setFrameShape(QFrame.Shape.NoFrame)
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self.setAccessibleName(f"Account {account_title(account)}")

            layout = QVBoxLayout(self)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)
            self.toggle_button = AccountSummaryButton(account, now, self)
            layout.addWidget(self.toggle_button)

            self.details_widget = QWidget(self)
            self.details_widget.setObjectName("accountDetails")
            details_layout = QVBoxLayout(self.details_widget)
            details_layout.setContentsMargins(15, 12, 15, 14)
            details_layout.setSpacing(9)
            self.details_widget.setVisible(False)
            layout.addWidget(self.details_widget)
            self.toggle_button.toggled.connect(self._set_expanded)

            identity_parts = [account.email, account.plan_type]
            identity = _set_role(
                _plain_label("  ·  ".join(map(str, identity_parts))), "muted"
            )
            identity.setToolTip(tooltip_text(account.email, 240))
            details_layout.addWidget(identity)

            routing = _set_role(
                _plain_label(
                    f"{display_routing_policy(account.routing_policy)} routing"
                ),
                "quiet",
            )
            details_layout.addWidget(routing)

            usage = account.usage
            windows = (
                (
                    "5-hour",
                    usage.primary_remaining_percent if usage else None,
                    account.reset_at_primary,
                ),
                (
                    "Weekly",
                    usage.secondary_remaining_percent if usage else None,
                    account.reset_at_secondary,
                ),
                (
                    "Monthly",
                    usage.monthly_remaining_percent if usage else None,
                    account.reset_at_monthly,
                ),
            )
            for label_text, value, reset_at in windows:
                if value is None and reset_at is None:
                    continue
                quota_header = QHBoxLayout()
                quota_header.setSpacing(8)
                quota_header.addWidget(_plain_label(label_text))
                quota_header.addStretch(1)
                remaining = "Unavailable" if value is None else f"{round(value)}%"
                value_label = _set_role(_plain_label(remaining), "quotaValue")
                quota_header.addWidget(value_label)
                details_layout.addLayout(quota_header)
                details_layout.addWidget(QuotaProgress(value, self))
                countdown = format_reset_countdown(reset_at, now)
                if countdown:
                    reset_label = _set_role(
                        _plain_label(f"Resets in {countdown}"), "quiet"
                    )
                    reset_label.setAlignment(Qt.AlignmentFlag.AlignRight)
                    details_layout.addWidget(reset_label)

            details = account_summary_lines(account, now, display_time_zone)[3:]
            details = [
                line for line in details if not line.startswith(("5h:", "W:", "M:"))
            ]
            if account.deactivation_reason:
                details.insert(
                    0,
                    f"Reason: {sanitize_text(account.deactivation_reason, 180)}",
                )
            if details:
                metadata = _set_role(_plain_label("\n".join(details)), "quiet")
                metadata.setToolTip(tooltip_text("\n".join(details), 600))
                details_layout.addWidget(metadata)

            description = "\n".join(account_summary_lines(account, now))
            self.setAccessibleDescription(sanitize_text(description, 600))

        def _set_expanded(self, expanded: bool) -> None:
            self.details_widget.setVisible(expanded)
            self.updateGeometry()

    class DetailsWindow(QMainWindow):
        """Reusable details window that renders every application state."""

        settings_requested = pyqtSignal()
        login_requested = pyqtSignal(str)
        sign_out_requested = pyqtSignal()
        launch_at_login_changed = pyqtSignal(bool)
        quit_requested = pyqtSignal()
        dismissed = pyqtSignal()

        def __init__(
            self,
            coordinator=None,
            config: AppConfig | None = None,
            autostart_manager: AutostartManager | None = None,
            tray_available: Callable[[], bool] | None = None,
            parent: QWidget | None = None,
        ):
            super().__init__(parent)
            self.coordinator = None
            self.config = config or default_config()
            self.autostart_manager = autostart_manager or AutostartManager()
            self._tray_available = tray_available or (lambda: False)
            self._shown_once = False
            self._auto_size_enabled = True
            self._resizing_to_fit = False
            self._account_cards: dict[str, AccountCard] = {}
            self.setObjectName("detailsWindow")
            self.setWindowTitle("Codex LB Status")
            self.setMinimumSize(420, MIN_DETAILS_HEIGHT)
            width, height = _available_geometry_size()
            self.resize(width, height)
            self._build_ui()
            apply_theme(self)
            self.set_coordinator(coordinator)
            if coordinator is None:
                self.set_state(ApplicationState.loading())

        def _build_ui(self) -> None:
            root = QWidget(self)
            root_layout = QVBoxLayout(root)
            root_layout.setContentsMargins(20, 18, 20, 16)
            root_layout.setSpacing(13)

            header = QHBoxLayout()
            header.setSpacing(12)
            self.updated_label = _set_role(_plain_label(), "muted")
            self.updated_label.setObjectName("updatedLabel")
            header.addWidget(self.updated_label, 1, Qt.AlignmentFlag.AlignVCenter)
            self.refresh_button = QPushButton("Refresh")
            self.refresh_button.setObjectName("primaryButton")
            self.refresh_button.setToolTip("Refresh account status now")
            self.refresh_button.setAccessibleDescription(
                "Fetch the latest account status from Codex LB"
            )
            header.addWidget(self.refresh_button, 0, Qt.AlignmentFlag.AlignTop)
            root_layout.addLayout(header)

            self.spinner = QProgressBar()
            self.spinner.setObjectName("loadingBar")
            self.spinner.setRange(0, 0)
            self.spinner.setTextVisible(False)
            self.spinner.setFixedHeight(4)
            self.spinner.setAccessibleName("Refreshing account status")
            self.spinner.setVisible(False)
            root_layout.addWidget(self.spinner)

            self.summary_panel = QFrame()
            self.summary_panel.setObjectName("summaryPanel")
            summary_layout = QHBoxLayout(self.summary_panel)
            summary_layout.setContentsMargins(15, 12, 15, 12)
            summary_layout.setSpacing(13)
            (
                self.primary_summary,
                self.primary_caption,
                self.primary_increase,
            ) = self._summary_item(
                summary_layout,
                "5-hour",
                show_metadata=True,
            )
            summary_layout.addWidget(self._summary_divider())
            self.weekly_summary_item = QWidget()
            weekly_layout = QVBoxLayout(self.weekly_summary_item)
            weekly_layout.setContentsMargins(0, 0, 0, 0)
            weekly_layout.setSpacing(2)
            weekly_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
            self.weekly_caption = _set_role(_plain_label("Weekly"), "quiet")
            self.weekly_summary = _set_role(_plain_label("—"), "value")
            self.weekly_increase = _set_role(_plain_label(), "summaryMeta")
            weekly_layout.addWidget(self.weekly_caption)
            weekly_layout.addWidget(self.weekly_summary)
            weekly_layout.addWidget(self.weekly_increase)
            summary_layout.addWidget(
                self.weekly_summary_item,
                1,
                Qt.AlignmentFlag.AlignTop,
            )
            self.weekly_divider = self._summary_divider()
            summary_layout.addWidget(self.weekly_divider)
            (
                self.accounts_summary,
                self.accounts_caption,
                _metadata,
            ) = self._summary_item(summary_layout, "Active accounts")
            self.summary_label = _plain_label()
            self.summary_label.setObjectName("summaryLabel")
            self.summary_label.setVisible(False)
            summary_layout.addWidget(self.summary_label)
            root_layout.addWidget(self.summary_panel)

            self.banner = _plain_label()
            self.banner.setObjectName("statusBanner")
            self.banner.setAccessibleName("Application status")
            self.banner.setVisible(False)
            root_layout.addWidget(self.banner)

            self.login_actions = QWidget()
            self.login_actions.setObjectName("loginActions")
            self.login_actions.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Expanding,
            )
            login_layout = QVBoxLayout(self.login_actions)
            login_layout.setContentsMargins(28, 20, 28, 20)
            login_layout.setSpacing(12)
            login_layout.addStretch(1)
            self.login_prompt = _set_role(
                _plain_label("Choose how to access this Codex LB server."),
                "section",
            )
            self.login_prompt.setAlignment(Qt.AlignmentFlag.AlignCenter)
            login_layout.addWidget(self.login_prompt)

            login_buttons = QWidget()
            login_buttons.setMaximumWidth(300)
            button_layout = QVBoxLayout(login_buttons)
            button_layout.setContentsMargins(0, 0, 0, 0)
            button_layout.setSpacing(8)
            self.admin_login_button = QPushButton("Sign in")
            self.admin_login_button.setObjectName("primaryButton")
            self.admin_login_button.clicked.connect(
                lambda: self.login_requested.emit("admin")
            )
            self.guest_login_button = QPushButton("Continue as guest")
            self.guest_login_button.clicked.connect(
                lambda: self.login_requested.emit("guest")
            )
            button_layout.addWidget(self.admin_login_button)
            button_layout.addWidget(self.guest_login_button)
            login_layout.addWidget(
                login_buttons,
                0,
                Qt.AlignmentFlag.AlignHCenter,
            )
            self.login_privacy = _set_role(
                _plain_label("Credentials are used only for this sign-in."),
                "quiet",
            )
            self.login_privacy.setAlignment(Qt.AlignmentFlag.AlignCenter)
            login_layout.addWidget(self.login_privacy)
            login_layout.addStretch(1)
            self.login_actions.setVisible(False)
            root_layout.addWidget(self.login_actions, 1)

            account_heading = QHBoxLayout()
            self.accounts_title = _set_role(_plain_label("Accounts"), "section")
            account_heading.addWidget(self.accounts_title)
            account_heading.addStretch(1)
            self.account_count_label = _set_role(_plain_label(), "muted")
            account_heading.addWidget(self.account_count_label)
            root_layout.addLayout(account_heading)

            self.scroll = QScrollArea()
            self.scroll.setObjectName("accountScroll")
            self.scroll.setWidgetResizable(True)
            self.scroll.setHorizontalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            )
            self.account_container = QWidget()
            self.account_layout = QVBoxLayout(self.account_container)
            self.account_layout.setContentsMargins(0, 0, 2, 0)
            self.account_layout.setSpacing(9)
            self.scroll.setWidget(self.account_container)
            root_layout.addWidget(self.scroll, 1)

            footer = QFrame()
            footer.setObjectName("footerBar")
            footer_layout = QHBoxLayout(footer)
            footer_layout.setContentsMargins(0, 12, 0, 0)
            footer_layout.setSpacing(10)

            self.launch_at_login = QCheckBox("Launch at login")
            self.launch_at_login.setObjectName("launchAtLogin")
            self.launch_at_login.setChecked(self.autostart_manager.enabled)
            self.launch_at_login.setToolTip(
                "Start Codex LB Status automatically after signing in"
            )
            self.launch_at_login.toggled.connect(self.launch_at_login_changed)
            footer_layout.addWidget(self.launch_at_login)
            footer_layout.addStretch(1)

            self.actions_button = QToolButton()
            self.actions_button.setObjectName("actionsButton")
            self.actions_button.setText("Actions")
            self.actions_button.setPopupMode(
                QToolButton.ToolButtonPopupMode.InstantPopup
            )
            self.actions_button.setToolButtonStyle(
                Qt.ToolButtonStyle.ToolButtonTextBesideIcon
            )
            self.actions_button.setAccessibleName("Actions")
            self.actions_button.setToolTip("Open application actions")
            self.actions_menu = QMenu(self.actions_button)
            self.settings_action = QAction("Settings", self.actions_menu)
            self.settings_action.triggered.connect(self.settings_requested)
            self.actions_menu.addAction(self.settings_action)
            self.dashboard_action = QAction("Open dashboard", self.actions_menu)
            self.dashboard_action.triggered.connect(self.open_dashboard)
            self.actions_menu.addAction(self.dashboard_action)
            self.actions_menu.addSeparator()
            self.sign_out_action = QAction("Sign out", self.actions_menu)
            self.sign_out_action.setToolTip(
                "Remove this server's saved session from the desktop companion"
            )
            self.sign_out_action.triggered.connect(self.sign_out_requested)
            self.sign_out_action.setVisible(False)
            self.actions_menu.addAction(self.sign_out_action)
            self.stop_action = QAction("Stop indicator", self.actions_menu)
            self.stop_action.setToolTip("Close Codex LB Status")
            self.stop_action.triggered.connect(self.quit_requested)
            self.actions_menu.addAction(self.stop_action)
            self.actions_button.setMenu(self.actions_menu)
            footer_layout.addWidget(self.actions_button)
            root_layout.addWidget(footer)
            self.setCentralWidget(root)

        def _summary_item(
            self,
            layout: QHBoxLayout,
            caption: str,
            *,
            show_metadata: bool = False,
        ):
            container = QWidget()
            item_layout = QVBoxLayout(container)
            item_layout.setContentsMargins(0, 0, 0, 0)
            item_layout.setSpacing(2)
            item_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
            caption_label = _set_role(_plain_label(caption), "quiet")
            value_label = _set_role(_plain_label("—"), "value")
            metadata_label = _set_role(_plain_label(), "summaryMeta")
            metadata_label.setVisible(show_metadata)
            item_layout.addWidget(caption_label)
            item_layout.addWidget(value_label)
            item_layout.addWidget(metadata_label)
            layout.addWidget(container, 1, Qt.AlignmentFlag.AlignTop)
            return value_label, caption_label, metadata_label

        def _set_increase_countdown(
            self,
            label: QLabel,
            timestamp: datetime | None,
            now: datetime,
        ) -> None:
            countdown = format_reset_countdown(timestamp, now)
            text = (
                f"Increases in {countdown}"
                if countdown is not None
                else "No increase scheduled"
            )
            _set_safe_text(label, text)
            label.setToolTip(text)

        def _summary_divider(self) -> QFrame:
            divider = QFrame()
            divider.setObjectName("summaryDivider")
            divider.setFrameShape(QFrame.Shape.VLine)
            return divider

        def set_coordinator(self, coordinator) -> None:
            """Rebind refresh and state signals when the server origin changes."""

            if self.coordinator is not None:
                with suppress(TypeError, RuntimeError):
                    self.coordinator.state_changed.disconnect(self.set_state)
                with suppress(TypeError, RuntimeError):
                    self.refresh_button.clicked.disconnect(
                        self.coordinator.request_refresh
                    )
            self.coordinator = coordinator
            if coordinator is not None:
                coordinator.state_changed.connect(self.set_state)
                self.refresh_button.clicked.connect(coordinator.request_refresh)
                self.set_state(coordinator.state)

        def set_config(self, config: AppConfig) -> None:
            self.config = config
            self.set_state(self._state)

        def set_launch_at_login(self, enabled: bool) -> None:
            """Synchronize the shortcut without starting another transaction."""

            blocked = self.launch_at_login.blockSignals(True)
            self.launch_at_login.setChecked(bool(enabled))
            self.launch_at_login.blockSignals(blocked)

        def set_state(self, state: ApplicationState) -> None:
            expanded_account_ids = {
                account_id
                for account_id, card in self._account_cards.items()
                if card.toggle_button.isChecked()
            }
            self._state = state
            now = datetime.now(UTC)
            summary = summarize_accounts(state.accounts)
            signed_out = state.kind is ApplicationStateKind.LOGIN_REQUIRED
            server_version = sanitize_text(state.server_version, 40)
            self.dashboard_action.setText(
                f"Open Codex LB {server_version}"
                if server_version
                else "Open dashboard"
            )
            _set_safe_text(self.summary_label, format_pool_headline(summary))

            if signed_out:
                _set_safe_text(self.updated_label, "Not signed in")
            elif state.refreshed_at:
                updated = format_absolute_timestamp(
                    state.refreshed_at,
                    self.config.display_time_zone,
                )
                _set_safe_text(self.updated_label, f"Updated {updated}")
            elif state.kind is ApplicationStateKind.LOADING:
                _set_safe_text(self.updated_label, "Connecting to Codex LB…")
            else:
                _set_safe_text(self.updated_label, "Waiting for the first update")

            self.spinner.setVisible(state.kind is ApplicationStateKind.LOADING)
            self.refresh_button.setEnabled(
                state.kind is not ApplicationStateKind.LOADING
            )
            self.refresh_button.setVisible(not signed_out)
            self.summary_panel.setVisible(not signed_out)
            self.accounts_title.setVisible(not signed_out)
            self.account_count_label.setVisible(not signed_out)
            self.scroll.setVisible(not signed_out)

            use_monthly = (
                summary.primary is None
                and summary.secondary is None
                and summary.monthly is not None
            )
            self.primary_caption.setText("Monthly" if use_monthly else "5-hour")
            primary = summary.monthly if use_monthly else summary.primary
            primary_increases_at = (
                summary.monthly_increases_at
                if use_monthly
                else summary.primary_increases_at
            )
            self.primary_summary.setText(
                "—" if primary is None else f"{round_percentage(primary)}%"
            )
            self._set_increase_countdown(
                self.primary_increase,
                primary_increases_at,
                now,
            )
            _set_dynamic_property(
                self.primary_summary,
                "tone",
                quota_tone(primary).value,
            )
            self.weekly_summary_item.setVisible(not use_monthly)
            self.weekly_divider.setVisible(not use_monthly)
            self.weekly_summary.setText(
                "—"
                if summary.secondary is None
                else f"{round_percentage(summary.secondary)}%"
            )
            self._set_increase_countdown(
                self.weekly_increase,
                summary.secondary_increases_at,
                now,
            )
            _set_dynamic_property(
                self.weekly_summary,
                "tone",
                quota_tone(summary.secondary).value,
            )
            self.accounts_summary.setText(
                f"{summary.active_count}/{summary.total_count}"
            )
            self.account_count_label.setText(
                f"{summary.total_count} total"
                if summary.total_count != 1
                else "1 total"
            )

            banner = {
                ApplicationStateKind.LOADING: "Refreshing account status…",
                ApplicationStateKind.READY: "",
                ApplicationStateKind.EMPTY: "Codex LB reported no accounts.",
                ApplicationStateKind.STALE: (
                    "The last update failed. Showing previously fetched data."
                ),
                ApplicationStateKind.LOGIN_REQUIRED: (
                    "Sign in to Codex LB to view account status."
                ),
                ApplicationStateKind.ERROR: "Could not load account status.",
            }[state.kind]
            if state.error_message:
                banner = f"{banner} {state.error_message}".strip()
            _set_safe_text(self.banner, banner)
            self.banner.setVisible(bool(banner))
            banner_tone = {
                ApplicationStateKind.LOADING: "info",
                ApplicationStateKind.READY: "neutral",
                ApplicationStateKind.EMPTY: "neutral",
                ApplicationStateKind.STALE: "warning",
                ApplicationStateKind.LOGIN_REQUIRED: "info",
                ApplicationStateKind.ERROR: "error",
            }[state.kind]
            _set_dynamic_property(self.banner, "tone", banner_tone)

            show_login = signed_out
            session = state.session
            self.sign_out_action.setVisible(
                bool(session is not None and session.authenticated)
            )
            show_admin = show_login and (session is None or session.password_required)
            show_guest = show_login and (
                session is None or session.guest_access_enabled
            )
            self.admin_login_button.setVisible(show_admin)
            self.guest_login_button.setVisible(show_guest)
            self.login_actions.setVisible(show_admin or show_guest)

            while self.account_layout.count():
                item = self.account_layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.hide()
                    widget.deleteLater()
            self._account_cards.clear()
            if state.accounts and not signed_out:
                for account in sort_accounts(state.accounts):
                    card = AccountCard(
                        account,
                        now,
                        self.config.display_time_zone,
                        self.account_container,
                    )
                    self._account_cards[account.account_id] = card
                    self.account_layout.addWidget(card)
                    card.toggle_button.setChecked(
                        account.account_id in expanded_account_ids
                    )
            elif not signed_out:
                empty_text = {
                    ApplicationStateKind.LOADING: "Waiting for the first update…",
                    ApplicationStateKind.LOGIN_REQUIRED: (
                        "Accounts will appear here after you sign in."
                    ),
                    ApplicationStateKind.ERROR: (
                        "Check the server address in Settings, then refresh."
                    ),
                }.get(state.kind, "No accounts are available.")
                empty = _set_role(_plain_label(empty_text), "muted")
                empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
                empty.setMinimumHeight(96)
                self.account_layout.addWidget(empty)
            self.account_layout.addStretch(1)
            if self._shown_once:
                self._resize_to_account_count()

        def open_dashboard(self) -> None:
            try:
                url = normalize_base_url(self.config.base_url)
            except ConfigError:
                return
            QDesktopServices.openUrl(QUrl(url))

        def showEvent(self, event) -> None:
            if not self._shown_once:
                self._shown_once = True
            super().showEvent(event)
            self._resize_to_account_count()

        def resizeEvent(self, event) -> None:
            super().resizeEvent(event)
            if self._shown_once and not self._resizing_to_fit:
                self._auto_size_enabled = False

        def _resize_to_account_count(self) -> None:
            if not self._auto_size_enabled:
                return
            _width, available_height = _available_geometry_size()
            target_height = details_window_height(available_height)
            if self.height() == target_height:
                return
            self._resizing_to_fit = True
            try:
                self.resize(self.width(), target_height)
            finally:
                self._resizing_to_fit = False

        def set_tray_attached(self, attached: bool) -> None:
            """Use a tool window while the tray is the application's home."""

            window_type = Qt.WindowType.Tool if attached else Qt.WindowType.Window
            if self.windowType() == window_type:
                return
            flags = self.windowFlags() & ~Qt.WindowType.WindowType_Mask
            self.setWindowFlags(flags | window_type)

        def closeEvent(self, event) -> None:
            self.dismissed.emit()
            event.accept()
            if not self._tray_available():
                QApplication.quit()

    class SettingsDialog(QDialog):
        """Non-blocking settings editor with transactional save behavior."""

        settings_saved = pyqtSignal(object, bool)

        def __init__(
            self,
            config: AppConfig,
            autostart_manager: AutostartManager | None = None,
            config_path=None,
            parent: QWidget | None = None,
        ):
            super().__init__(parent)
            self.config = config
            self.autostart_manager = autostart_manager or AutostartManager()
            self.config_path = config_path
            self.setObjectName("settingsDialog")
            self.setWindowTitle("Settings")
            configure_modal_dialog(self)
            self.setMinimumWidth(450)
            self._build_ui()
            apply_theme(self)

        def _build_ui(self) -> None:
            layout = QVBoxLayout(self)
            layout.setContentsMargins(22, 20, 22, 20)
            layout.setSpacing(14)

            layout.addWidget(_set_role(_plain_label("Connection"), "section"))
            form = QFormLayout()
            form.setContentsMargins(0, 0, 0, 0)
            form.setHorizontalSpacing(14)
            form.setVerticalSpacing(11)
            form.setFieldGrowthPolicy(
                QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
            )

            self.server_url = QLineEdit(self.config.base_url)
            self.server_url.setObjectName("serverUrl")
            self.server_url.setClearButtonEnabled(True)
            self.server_url.setPlaceholderText("https://codex.example.com")
            self.server_url.setAccessibleName("Codex LB server address")
            self.server_url.setAccessibleDescription(
                "The origin of the Codex LB dashboard; remote servers require HTTPS"
            )
            server_label = _plain_label("&Server address")
            server_label.setBuddy(self.server_url)
            form.addRow(server_label, self.server_url)
            layout.addLayout(form)
            server_help = _set_role(
                _plain_label(
                    "Use the dashboard origin only. Remote servers require HTTPS."
                ),
                "quiet",
            )
            layout.addWidget(server_help)

            layout.addWidget(_set_role(_plain_label("Behavior"), "section"))
            behavior_form = QFormLayout()
            behavior_form.setContentsMargins(0, 0, 0, 0)
            behavior_form.setHorizontalSpacing(14)
            behavior_form.setVerticalSpacing(11)
            behavior_form.setFieldGrowthPolicy(
                QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
            )
            self.time_zone = QComboBox()
            self.time_zone.setObjectName("displayTimeZone")
            self.time_zone.setAccessibleName("Timestamp display")
            self.time_zone.addItem("System local time", "local")
            self.time_zone.addItem("UTC", "utc")
            self.time_zone.setCurrentIndex(
                max(0, self.time_zone.findData(self.config.display_time_zone))
            )
            time_label = _plain_label("Display &time")
            time_label.setBuddy(self.time_zone)
            behavior_form.addRow(time_label, self.time_zone)
            self.launch_at_login = QCheckBox("Launch Codex LB Status at login")
            self.launch_at_login.setObjectName("launchAtLogin")
            self.launch_at_login.setChecked(self.autostart_manager.enabled)
            self.launch_at_login.setAccessibleDescription(
                "Start the status indicator automatically after signing in"
            )
            behavior_form.addRow("Startup", self.launch_at_login)
            layout.addLayout(behavior_form)

            self.error_label = _plain_label()
            self.error_label.setObjectName("settingsError")
            self.error_label.setAccessibleName("Settings error")
            self.error_label.setVisible(False)
            layout.addWidget(self.error_label)
            self.server_url.textChanged.connect(
                lambda _text: self.error_label.setVisible(False)
            )

            layout.addStretch(1)
            buttons = QDialogButtonBox(
                QDialogButtonBox.StandardButton.Save
                | QDialogButtonBox.StandardButton.Cancel
            )
            self.save_button = buttons.button(QDialogButtonBox.StandardButton.Save)
            self.save_button.setText("Save changes")
            self.save_button.setObjectName("primaryButton")
            self.save_button.setDefault(True)
            self.cancel_button = buttons.button(QDialogButtonBox.StandardButton.Cancel)
            self.cancel_button.setText("Cancel")
            self.restore_button = QPushButton("Restore defaults")
            buttons.addButton(
                self.restore_button,
                QDialogButtonBox.ButtonRole.ResetRole,
            )
            buttons.accepted.connect(self.save)
            buttons.rejected.connect(self.reject)
            self.restore_button.clicked.connect(self.confirm_restore_defaults)
            remove_button_icons(buttons)
            layout.addWidget(buttons)
            QWidget.setTabOrder(self.server_url, self.time_zone)
            QWidget.setTabOrder(self.time_zone, self.launch_at_login)
            QWidget.setTabOrder(self.launch_at_login, self.restore_button)
            QWidget.setTabOrder(self.restore_button, self.save_button)

        def _show_error(self, message: str, widget: QWidget | None = None) -> None:
            _set_safe_text(self.error_label, message)
            self.error_label.setVisible(True)
            if widget is not None:
                widget.setFocus()
                if isinstance(widget, QLineEdit):
                    widget.selectAll()

        def save(self) -> None:
            try:
                config = AppConfig(
                    base_url=normalize_base_url(self.server_url.text()),
                    display_time_zone=validate_display_time_zone(
                        self.time_zone.currentData()
                    ),
                )
            except ConfigError as error:
                self._show_error(str(error), self.server_url)
                return
            previous_base_url = self.config.base_url
            try:
                saved = apply_settings_transaction(
                    config,
                    self.launch_at_login.isChecked(),
                    self.autostart_manager,
                    self.config_path,
                )
            except SettingsTransactionError as error:
                self._show_error(str(error))
                return
            self.config = saved
            self.settings_saved.emit(saved, saved.base_url != previous_base_url)
            self.accept()

        def confirm_restore_defaults(self) -> None:
            message = QMessageBox(self)
            message.setIcon(QMessageBox.Icon.Question)
            message.setWindowTitle("Restore defaults")
            configure_modal_dialog(message)
            message.setText("Restore all settings to their defaults?")
            message.setInformativeText(
                "The server will return to this computer, timestamps will use "
                "local time, and launch at login will be turned off. Saved "
                "sessions will be kept."
            )
            message.setStandardButtons(
                QMessageBox.StandardButton.RestoreDefaults
                | QMessageBox.StandardButton.Cancel
            )
            remove_button_icons(message)
            message.finished.connect(
                lambda result: (
                    self._restore_defaults()
                    if result == QMessageBox.StandardButton.RestoreDefaults
                    else None
                )
            )
            open_message_box(message)

        def _restore_defaults(self) -> None:
            defaults = default_config()
            self.server_url.setText(defaults.base_url)
            self.time_zone.setCurrentIndex(self.time_zone.findData("local"))
            self.launch_at_login.setChecked(False)

    class PasswordDialog(QDialog):
        submitted = pyqtSignal(str)

        def __init__(
            self,
            title: str,
            prompt: str,
            parent: QWidget | None = None,
            action_label: str = "Log in",
        ):
            super().__init__(parent)
            self.setWindowTitle(title)
            configure_modal_dialog(self)
            self.setMinimumWidth(420)
            layout = QVBoxLayout(self)
            layout.setContentsMargins(24, 22, 24, 20)
            layout.setSpacing(16)
            layout.addWidget(_set_role(_plain_label(prompt), "section"))

            self.password = QLineEdit()
            self.password.setObjectName("password")
            self.password.setEchoMode(QLineEdit.EchoMode.Password)
            self.password.setPlaceholderText("Enter password")
            self.password.setAccessibleName("Password")
            self.password.setClearButtonEnabled(True)
            self.password.returnPressed.connect(self.submit)
            self.password_label = _plain_label("&Password")
            self.password_label.setBuddy(self.password)

            form = QFormLayout()
            form.setContentsMargins(0, 0, 0, 0)
            form.setHorizontalSpacing(16)
            form.setVerticalSpacing(10)
            form.setFieldGrowthPolicy(
                QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
            )
            form.addRow(self.password_label, self.password)
            layout.addLayout(form)

            self.show_password = QCheckBox("Show password")
            self.show_password.toggled.connect(self._set_password_visible)
            options = QHBoxLayout()
            options.setSpacing(12)
            options.addWidget(self.show_password)
            options.addStretch(1)
            self.privacy_label = _set_role(
                _plain_label("Used for this sign-in only and never saved."), "quiet"
            )
            self.privacy_label.setWordWrap(False)
            options.addWidget(self.privacy_label)
            layout.addLayout(options)
            self.error_label = _plain_label()
            self.error_label.setObjectName("loginError")
            self.error_label.setAccessibleName("Login error")
            self.error_label.setVisible(False)
            layout.addWidget(self.error_label)
            self.password.textChanged.connect(
                lambda _text: self.error_label.setVisible(False)
            )

            buttons = QDialogButtonBox(
                QDialogButtonBox.StandardButton.Ok
                | QDialogButtonBox.StandardButton.Cancel
            )
            self.submit_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
            self.submit_button.setText(action_label)
            self.submit_button.setObjectName("primaryButton")
            self.submit_button.setDefault(True)
            self.cancel_button = buttons.button(QDialogButtonBox.StandardButton.Cancel)
            self.cancel_button.setText("Cancel")
            buttons.accepted.connect(self.submit)
            buttons.rejected.connect(self.cancel)
            remove_button_icons(buttons)
            layout.addWidget(buttons)
            QWidget.setTabOrder(self.password, self.show_password)
            QWidget.setTabOrder(self.show_password, self.submit_button)
            apply_theme(self)

        def _set_password_visible(self, visible: bool) -> None:
            mode = QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password
            self.password.setEchoMode(mode)

        def _show_error(self, message: str) -> None:
            _set_safe_text(self.error_label, message)
            self.error_label.setVisible(True)
            self.password.setFocus()

        def cancel(self) -> None:
            self.password.clear()
            self.reject()

        def submit(self) -> None:
            value = self.password.text()
            if not value:
                self._show_error("Enter the administrator password.")
                return
            self.submitted.emit(value)
            self.password.clear()
            self.accept()

    class GuestPasswordDialog(PasswordDialog):
        submitted_optional = pyqtSignal(object)

        def __init__(self, parent: QWidget | None = None):
            super().__init__(
                "Continue as guest",
                "Sign in with guest access",
                parent,
                action_label="Continue",
            )
            self.password.setAccessibleName("Guest password")
            self.password.setPlaceholderText("Guest password (optional)")
            self.password_label.setText("&Guest password")
            self.show_password.setText("Show guest password")

        def submit(self) -> None:
            value = self.password.text() or None
            self.submitted_optional.emit(value)
            self.password.clear()
            self.accept()

    class TotpDialog(PasswordDialog):
        def __init__(self, parent: QWidget | None = None):
            super().__init__(
                "Two-factor verification",
                "Enter your six-digit verification code",
                parent,
                action_label="Verify",
            )
            self.password.setAccessibleName("Six-digit verification code")
            self.password.setPlaceholderText("000000")
            self.password_label.setText("&Verification code")
            self.password.setMaxLength(6)
            self.password.setInputMethodHints(Qt.InputMethodHint.ImhDigitsOnly)
            self.show_password.setText("Show code")

        def submit(self) -> None:
            value = self.password.text()
            if len(value) != 6 or not value.isdigit():
                self._show_error("Enter the six-digit code from your authenticator.")
                return
            self.submitted.emit(value)
            self.password.clear()
            self.accept()


__all__ = [
    "AccountCard",
    "DetailsWindow",
    "GuestPasswordDialog",
    "PasswordDialog",
    "QuotaProgress",
    "SettingsDialog",
    "TotpDialog",
    "configure_modal_dialog",
    "details_window_height",
    "ensure_message_box_width",
    "open_message_box",
    "position_window_centered_on_anchor",
    "position_window_near_anchor",
    "remove_button_icons",
]
