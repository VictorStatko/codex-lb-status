"""Bounded local activation forwarding tests."""

from __future__ import annotations

import os
import threading
import uuid

import pytest

pytest.importorskip("PyQt6")

from codex_lb_status.single_instance import (
    SingleInstance,
    decode_command,
    encode_command,
)


def test_activation_protocol_is_versioned_and_bounded() -> None:
    assert decode_command(encode_command("settings")) == "settings"
    assert decode_command(b"v1:unknown\n") is None
    assert decode_command(b"v2:default\n") is None
    assert decode_command(b"x" * 129) is None
    with pytest.raises(ValueError):
        encode_command("quit")


def test_live_instance_receives_only_allowlisted_commands(qtbot) -> None:
    name = f"io.github.victorstatko.codex_lb_status.test.{os.getpid()}"
    first = SingleInstance(name)
    second = SingleInstance(name)
    received = []
    first.command_received.connect(received.append)
    try:
        assert first.acquire("default")
        assert not second.acquire("settings")
        qtbot.waitUntil(lambda: received == ["settings"], timeout=1_000)
        assert first.owns_server
    finally:
        second.close()
        first.close()


def test_concurrent_acquire_creates_only_one_owner(monkeypatch) -> None:
    import codex_lb_status.single_instance as single_instance_module

    class Signal:
        def connect(self, _slot) -> None:
            pass

    class FakeLocalServer:
        class SocketOption:
            UserAccessOption = object()

        endpoint_lock = threading.Lock()
        endpoint_listening = False

        def __init__(self, _parent) -> None:
            self.newConnection = Signal()

        def setSocketOptions(self, _options) -> None:
            pass

        def listen(self, _name: str) -> bool:
            with self.endpoint_lock:
                if self.endpoint_listening:
                    return False
                self.endpoint_listening = True
                return True

        @classmethod
        def removeServer(cls, _name: str) -> bool:
            with cls.endpoint_lock:
                cls.endpoint_listening = False
            return True

        def close(self) -> None:
            type(self).removeServer("")

    monkeypatch.setattr(single_instance_module, "QLocalServer", FakeLocalServer)
    name = (
        f"io.github.victorstatko.codex_lb_status.test.{os.getpid()}.{uuid.uuid4().hex}"
    )
    probe_barrier = threading.Barrier(2)
    results = []
    errors = []

    def acquire() -> None:
        instance = SingleInstance(name)
        first_probe = True

        def probe(_command: str) -> bool:
            nonlocal first_probe
            if first_probe:
                first_probe = False
                probe_barrier.wait(timeout=1)
            return False

        instance._forward_to_existing = probe
        try:
            results.append(instance.acquire("background"))
        except BaseException as error:
            errors.append(error)
        finally:
            instance.close()

    threads = [threading.Thread(target=acquire) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)

    assert all(not thread.is_alive() for thread in threads)
    assert not errors
    assert sorted(results) == [False, True]
