"""Validated user configuration and atomic persistence helpers."""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import SplitResult, urlsplit, urlunsplit

DEFAULT_BASE_URL = "http://127.0.0.1:2455"
CONFIG_SCHEMA_VERSION = 1
DISPLAY_TIME_ZONES = frozenset(("local", "utc"))
LOOPBACK_HOSTS = frozenset(("127.0.0.1", "localhost", "::1"))


class ConfigError(ValueError):
    """Raised for invalid or unreadable application configuration."""


class SettingsTransactionError(ConfigError):
    """Raised when configuration and autostart cannot commit together."""


class AutostartSettings(Protocol):
    """Minimal autostart interface required by a settings transaction."""

    def set_enabled(self, enabled: bool) -> None: ...

    def snapshot(self) -> bytes | None: ...

    def restore(self, snapshot: bytes | None) -> None: ...


@dataclass(frozen=True, slots=True)
class AppConfig:
    base_url: str = DEFAULT_BASE_URL
    display_time_zone: str = "local"
    schema_version: int = CONFIG_SCHEMA_VERSION

    def validated(self) -> AppConfig:
        return AppConfig(
            base_url=normalize_base_url(self.base_url),
            display_time_zone=validate_display_time_zone(self.display_time_zone),
        )


def _config_home() -> Path:
    configured = os.environ.get("XDG_CONFIG_HOME")
    return Path(configured).expanduser() if configured else Path.home() / ".config"


def _state_home() -> Path:
    configured = os.environ.get("XDG_STATE_HOME")
    return (
        Path(configured).expanduser()
        if configured
        else Path.home() / ".local" / "state"
    )


def config_path() -> Path:
    return _config_home() / "codex-lb-status" / "config.json"


def sessions_directory() -> Path:
    return _state_home() / "codex-lb-status" / "sessions"


def validate_display_time_zone(value: str) -> str:
    if value not in DISPLAY_TIME_ZONES:
        raise ConfigError("displayTimeZone must be either local or utc")
    return value


def _normalized_split(raw: str) -> SplitResult:
    if not isinstance(raw, str) or not raw.strip():
        raise ConfigError("baseUrl must be an absolute HTTP or HTTPS URL")
    try:
        parsed = urlsplit(raw.strip())
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as error:
        raise ConfigError("baseUrl must be a valid HTTP or HTTPS URL") from error
    malformed_unbracketed_port = (
        port is None and ":" in parsed.netloc and not parsed.netloc.endswith("]")
    )
    if (
        parsed.scheme not in ("http", "https")
        or not hostname
        or malformed_unbracketed_port
    ):
        raise ConfigError("baseUrl must be an absolute HTTP or HTTPS URL")
    if parsed.username or parsed.password:
        raise ConfigError("baseUrl must not contain credentials")
    if parsed.path not in ("", "/"):
        raise ConfigError("baseUrl must be an origin without a path")
    if parsed.query or parsed.fragment:
        raise ConfigError("baseUrl must not contain a query or fragment")
    return parsed


def normalize_base_url(raw: str) -> str:
    """Validate and normalize a server URL to an origin."""

    parsed = _normalized_split(raw)
    hostname = parsed.hostname or ""
    if parsed.scheme == "http" and hostname.lower().rstrip(".") not in LOOPBACK_HOSTS:
        raise ConfigError(
            "remote codex-lb connections require HTTPS; plain HTTP is allowed "
            "only on loopback"
        )
    host = hostname.lower()
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = host
    if parsed.port is not None:
        netloc = f"{netloc}:{parsed.port}"
    return urlunsplit((parsed.scheme.lower(), netloc, "", "", ""))


def _atomic_write(path: Path, content: str, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=path.parent,
        text=True,
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
        os.chmod(path, mode)
    except Exception:
        with suppress(OSError):
            temporary_path.unlink(missing_ok=True)
        raise


def load_config(path: Path | str | None = None) -> AppConfig:
    """Load validated settings, using defaults when the file is absent."""

    target = Path(path) if path is not None else config_path()
    if not target.exists():
        return AppConfig()
    try:
        with target.open(encoding="utf-8") as stream:
            raw = json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ConfigError(f"cannot read configuration: {error}") from error
    if not isinstance(raw, dict):
        raise ConfigError("configuration must contain a JSON object")
    unknown = set(raw) - {"schemaVersion", "baseUrl", "displayTimeZone"}
    if unknown:
        raise ConfigError(
            f"configuration contains unsupported keys: {', '.join(sorted(unknown))}"
        )
    schema_version = raw.get("schemaVersion", CONFIG_SCHEMA_VERSION)
    if schema_version != CONFIG_SCHEMA_VERSION:
        raise ConfigError(
            f"unsupported configuration schema version: {schema_version!r}"
        )
    base_url = raw.get("baseUrl", DEFAULT_BASE_URL)
    display_time_zone = raw.get("displayTimeZone", "local")
    if not isinstance(base_url, str):
        raise ConfigError("baseUrl must be a string")
    if not isinstance(display_time_zone, str):
        raise ConfigError("displayTimeZone must be either local or utc")
    return AppConfig(
        base_url=normalize_base_url(base_url),
        display_time_zone=validate_display_time_zone(display_time_zone),
    )


def save_config(config: AppConfig, path: Path | str | None = None) -> AppConfig:
    """Validate and atomically save settings with restricted permissions."""

    validated = config.validated()
    target = Path(path) if path is not None else config_path()
    body = {
        "schemaVersion": CONFIG_SCHEMA_VERSION,
        "baseUrl": validated.base_url,
        "displayTimeZone": validated.display_time_zone,
    }
    _atomic_write(target, json.dumps(body, indent=2, sort_keys=True) + "\n", 0o600)
    return validated


def default_config() -> AppConfig:
    return AppConfig()


def restore_defaults(path: Path | str | None = None) -> AppConfig:
    """Restore preferences through the same validated atomic save path."""

    return save_config(default_config(), path)


def apply_settings_transaction(
    config: AppConfig,
    launch_at_login: bool,
    autostart_manager: AutostartSettings,
    path: Path | str | None = None,
) -> AppConfig:
    """Commit config and autostart together, restoring both on failure."""

    validated = config.validated()
    target = Path(path) if path is not None else config_path()
    old_config_bytes = target.read_bytes() if target.exists() else None
    old_autostart = autostart_manager.snapshot()
    try:
        save_config(validated, target)
        autostart_manager.set_enabled(launch_at_login)
    except Exception as error:
        try:
            if old_config_bytes is None:
                target.unlink(missing_ok=True)
            else:
                _atomic_write(target, old_config_bytes.decode("utf-8"), 0o600)
            autostart_manager.restore(old_autostart)
        except Exception as rollback_error:
            raise SettingsTransactionError(
                "settings could not be saved and rollback also failed"
            ) from rollback_error
        raise SettingsTransactionError(
            "settings could not be saved; no changes were applied"
        ) from error
    return validated


__all__ = [
    "CONFIG_SCHEMA_VERSION",
    "DEFAULT_BASE_URL",
    "DISPLAY_TIME_ZONES",
    "AppConfig",
    "ConfigError",
    "SettingsTransactionError",
    "apply_settings_transaction",
    "config_path",
    "default_config",
    "load_config",
    "normalize_base_url",
    "restore_defaults",
    "save_config",
    "sessions_directory",
    "validate_display_time_zone",
]
