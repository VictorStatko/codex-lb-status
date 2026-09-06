#!/usr/bin/env python3
"""Prepare and validate synchronized project release metadata."""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
import xml.etree.ElementTree as ET
from datetime import date, datetime
from email.utils import format_datetime
from pathlib import Path

PROJECT_NAME = "codex-lb-status"
VERSION_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


class ReleaseError(ValueError):
    """Raised when release metadata is invalid or inconsistent."""


def parse_version(value: str) -> tuple[int, int, int]:
    if not VERSION_PATTERN.fullmatch(value):
        raise ReleaseError(
            f"invalid version {value!r}; expected MAJOR.MINOR.PATCH, for example 0.1.35"
        )
    return tuple(int(part) for part in value.split("."))  # type: ignore[return-value]


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise ReleaseError(f"required file is missing: {path}") from error


def replace_once(text: str, pattern: str, replacement: str, label: str) -> str:
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.MULTILINE)
    if count != 1:
        raise ReleaseError(f"could not update {label}")
    return updated


def project_metadata(root: Path) -> dict[str, object]:
    return tomllib.loads(read_text(root / "pyproject.toml"))["project"]


def current_versions(root: Path) -> dict[str, str]:
    metadata = project_metadata(root)
    project_version = str(metadata["version"])

    init_match = re.search(
        r'^__version__ = "([^"]+)"$',
        read_text(root / "src/codex_lb_status/__init__.py"),
        re.MULTILINE,
    )
    if not init_match:
        raise ReleaseError("could not read src/codex_lb_status/__init__.py version")

    changelog_match = re.search(
        rf"^{re.escape(PROJECT_NAME)} \(([^)]+)\)",
        read_text(root / "debian/changelog"),
        re.MULTILINE,
    )
    if not changelog_match:
        raise ReleaseError("could not read the top Debian changelog version")

    try:
        appstream_root = ET.fromstring(
            read_text(
                root / "debian/io.github.victorstatko.codex_lb_status.metainfo.xml"
            )
        )
    except ET.ParseError as error:
        raise ReleaseError(f"invalid AppStream metadata: {error}") from error
    appstream_release = appstream_root.find("./releases/release")
    if appstream_release is None or not appstream_release.get("version"):
        raise ReleaseError("could not read the latest AppStream release version")

    lock_data = tomllib.loads(read_text(root / "uv.lock"))
    lock_versions = [
        str(package["version"])
        for package in lock_data.get("package", [])
        if package.get("name") == PROJECT_NAME
    ]
    if len(lock_versions) != 1:
        raise ReleaseError(f"expected exactly one {PROJECT_NAME} package in uv.lock")

    return {
        "pyproject.toml": project_version,
        "src/codex_lb_status/__init__.py": init_match.group(1),
        "debian/changelog": changelog_match.group(1),
        "AppStream metadata": appstream_release.get("version", ""),
        "uv.lock": lock_versions[0],
    }


def check_release(root: Path, version: str) -> None:
    parse_version(version)
    mismatches = {
        location: actual
        for location, actual in current_versions(root).items()
        if actual != version
    }
    if mismatches:
        details = ", ".join(
            f"{location} has {actual!r}" for location, actual in mismatches.items()
        )
        raise ReleaseError(f"expected release {version!r}, but {details}")
    print(f"Release metadata matches {version}.")


def author(metadata: dict[str, object]) -> tuple[str, str]:
    authors = metadata.get("authors")
    if not isinstance(authors, list) or not authors or not isinstance(authors[0], dict):
        raise ReleaseError("pyproject.toml must define a project author")
    name = authors[0].get("name")
    email = authors[0].get("email")
    if not isinstance(name, str) or not isinstance(email, str):
        raise ReleaseError("the primary project author must have a name and email")
    return name, email


def prepare_release(
    root: Path,
    version: str,
    *,
    release_date: date | None = None,
    release_datetime: datetime | None = None,
) -> None:
    target = parse_version(version)
    metadata = project_metadata(root)
    existing_version = str(metadata["version"])
    if target < parse_version(existing_version):
        raise ReleaseError(
            f"release {version} is older than the current project version "
            f"{existing_version}"
        )

    today = release_date or date.today()
    now = release_datetime or datetime.now().astimezone()
    name, email = author(metadata)

    pyproject_path = root / "pyproject.toml"
    pyproject = read_text(pyproject_path)
    if existing_version != version:
        pyproject_path.write_text(
            replace_once(
                pyproject,
                rf'^version = "{re.escape(existing_version)}"$',
                f'version = "{version}"',
                "pyproject.toml version",
            ),
            encoding="utf-8",
        )

    init_path = root / "src/codex_lb_status/__init__.py"
    init_text = read_text(init_path)
    init_path.write_text(
        replace_once(
            init_text,
            r'^__version__ = "[^"]+"$',
            f'__version__ = "{version}"',
            "package version",
        ),
        encoding="utf-8",
    )

    changelog_path = root / "debian/changelog"
    changelog = read_text(changelog_path)
    changelog_match = re.match(rf"{re.escape(PROJECT_NAME)} \(([^)]+)\)", changelog)
    if not changelog_match:
        raise ReleaseError("could not read the top Debian changelog version")
    changelog_version = changelog_match.group(1)
    if target < parse_version(changelog_version):
        raise ReleaseError(
            f"release {version} is older than Debian changelog version "
            f"{changelog_version}"
        )
    if changelog_version != version:
        entry = (
            f"{PROJECT_NAME} ({version}) unstable; urgency=medium\n\n"
            f"  * Prepare release {version}.\n\n"
            f" -- {name} <{email}>  {format_datetime(now)}\n\n"
        )
        changelog_path.write_text(entry + changelog, encoding="utf-8")

    appstream_path = root / "debian/io.github.victorstatko.codex_lb_status.metainfo.xml"
    appstream = read_text(appstream_path)
    existing_release = re.search(r'<release version="([^"]+)" date="[^"]+">', appstream)
    if not existing_release:
        raise ReleaseError("could not read the latest AppStream release")
    appstream_version = existing_release.group(1)
    if target < parse_version(appstream_version):
        raise ReleaseError(
            f"release {version} is older than AppStream version {appstream_version}"
        )
    if appstream_version != version:
        entry = (
            f'    <release version="{version}" date="{today.isoformat()}">\n'
            "      <description>\n"
            f"        <p>Prepared release {version}.</p>\n"
            "      </description>\n"
            "    </release>\n"
        )
        appstream = replace_once(
            appstream,
            r"^(  <releases>\n)",
            rf"\g<1>{entry}",
            "AppStream release",
        )
        appstream_path.write_text(appstream, encoding="utf-8")

    print(f"Prepared release metadata for {version}.")
    print("Run uv lock next, then review the generated changelog and AppStream notes.")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("command", choices=("prepare", "check"))
    result.add_argument("version", help="release version in MAJOR.MINOR.PATCH form")
    result.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help=argparse.SUPPRESS,
    )
    return result


def main() -> int:
    arguments = parser().parse_args()
    try:
        if arguments.command == "prepare":
            prepare_release(arguments.root, arguments.version)
        else:
            check_release(arguments.root, arguments.version)
    except (ReleaseError, KeyError, tomllib.TOMLDecodeError) as error:
        print(f"release metadata error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
