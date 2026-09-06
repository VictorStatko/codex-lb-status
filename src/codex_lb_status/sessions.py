"""Origin-scoped, permission-restricted persistent cookie jars."""

from __future__ import annotations

import hashlib
import os
import tempfile
from http.cookiejar import Cookie, CookieJar, MozillaCookieJar
from pathlib import Path
from time import time
from urllib.parse import urlsplit

from .config import normalize_base_url, sessions_directory


class SessionError(ValueError):
    """Raised when a persisted session cannot be safely loaded or saved."""


def origin_hash(origin: str) -> str:
    return hashlib.sha256(normalize_base_url(origin).encode("utf-8")).hexdigest()[:16]


def session_path(origin: str, state_directory: Path | str | None = None) -> Path:
    directory = (
        Path(state_directory) if state_directory is not None else sessions_directory()
    )
    return directory / f"{origin_hash(origin)}.cookies"


def _cookie_matches_origin(cookie: Cookie, origin: str) -> bool:
    parsed = urlsplit(normalize_base_url(origin))
    host = (parsed.hostname or "").lower()
    cookie_domain = cookie.domain.lstrip(".").lower()
    if cookie_domain != host:
        return False
    if cookie.port:
        origin_port = parsed.port or (443 if parsed.scheme == "https" else 80)
        allowed_ports = cookie.port.split(",")
        if str(origin_port) not in allowed_ports:
            return False
    if cookie.secure and parsed.scheme != "https":
        return False
    return bool(cookie.path and cookie.path.startswith("/"))


def _filtered_jar(jar: CookieJar, origin: str) -> CookieJar:
    filtered = CookieJar()
    now = time()
    for cookie in jar:
        if cookie.is_expired(now) or not _cookie_matches_origin(cookie, origin):
            continue
        filtered.set_cookie(cookie)
    return filtered


class SessionCookieStore:
    """Store cookies in a separate file for each normalized server origin."""

    def __init__(self, state_directory: Path | str | None = None):
        self.state_directory = (
            Path(state_directory)
            if state_directory is not None
            else sessions_directory()
        )

    def load(self, origin: str) -> CookieJar:
        normalized = normalize_base_url(origin)
        path = session_path(normalized, self.state_directory)
        jar = MozillaCookieJar(str(path))
        if not path.exists():
            return CookieJar()
        try:
            jar.load(ignore_discard=True, ignore_expires=False)
        except (OSError, ValueError) as error:
            raise SessionError("cannot read the saved dashboard session") from error
        return _filtered_jar(jar, normalized)

    def save(self, origin: str, cookies: CookieJar) -> Path:
        normalized = normalize_base_url(origin)
        filtered = _filtered_jar(cookies, normalized)
        self.state_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.state_directory, 0o700)
        target = session_path(normalized, self.state_directory)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.", dir=self.state_directory
        )
        temporary_path = Path(temporary_name)
        os.close(descriptor)
        try:
            output = MozillaCookieJar(str(temporary_path))
            for cookie in filtered:
                output.set_cookie(cookie)
            output.save(ignore_discard=True, ignore_expires=False)
            os.chmod(temporary_path, 0o600)
            os.replace(temporary_path, target)
            os.chmod(target, 0o600)
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise
        return target

    def clear(self, origin: str) -> None:
        path = session_path(normalize_base_url(origin), self.state_directory)
        path.unlink(missing_ok=True)


__all__ = ["SessionCookieStore", "SessionError", "origin_hash", "session_path"]
