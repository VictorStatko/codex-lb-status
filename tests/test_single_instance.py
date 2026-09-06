"""Bounded local activation forwarding tests."""

from __future__ import annotations

import os

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
