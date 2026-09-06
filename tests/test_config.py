"""Configuration validation and atomic persistence tests."""

from __future__ import annotations

import json
import os

import pytest

from codex_lb_status.config import (
    DEFAULT_BASE_URL,
    AppConfig,
    ConfigError,
    SettingsTransactionError,
    load_config,
    normalize_base_url,
    restore_defaults,
    save_config,
)


def test_missing_configuration_uses_loopback_defaults(tmp_path) -> None:
    assert load_config(tmp_path / "missing.json") == AppConfig()


def test_xdg_paths_are_resolved_from_environment(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    from codex_lb_status.config import config_path, sessions_directory

    assert config_path() == tmp_path / "config" / "codex-lb-status" / "config.json"
    assert sessions_directory() == tmp_path / "state" / "codex-lb-status" / "sessions"


def test_display_timezone_migrates_when_missing(tmp_path) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"schemaVersion": 1, "baseUrl": DEFAULT_BASE_URL}))
    assert load_config(path).display_time_zone == "local"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("http://localhost:2455/", "http://localhost:2455"),
        ("http://127.0.0.1:2455", DEFAULT_BASE_URL),
        ("http://[::1]:2455/", "http://[::1]:2455"),
        ("https://example.com/", "https://example.com"),
    ],
)
def test_allowed_origins_are_normalized(raw: str, expected: str) -> None:
    assert normalize_base_url(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "http://example.com",
        "ftp://example.com",
        "https://user:password@example.com",
        "https://example.com/path",
        "https://example.com/?query=1",
        "https://example.com/#fragment",
        "",
    ],
)
def test_unsafe_origins_are_rejected(raw: str) -> None:
    with pytest.raises(ConfigError):
        normalize_base_url(raw)


def test_malformed_ports_and_non_object_json_are_rejected(tmp_path) -> None:
    with pytest.raises(ConfigError):
        normalize_base_url("https://example.com:notaport")
    path = tmp_path / "config.json"
    path.write_text("[]")
    with pytest.raises(ConfigError, match="JSON object"):
        load_config(path)
    path.write_text(json.dumps({"schemaVersion": 1, "baseUrl": 123}))
    with pytest.raises(ConfigError, match="baseUrl"):
        load_config(path)
    path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "baseUrl": "https://example.com",
                "displayTimeZone": 1,
            }
        )
    )
    with pytest.raises(ConfigError, match="displayTimeZone"):
        load_config(path)


def test_only_local_or_utc_display_time_zones_are_accepted(tmp_path) -> None:
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "baseUrl": DEFAULT_BASE_URL,
                "displayTimeZone": "mars",
            }
        )
    )
    with pytest.raises(ConfigError, match="displayTimeZone"):
        load_config(path)


def test_unknown_keys_and_schema_versions_are_rejected(tmp_path) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"schemaVersion": 2, "baseUrl": DEFAULT_BASE_URL}))
    with pytest.raises(ConfigError, match="schema version"):
        load_config(path)
    path.write_text(json.dumps({"schemaVersion": 1, "unexpected": True}))
    with pytest.raises(ConfigError, match="unsupported keys"):
        load_config(path)


def test_config_is_saved_atomically_with_restricted_permissions(tmp_path) -> None:
    path = tmp_path / "nested" / "config.json"
    saved = save_config(AppConfig("https://example.com", "utc"), path)
    assert saved == AppConfig("https://example.com", "utc")
    assert load_config(path) == saved
    assert os.stat(path.parent).st_mode & 0o777 == 0o700
    assert os.stat(path).st_mode & 0o777 == 0o600
    assert not list(path.parent.glob(".*config.json.*"))


def test_restore_defaults_uses_the_normal_save_path(tmp_path) -> None:
    path = tmp_path / "config.json"
    save_config(AppConfig("https://example.com", "utc"), path)
    assert restore_defaults(path) == AppConfig()
    assert load_config(path) == AppConfig()


def test_corrupt_configuration_is_recoverable(tmp_path) -> None:
    path = tmp_path / "config.json"
    path.write_text("not json")
    with pytest.raises(ConfigError, match="cannot read configuration"):
        load_config(path)
    assert restore_defaults(path) == AppConfig()


def test_settings_transaction_restores_existing_files_on_failure(tmp_path) -> None:
    from codex_lb_status.autostart import AutostartManager
    from codex_lb_status.config import apply_settings_transaction

    config_path = tmp_path / "config.json"
    save_config(AppConfig("https://example.com", "utc"), config_path)
    manager = AutostartManager(tmp_path / "config-home")
    manager.set_enabled(True)
    old_config = config_path.read_text()
    old_autostart = manager.path.read_text()

    def fail(_enabled: bool) -> None:
        raise OSError("fail")

    manager.set_enabled = fail
    with pytest.raises(SettingsTransactionError):
        apply_settings_transaction(AppConfig(), False, manager, config_path)
    assert config_path.read_text() == old_config
    assert manager.path.read_text() == old_autostart
