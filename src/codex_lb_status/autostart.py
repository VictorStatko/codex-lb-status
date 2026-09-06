"""User-scoped XDG autostart management."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

APPLICATION_ID = "io.github.victorstatko.codex_lb_status"


def autostart_path(config_home: Path | str | None = None) -> Path:
    if config_home is None:
        configured = os.environ.get("XDG_CONFIG_HOME")
        config_home = (
            Path(configured).expanduser() if configured else Path.home() / ".config"
        )
    return Path(config_home) / "autostart" / f"{APPLICATION_ID}.desktop"


def desktop_entry() -> str:
    return "\n".join(
        (
            "[Desktop Entry]",
            "Type=Application",
            "Name=Codex LB Status",
            "Comment=Read-only Codex LB status indicator",
            "Exec=/usr/bin/codex-lb-status --background",
            "X-GNOME-Autostart-enabled=true",
            "NoDisplay=true",
            "",
        )
    )


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=path.parent,
        text=True,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
        os.chmod(path, 0o600)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


class AutostartManager:
    """Create and remove only this application's desktop entry."""

    def __init__(self, config_home: Path | str | None = None):
        self.path = autostart_path(config_home)

    @property
    def enabled(self) -> bool:
        return self.path.is_file()

    def set_enabled(self, enabled: bool) -> None:
        if enabled:
            _atomic_write(self.path, desktop_entry())
        else:
            self.path.unlink(missing_ok=True)

    def snapshot(self) -> bytes | None:
        try:
            return self.path.read_bytes()
        except FileNotFoundError:
            return None

    def restore(self, snapshot: bytes | None) -> None:
        if snapshot is None:
            self.path.unlink(missing_ok=True)
            return
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.", dir=self.path.parent
        )
        temporary_path = Path(temporary_name)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(snapshot)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, self.path)
            os.chmod(self.path, 0o600)
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise


__all__ = ["APPLICATION_ID", "AutostartManager", "autostart_path", "desktop_entry"]
