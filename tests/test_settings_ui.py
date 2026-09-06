"""Settings validation and transactional Qt UI tests."""

from __future__ import annotations

import pytest

pytest.importorskip("PyQt6")

from codex_lb_status.autostart import AutostartManager
from codex_lb_status.config import AppConfig, load_config
from codex_lb_status.ui import SettingsDialog


def test_settings_can_save_url_timezone_and_autostart(qtbot, tmp_path) -> None:
    config_path = tmp_path / "config.json"
    manager = AutostartManager(tmp_path / "config-home")
    dialog = SettingsDialog(
        AppConfig(),
        manager,
        config_path=config_path,
    )
    qtbot.addWidget(dialog)
    saved = []
    dialog.settings_saved.connect(
        lambda config, changed: saved.append((config, changed))
    )
    dialog.server_url.setText("https://example.com/")
    dialog.time_zone.setCurrentIndex(1)
    dialog.launch_at_login.setChecked(True)
    dialog.save()
    assert saved[0][0] == AppConfig("https://example.com", "utc")
    assert saved[0][1]
    assert load_config(config_path) == AppConfig("https://example.com", "utc")
    assert manager.enabled


def test_invalid_setting_is_reported_without_partial_apply(qtbot, tmp_path) -> None:
    config_path = tmp_path / "config.json"
    manager = AutostartManager(tmp_path / "config-home")
    dialog = SettingsDialog(AppConfig(), manager, config_path=config_path)
    qtbot.addWidget(dialog)
    dialog.server_url.setText("http://remote.example.com")
    dialog.save()
    assert not dialog.error_label.isHidden()
    assert "HTTPS" in dialog.error_label.text()
    assert not config_path.exists()
    assert not manager.enabled


def test_transaction_failure_rolls_back_config_and_autostart(qtbot, tmp_path) -> None:
    config_path = tmp_path / "config.json"
    manager = AutostartManager(tmp_path / "config-home")
    dialog = SettingsDialog(AppConfig(), manager, config_path=config_path)
    qtbot.addWidget(dialog)

    def fail(_enabled: bool) -> None:
        raise OSError("simulated autostart failure")

    manager.set_enabled = fail
    dialog.server_url.setText("https://example.com")
    dialog.save()
    assert not dialog.error_label.isHidden()
    assert not config_path.exists()


def test_settings_controls_have_clear_labels_and_primary_action(qtbot) -> None:
    dialog = SettingsDialog(AppConfig())
    qtbot.addWidget(dialog)
    assert dialog.server_url.accessibleName() == "Codex LB server address"
    assert dialog.time_zone.accessibleName() == "Timestamp display"
    assert dialog.save_button.text() == "Save changes"
    assert dialog.save_button.isDefault()
    assert dialog.save_button.icon().isNull()
    assert dialog.cancel_button.icon().isNull()
    assert dialog.restore_button.icon().isNull()
