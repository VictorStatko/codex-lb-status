"""Privacy and boundedness checks for local diagnostics."""

from __future__ import annotations

import json
import logging
import os

from codex_lb_status.diagnostics import configure_logging, log_event


def test_diagnostic_events_are_json_and_redact_sensitive_fields(tmp_path) -> None:
    path = tmp_path / "logs" / "app.log"

    try:
        assert configure_logging(path) == path
        log_event(
            logging.WARNING,
            "session_rejected",
            operation_id="op-1",
            password="plain-text-password",
            status_code=401,
            verification_code="123456",
            nested={"access_token": "plain-text-token"},
        )

        content = path.read_text()
        records = [json.loads(line) for line in content.splitlines()]
        assert records[0]["event"] == "diagnostics_enabled"
        assert records[1]["event"] == "session_rejected"
        assert records[1]["operation_id"] == "op-1"
        assert records[1]["password"] == "[redacted]"
        assert records[1]["status_code"] == 401
        assert records[1]["verification_code"] == "[redacted]"
        assert records[1]["nested"]["access_token"] == "[redacted]"
        assert "plain-text-password" not in content
        assert "plain-text-token" not in content
        assert os.stat(path.parent).st_mode & 0o777 == 0o700
        assert os.stat(path).st_mode & 0o777 == 0o600
    finally:
        logger = logging.getLogger("codex_lb_status")
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
            handler.close()
        logger.setLevel(logging.NOTSET)
        logger.propagate = True
