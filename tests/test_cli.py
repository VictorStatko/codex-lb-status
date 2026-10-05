"""Step 1 command-line and import-safety checks."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from codex_lb_status import __version__
from codex_lb_status.app import (
    CliOptions,
    build_parser,
    configure_qt_platform,
    parse_args,
)


def test_version_constant_matches_project_metadata() -> None:
    root = Path(__file__).resolve().parents[1]
    metadata = tomllib.loads((root / "pyproject.toml").read_text())
    assert __version__ == metadata["project"]["version"]


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        ([], CliOptions()),
        (["--background"], CliOptions(background=True)),
        (["--settings"], CliOptions(settings=True)),
    ],
)
def test_parse_startup_intent(arguments: list[str], expected: CliOptions) -> None:
    assert parse_args(arguments) == expected


def test_version_option_prints_project_version(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as raised:
        build_parser().parse_args(["--version"])

    assert raised.value.code == 0
    assert capsys.readouterr().out == f"codex-lb-status {__version__}\n"


def test_conflicting_startup_intents_are_rejected() -> None:
    with pytest.raises(SystemExit) as raised:
        build_parser().parse_args(["--background", "--settings"])

    assert raised.value.code == 2


def test_unknown_option_is_rejected() -> None:
    with pytest.raises(SystemExit) as raised:
        build_parser().parse_args(["--not-a-real-option"])

    assert raised.value.code == 2


def test_wayland_session_prefers_xcb_for_window_positioning() -> None:
    environment = {"XDG_SESSION_TYPE": "wayland", "DISPLAY": ":0"}

    assert configure_qt_platform(environment)
    assert environment["QT_QPA_PLATFORM"] == "xcb"


def test_explicit_qt_platform_is_preserved() -> None:
    environment = {
        "XDG_SESSION_TYPE": "wayland",
        "DISPLAY": ":0",
        "QT_QPA_PLATFORM": "wayland",
    }

    assert not configure_qt_platform(environment)
    assert environment["QT_QPA_PLATFORM"] == "wayland"
