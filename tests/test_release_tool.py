from __future__ import annotations

import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CURRENT_VERSION = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"][
    "version"
]
CURRENT_PARTS = tuple(int(part) for part in CURRENT_VERSION.split("."))
NEXT_VERSION = ".".join(
    str(part) for part in (*CURRENT_PARTS[:2], CURRENT_PARTS[2] + 1)
)
RELEASE_FILES = (
    "pyproject.toml",
    "src/codex_lb_status/__init__.py",
    "debian/changelog",
    "debian/io.github.victorstatko.codex_lb_status.metainfo.xml",
    "uv.lock",
)


def run_release(
    command: str, version: str, root: Path = ROOT
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/release.py"),
            command,
            version,
            "--root",
            str(root),
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def copy_release_files(destination: Path) -> None:
    for relative_path in RELEASE_FILES:
        source = ROOT / relative_path
        target = destination / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def test_current_release_metadata_is_synchronized() -> None:
    result = run_release("check", CURRENT_VERSION)

    assert result.returncode == 0, result.stderr


def test_prepare_release_updates_human_maintained_metadata(tmp_path: Path) -> None:
    copy_release_files(tmp_path)

    result = run_release("prepare", NEXT_VERSION, tmp_path)

    assert result.returncode == 0, result.stderr
    assert f'version = "{NEXT_VERSION}"' in (tmp_path / "pyproject.toml").read_text()
    assert (
        f'__version__ = "{NEXT_VERSION}"'
        in (tmp_path / "src/codex_lb_status/__init__.py").read_text()
    )
    assert (
        (tmp_path / "debian/changelog")
        .read_text()
        .startswith(f"codex-lb-status ({NEXT_VERSION}) unstable; urgency=medium")
    )
    assert (
        f'<release version="{NEXT_VERSION}" date="'
        in (
            tmp_path / "debian/io.github.victorstatko.codex_lb_status.metainfo.xml"
        ).read_text()
    )

    result = run_release("check", NEXT_VERSION, tmp_path)

    assert result.returncode == 2
    assert f"uv.lock has '{CURRENT_VERSION}'" in result.stderr


def test_prepare_release_is_idempotent(tmp_path: Path) -> None:
    copy_release_files(tmp_path)

    first = run_release("prepare", NEXT_VERSION, tmp_path)
    second = run_release("prepare", NEXT_VERSION, tmp_path)

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert (tmp_path / "debian/changelog").read_text().count(
        f"codex-lb-status ({NEXT_VERSION})"
    ) == 1
    appstream = (
        tmp_path / "debian/io.github.victorstatko.codex_lb_status.metainfo.xml"
    ).read_text()
    assert appstream.count(f'<release version="{NEXT_VERSION}"') == 1


@pytest.mark.parametrize("version", ["1.2", "v1.2.3", "1.2.3-rc1", "next"])
def test_prepare_release_rejects_non_release_versions(
    tmp_path: Path, version: str
) -> None:
    copy_release_files(tmp_path)

    result = run_release("prepare", version, tmp_path)

    assert result.returncode == 2
    assert "expected MAJOR.MINOR.PATCH" in result.stderr
