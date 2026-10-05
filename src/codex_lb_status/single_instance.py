"""Per-user Qt local-server ownership and bounded activation forwarding."""

from __future__ import annotations

import hashlib
import os
import tempfile

APPLICATION_SERVER_NAME = "io.github.victorstatko.codex_lb_status"
PROTOCOL_VERSION = "v1"
ALLOWED_COMMANDS = frozenset(("default", "settings", "background"))
MAX_COMMAND_BYTES = 128

try:
    from PyQt6.QtCore import QLockFile, QObject, QStandardPaths, pyqtSignal
    from PyQt6.QtNetwork import QLocalServer, QLocalSocket
except ImportError:  # pragma: no cover - exercised only without PyQt6.
    QObject = None


def encode_command(command: str) -> bytes:
    if command not in ALLOWED_COMMANDS:
        raise ValueError("unsupported activation command")
    return f"{PROTOCOL_VERSION}:{command}\n".encode("ascii")


def decode_command(payload: bytes) -> str | None:
    if len(payload) > MAX_COMMAND_BYTES:
        return None
    try:
        line = payload.splitlines()[0].decode("ascii")
    except (IndexError, UnicodeDecodeError):
        return None
    version, separator, command = line.partition(":")
    if version != PROTOCOL_VERSION or not separator or command not in ALLOWED_COMMANDS:
        return None
    return command


def _lock_file_path(name: str) -> str:
    """Return a per-user path that is stable for one local-server name."""

    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:24]
    user_id = getattr(os, "getuid", lambda: 0)()
    directory = (
        QStandardPaths.writableLocation(QStandardPaths.StandardLocation.RuntimeLocation)
        or QStandardPaths.writableLocation(QStandardPaths.StandardLocation.TempLocation)
        or tempfile.gettempdir()
    )
    return os.path.join(directory, f"codex-lb-status-{user_id}-{digest}.lock")


if QObject is None:

    class SingleInstance:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("PyQt6 >= 6.6 is required for single-instance behavior")

else:

    class SingleInstance(QObject):
        """Own the application socket or forward one validated command."""

        command_received = pyqtSignal(str)

        def __init__(
            self,
            name: str = APPLICATION_SERVER_NAME,
            parent: QObject | None = None,
        ):
            super().__init__(parent)
            self.name = name
            self.server = QLocalServer(self)
            self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
            self.server.newConnection.connect(self._accept_connection)
            self._sockets: list[QLocalSocket] = []
            self._lock_file = QLockFile(_lock_file_path(name))
            # This lock is held for the lifetime of the process. A crashed
            # process releases the OS lock immediately; the lock file itself
            # may remain and must not block a later launch based on its age.
            self._lock_file.setStaleLockTime(0)
            self._lock_acquired = False
            self._owns_server = False

        @property
        def owns_server(self) -> bool:
            return self._owns_server

        def acquire(self, command: str = "default") -> bool:
            encode_command(command)
            if self._forward_to_existing(command):
                return False

            # The probe and server.listen() cannot be the ownership decision:
            # two launchers can pass the probe before either one listens. The
            # lock serializes that gap and makes stale-socket removal safe for
            # all instances using this version of the application.
            if not self._lock_file.tryLock(0):
                return False

            self._lock_acquired = True
            if self._forward_to_existing(command):
                self._release_lock()
                return False
            if not self.server.listen(self.name):
                # A live server may have appeared before we acquired the
                # lock (for example, an older application version).
                if self._forward_to_existing(command):
                    self._release_lock()
                    return False
                # At this point the endpoint is not accepting connections,
                # so it is the crash residue that Qt documents removeServer()
                # for. The lock prevents another current launcher racing us.
                QLocalServer.removeServer(self.name)
                if not self.server.listen(self.name):
                    self._release_lock()
                    return False
            self._owns_server = True
            return True

        def _release_lock(self) -> None:
            if self._lock_acquired:
                self._lock_file.unlock()
                self._lock_acquired = False

        def _forward_to_existing(self, command: str) -> bool:
            socket = QLocalSocket(self)
            socket.connectToServer(self.name, QLocalSocket.OpenModeFlag.WriteOnly)
            if not socket.waitForConnected(300):
                socket.deleteLater()
                return False
            payload = encode_command(command)
            socket.write(payload)
            written = socket.waitForBytesWritten(300)
            socket.disconnectFromServer()
            socket.deleteLater()
            return written

        def _accept_connection(self) -> None:
            while self.server.hasPendingConnections():
                socket = self.server.nextPendingConnection()
                if socket is None:
                    continue
                self._sockets.append(socket)
                socket.readyRead.connect(
                    lambda socket=socket: self._read_socket(socket)
                )
                socket.disconnected.connect(
                    lambda socket=socket: self._forget_socket(socket)
                )

        def _read_socket(self, socket: QLocalSocket) -> None:
            payload = bytes(socket.read(MAX_COMMAND_BYTES + 1))
            command = decode_command(payload)
            if command is not None:
                self.command_received.emit(command)
            socket.disconnectFromServer()

        def _forget_socket(self, socket: QLocalSocket) -> None:
            if socket in self._sockets:
                self._sockets.remove(socket)
            socket.deleteLater()

        def close(self) -> None:
            if self._owns_server:
                self.server.close()
                self._owns_server = False
            self._release_lock()


__all__ = [
    "ALLOWED_COMMANDS",
    "APPLICATION_SERVER_NAME",
    "MAX_COMMAND_BYTES",
    "PROTOCOL_VERSION",
    "SingleInstance",
    "decode_command",
    "encode_command",
]
