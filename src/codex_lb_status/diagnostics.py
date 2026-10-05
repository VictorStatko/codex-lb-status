"""Small, privacy-safe diagnostic log for intermittent desktop failures."""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import time
from pathlib import Path
from typing import Any

LOG_FILE_NAME = "codex-lb-status.log"
MAX_LOG_BYTES = 1_048_576
LOG_BACKUP_COUNT = 2
_LOGGER_NAME = "codex_lb_status"
_SENSITIVE_FIELD_MARKERS = ("password", "token", "secret", "cookie")
_SENSITIVE_FIELD_NAMES = frozenset(
    {"code", "otp", "otp_code", "totp_code", "verification_code"}
)


class _PrivateRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """Rotating handler that keeps both new and rolled files user-only."""

    def _open(self):
        stream = super()._open()
        os.chmod(self.baseFilename, 0o600)
        return stream


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        fields = getattr(record, "diagnostic_fields", {})
        payload = {
            "timestamp": time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)
            ),
            "level": record.levelname,
            "event": getattr(record, "diagnostic_event", record.getMessage()),
        }
        if fields:
            payload.update(fields)
        if record.exc_info:
            payload["exception_type"] = record.exc_info[0].__name__
        return json.dumps(payload, ensure_ascii=True, sort_keys=True)


def _safe_value(key: str, value: Any) -> Any:
    normalized_key = key.casefold()
    if normalized_key in _SENSITIVE_FIELD_NAMES or any(
        marker in normalized_key for marker in _SENSITIVE_FIELD_MARKERS
    ):
        return "[redacted]"
    if isinstance(value, dict):
        return {
            str(item_key): _safe_value(str(item_key), item)
            for item_key, item in value.items()
        }
    if isinstance(value, list):
        return [_safe_value(key, item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _safe_fields(fields: dict[str, Any]) -> dict[str, Any]:
    return {key: _safe_value(key, value) for key, value in fields.items()}


def log_event(level: int, event: str, **fields: Any) -> None:
    """Write one structured event; credentials and cookie values are never kept."""

    logging.getLogger(_LOGGER_NAME).log(
        level,
        event,
        extra={
            "diagnostic_event": event,
            "diagnostic_fields": _safe_fields(fields),
        },
    )


def default_log_path() -> Path:
    state_home = os.environ.get("XDG_STATE_HOME")
    root = (
        Path(state_home).expanduser()
        if state_home
        else Path.home() / ".local" / "state"
    )
    return root / "codex-lb-status" / LOG_FILE_NAME


def configure_logging(path: Path | str | None = None) -> Path | None:
    """Enable the bounded diagnostic log without making startup depend on it."""

    target = Path(path) if path is not None else default_log_path()
    logger = logging.getLogger(_LOGGER_NAME)
    existing = next(
        (
            handler
            for handler in logger.handlers
            if isinstance(handler, _PrivateRotatingFileHandler)
        ),
        None,
    )
    if existing is not None and Path(existing.baseFilename) == target:
        return target
    if existing is not None:
        logger.removeHandler(existing)
        existing.close()
    try:
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(target.parent, 0o700)
        handler = _PrivateRotatingFileHandler(
            target,
            maxBytes=MAX_LOG_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
    except OSError:
        return None
    handler.setFormatter(_JsonFormatter())
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.addHandler(handler)
    log_event(logging.INFO, "diagnostics_enabled")
    return target


__all__ = [
    "LOG_BACKUP_COUNT",
    "LOG_FILE_NAME",
    "MAX_LOG_BYTES",
    "configure_logging",
    "default_log_path",
    "log_event",
]
