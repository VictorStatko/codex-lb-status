"""User autostart entry tests."""

from __future__ import annotations

from codex_lb_status.autostart import AutostartManager, desktop_entry


def test_autostart_creation_is_idempotent_and_exact(tmp_path) -> None:
    manager = AutostartManager(tmp_path / "config")
    manager.set_enabled(True)
    first = manager.path.read_text()
    manager.set_enabled(True)
    assert manager.path.read_text() == first == desktop_entry()
    assert "Exec=/usr/bin/codex-lb-status --background" in first
    assert "X-GNOME-Autostart-enabled=true" in first
    manager.set_enabled(False)
    manager.set_enabled(False)
    assert not manager.path.exists()


def test_disabling_autostart_does_not_delete_other_user_configuration(tmp_path) -> None:
    config_home = tmp_path / "config"
    config_home.mkdir()
    settings = config_home / "codex-lb-status" / "config.json"
    settings.parent.mkdir()
    settings.write_text("preserve")
    manager = AutostartManager(config_home)
    manager.set_enabled(True)
    manager.set_enabled(False)
    assert settings.read_text() == "preserve"
