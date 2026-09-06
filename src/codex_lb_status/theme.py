"""Shared visual theme for the native Codex LB companion."""

from __future__ import annotations

try:
    from PyQt6.QtGui import QFont, QFontDatabase, QIcon
    from PyQt6.QtWidgets import QApplication, QWidget
except ImportError:  # pragma: no cover - only used by the desktop runtime.
    QApplication = None


COLORS = {
    "canvas": "#f6f7f9",
    "surface": "#ffffff",
    "surface_subtle": "#f1f3f5",
    "border": "#d9dee5",
    "border_strong": "#c5cbd3",
    "text": "#15181d",
    "muted": "#626b77",
    "quiet": "#89919c",
    "accent": "#355f9d",
    "accent_hover": "#294c80",
    "focus": "#4f75c2",
    "green": "#16865f",
    "green_soft": "#e9f7f1",
    "amber": "#b66b12",
    "amber_soft": "#fff5e5",
    "red": "#c6413a",
    "red_soft": "#fff0ef",
    "gray": "#78808b",
    "gray_soft": "#eef0f3",
}


APP_STYLE_SHEET = f"""
QMainWindow, QDialog {{
    background: {COLORS["canvas"]};
    color: {COLORS["text"]};
}}
QWidget {{
    color: {COLORS["text"]};
    font-family: "Ubuntu Sans";
    font-size: 10pt;
}}
QLabel[role="title"] {{
    font-size: 17pt;
    font-weight: 700;
}}
QLabel[role="section"] {{
    font-size: 11pt;
    font-weight: 700;
}}
QLabel[role="muted"] {{ color: {COLORS["muted"]}; }}
QLabel[role="quiet"] {{ color: {COLORS["quiet"]}; font-size: 9pt; }}
QLabel[role="value"] {{ font-size: 20pt; font-weight: 700; }}
QLabel[role="summaryMeta"] {{ color: {COLORS["quiet"]}; font-size: 8pt; }}
QLabel[role="value"][tone="green"] {{ color: {COLORS["green"]}; }}
QLabel[role="value"][tone="amber"] {{ color: {COLORS["amber"]}; }}
QLabel[role="value"][tone="red"] {{ color: {COLORS["red"]}; }}
QLabel[role="value"][tone="gray"] {{ color: {COLORS["muted"]}; }}
QLabel[role="quotaValue"] {{ font-weight: 700; }}
QFrame#summaryPanel, QFrame#accountCard {{
    background: {COLORS["surface"]};
    border: 1px solid {COLORS["border"]};
    border-radius: 9px;
}}
QToolButton#accountHeader {{
    min-height: 88px;
    padding: 0;
    background: transparent;
    border: 0;
    border-radius: 8px;
}}
QToolButton#accountHeader:hover {{
    background: {COLORS["surface_subtle"]};
}}
QToolButton#accountHeader:checked {{
    background: #fafbfc;
    border-bottom-left-radius: 0;
    border-bottom-right-radius: 0;
}}
QToolButton#accountHeader:focus {{
    border: 2px solid {COLORS["focus"]};
}}
QLabel#disclosure {{
    color: {COLORS["muted"]};
    font-size: 14pt;
}}
QLabel#accountName {{ font-weight: 700; }}
QLabel[role="accountMeta"] {{
    color: {COLORS["muted"]};
    font-size: 9pt;
}}
QLabel[role="quotaCaption"],
QLabel#quotaColumnReset,
QLabel[role="quotaReset"] {{
    color: {COLORS["quiet"]};
    font-size: 8pt;
    font-weight: 400;
}}
QLabel#quotaColumnValue {{
    font-size: 10pt;
    font-weight: 700;
}}
QLabel#quotaColumnValue[tone="green"] {{ color: {COLORS["green"]}; }}
QLabel#quotaColumnValue[tone="amber"] {{ color: {COLORS["amber"]}; }}
QLabel#quotaColumnValue[tone="red"] {{ color: {COLORS["red"]}; }}
QLabel#quotaColumnValue[tone="gray"] {{ color: {COLORS["muted"]}; }}
QFrame#quotaDivider {{
    background: {COLORS["border"]};
    border: 0;
    max-width: 1px;
}}
QLabel#accountStatus {{
    font-size: 9pt;
    font-weight: 600;
}}
QLabel#accountStatus[tone="green"] {{ color: {COLORS["green"]}; }}
QLabel#accountStatus[tone="amber"] {{ color: {COLORS["amber"]}; }}
QLabel#accountStatus[tone="red"] {{ color: {COLORS["red"]}; }}
QLabel#accountStatus[tone="gray"] {{ color: {COLORS["muted"]}; }}
QWidget#accountDetails {{
    background: transparent;
    border-top: 1px solid {COLORS["border"]};
}}
QFrame#summaryDivider {{
    background: {COLORS["border"]};
    border: 0;
    max-width: 1px;
}}
QFrame#footerBar {{
    background: transparent;
    border-top: 1px solid {COLORS["border"]};
}}
QLabel#statusBadge {{
    padding: 3px 7px;
    border-radius: 5px;
    font-size: 9pt;
    font-weight: 600;
}}
QLabel#statusBadge[tone="green"] {{
    color: {COLORS["green"]};
    background: {COLORS["green_soft"]};
    border: 1px solid #bde8d7;
}}
QLabel#statusBadge[tone="amber"] {{
    color: {COLORS["amber"]};
    background: {COLORS["amber_soft"]};
    border: 1px solid #eed3aa;
}}
QLabel#statusBadge[tone="red"] {{
    color: {COLORS["red"]};
    background: {COLORS["red_soft"]};
    border: 1px solid #efc6c2;
}}
QLabel#statusBadge[tone="gray"] {{
    color: {COLORS["muted"]};
    background: {COLORS["gray_soft"]};
    border: 1px solid {COLORS["border"]};
}}
QLabel#statusBanner {{
    padding: 9px 11px;
    border-radius: 7px;
}}
QLabel#statusBanner[tone="info"] {{
    color: {COLORS["accent"]};
    background: #eef3fa;
    border: 1px solid #cedaed;
}}
QLabel#statusBanner[tone="warning"] {{
    color: {COLORS["amber"]};
    background: {COLORS["amber_soft"]};
    border: 1px solid #eed3aa;
}}
QLabel#statusBanner[tone="error"] {{
    color: {COLORS["red"]};
    background: {COLORS["red_soft"]};
    border: 1px solid #efc6c2;
}}
QLabel#statusBanner[tone="neutral"] {{
    color: {COLORS["muted"]};
    background: {COLORS["gray_soft"]};
    border: 1px solid {COLORS["border"]};
}}
QLabel#settingsError, QLabel#loginError {{
    color: {COLORS["red"]};
    background: {COLORS["red_soft"]};
    border: 1px solid #efc6c2;
    border-radius: 7px;
    padding: 8px 10px;
}}
QPushButton {{
    min-height: 32px;
    padding: 0 12px;
    background: {COLORS["surface"]};
    border: 1px solid {COLORS["border_strong"]};
    border-radius: 7px;
}}
QPushButton:hover {{
    background: {COLORS["surface_subtle"]};
    border-color: #aeb6c0;
}}
QPushButton:pressed {{ background: #e7eaee; }}
QPushButton:focus {{ border: 2px solid {COLORS["focus"]}; }}
QPushButton:disabled {{
    color: {COLORS["quiet"]};
    background: {COLORS["surface_subtle"]};
    border-color: {COLORS["border"]};
}}
QPushButton#primaryButton {{
    color: #ffffff;
    background: {COLORS["accent"]};
    border-color: {COLORS["accent"]};
    font-weight: 600;
}}
QPushButton#primaryButton:hover {{
    background: {COLORS["accent_hover"]};
    border-color: {COLORS["accent_hover"]};
}}
QPushButton#dangerButton {{ color: {COLORS["red"]}; }}
QToolButton#actionsButton {{
    min-height: 32px;
    padding: 0 27px 0 12px;
    background: {COLORS["surface"]};
    border: 1px solid {COLORS["border_strong"]};
    border-radius: 7px;
}}
QToolButton#actionsButton:hover {{
    background: {COLORS["surface_subtle"]};
    border-color: #aeb6c0;
}}
QToolButton#actionsButton:pressed {{ background: #e7eaee; }}
QToolButton#actionsButton:focus {{ border: 2px solid {COLORS["focus"]}; }}
QToolButton#actionsButton::menu-indicator {{
    subcontrol-position: right center;
    subcontrol-origin: border;
    right: 8px;
}}
QLineEdit, QComboBox {{
    min-height: 34px;
    padding: 0 9px;
    background: {COLORS["surface"]};
    border: 1px solid {COLORS["border_strong"]};
    border-radius: 7px;
    selection-background-color: {COLORS["accent"]};
}}
QLineEdit:hover, QComboBox:hover {{ border-color: #aeb6c0; }}
QLineEdit:focus, QComboBox:focus {{
    border: 2px solid {COLORS["focus"]};
    padding: 0 8px;
}}
QComboBox::drop-down {{ border: 0; width: 26px; }}
QComboBox QAbstractItemView {{
    background: {COLORS["surface"]};
    border: 1px solid {COLORS["border"]};
    selection-background-color: {COLORS["surface_subtle"]};
    selection-color: {COLORS["text"]};
    outline: 0;
}}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 17px; height: 17px; }}
QProgressBar#quotaProgress {{
    background: #e8ebef;
    border: 0;
    border-radius: 3px;
}}
QProgressBar#quotaProgress::chunk {{ border-radius: 3px; }}
QProgressBar#quotaProgress[tone="green"]::chunk {{ background: {COLORS["green"]}; }}
QProgressBar#quotaProgress[tone="amber"]::chunk {{ background: #d28a2d; }}
QProgressBar#quotaProgress[tone="red"]::chunk {{ background: {COLORS["red"]}; }}
QProgressBar#quotaProgress[tone="gray"]::chunk {{ background: {COLORS["gray"]}; }}
QProgressBar#loadingBar {{
    background: #e4e8ed;
    border: 0;
    border-radius: 2px;
}}
QProgressBar#loadingBar::chunk {{ background: {COLORS["accent"]}; }}
QScrollArea {{ background: transparent; border: 0; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: #c7ccd3;
    min-height: 28px;
    border-radius: 4px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QMenu {{
    background: {COLORS["surface"]};
    border: 1px solid {COLORS["border"]};
    padding: 6px;
}}
QMenu::item {{
    min-height: 26px;
    padding: 4px 24px 4px 8px;
    border-radius: 6px;
}}
QMenu::item:selected {{ background: {COLORS["surface_subtle"]}; }}
QMenu::item:disabled {{ color: {COLORS["muted"]}; }}
QMenu::separator {{
    height: 1px;
    background: {COLORS["border"]};
    margin: 6px 4px;
}}
QToolTip {{
    color: {COLORS["text"]};
    background: {COLORS["surface"]};
    border: 1px solid {COLORS["border_strong"]};
    padding: 5px 7px;
}}
"""


def configure_application(app: QApplication) -> None:
    """Apply one predictable native style before application widgets are built."""

    app.setApplicationName("Codex LB Status")
    app.setApplicationDisplayName("Codex LB Status")
    app.setDesktopFileName("io.github.victorstatko.codex_lb_status")
    app.setStyle("Fusion")
    if "Ubuntu Sans" in QFontDatabase.families():
        app.setFont(QFont("Ubuntu Sans", 10))
    app.setWindowIcon(QIcon.fromTheme("io.github.victorstatko.codex_lb_status"))
    app.setStyleSheet(APP_STYLE_SHEET)


def apply_theme(widget: QWidget) -> None:
    """Style independently-created widgets, including isolated UI tests."""

    app = QApplication.instance() if QApplication is not None else None
    if app is None or not app.styleSheet():
        widget.setStyleSheet(APP_STYLE_SHEET)


__all__ = ["APP_STYLE_SHEET", "COLORS", "apply_theme", "configure_application"]
