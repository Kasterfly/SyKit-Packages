"""Validate the SyKit-Packages repository layout and index.json.

Standard library only. Mirrors the rules the SyKit 0.4.0 package handler
applies when it resolves packages from this repository, so anything that
passes here should install cleanly (against a matching SyKit tree).

Usage: python validate.py
Exits nonzero and lists every problem found.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
INDEX_PATH = ROOT / "index.json"
MANIFEST_NAME = "SyKitPackage.json"
SECTION_DIRS = ("add", "edit", "remove")
PACKAGE_ENTRIES = {MANIFEST_NAME, *SECTION_DIRS}
MANIFEST_KEYS = {"id", "name", "desc", "package-req", "credit", "sykit-req", "deps"}
VERSION_PATTERN = re.compile(r"\d+\.\d+\.\d+")
DEP_MAX_LENGTH = 200
PROTECTED_ROOTS = {".git", ".packages", "__pycache__"}
NON_PACKAGE_FILES = {"index.json", "validate.py"}
ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
SEGMENT_PATTERN = re.compile(r"[A-Za-z0-9._-]+")
WINDOWS_DEVICE_NAMES = frozenset(
    {
        "aux",
        "con",
        "nul",
        "prn",
        *(f"com{number}" for number in range(1, 10)),
        *(f"lpt{number}" for number in range(1, 10)),
    }
)

problems: list[str] = []


def problem(message: str) -> None:
    problems.append(message)


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant {value!r}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key {key!r}")
        value[key] = item
    return value


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as file:
        return json.load(
            file,
            parse_constant=_reject_json_constant,
            object_pairs_hook=_unique_object,
        )


def clean_text(value: str) -> bool:
    return not any(
        ord(character) < 32 or 127 <= ord(character) <= 159 for character in value
    )


def reserved_component(value: str) -> bool:
    stem = value.rstrip(" .").split(".", 1)[0].casefold()
    return stem in WINDOWS_DEVICE_NAMES


def valid_segment(value: str) -> bool:
    return (
        SEGMENT_PATTERN.fullmatch(value) is not None
        and set(value) != {"."}
        and value == value.rstrip(" .")
        and not reserved_component(value)
    )


def valid_target(target: str) -> bool:
    parts = target.replace("\\", "/").split("/")
    if not parts or any(
        part in ("", ".", "..")
        or ":" in part
        or part != part.rstrip(" .")
        or not clean_text(part)
        or reserved_component(part)
        for part in parts
    ):
        return False
    return parts[0].casefold() not in PROTECTED_ROOTS


def check_index() -> dict[str, str]:
    """Return the validated name -> folder mapping from index.json."""
    if not INDEX_PATH.is_file():
        problem("index.json is missing at the repository root.")
        return {}
    try:
        value = load_json(INDEX_PATH)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        problem(f"index.json could not be parsed: {error}")
        return {}
    packages = value.get("packages") if isinstance(value, dict) else None
    if not isinstance(packages, dict):
        problem('index.json must contain a "packages" object.')
        return {}
    mapping: dict[str, str] = {}
    seen: set[str] = set()
    for name, entry in packages.items():
        label = f"index.json entry {name!r}"
        if not isinstance(name, str) or not ID_PATTERN.fullmatch(name):
            problem(f"{label}: invalid package name.")
            continue
        if name.casefold() in seen:
            problem(f"{label}: names must be unique ignoring case.")
            continue
        seen.add(name.casefold())
        if not isinstance(entry, dict):
            problem(f"{label}: must be an object.")
            continue
        unknown = sorted(set(entry) - {"path", "desc"})
        if unknown:
            problem(f"{label}: unknown keys: {', '.join(unknown)}.")
        path = entry.get("path", name)
        if not isinstance(path, str) or not path or not all(
            valid_segment(part) for part in path.split("/")
        ):
            problem(f"{label}: invalid path.")
            continue
        desc = entry.get("desc", "")
        if not isinstance(desc, str) or not clean_text(desc):
            problem(f"{label}: desc must be a clean string.")
        mapping[name] = path
    return mapping


def check_manifest(folder: Path) -> None:
    manifest_path = folder / MANIFEST_NAME
    label = f"{folder.name}/{MANIFEST_NAME}"
    try:
        value = load_json(manifest_path)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        problem(f"{label}: could not be parsed: {error}")
        return
    if not isinstance(value, dict):
        problem(f"{label}: must contain a JSON object.")
        return
    unknown = sorted(set(value) - MANIFEST_KEYS)
    if unknown:
        problem(f"{label}: unknown keys: {', '.join(unknown)}.")
    package_id = value.get("id")
    if (
        not isinstance(package_id, str)
        or not ID_PATTERN.fullmatch(package_id)
        or package_id.endswith(".")
        or reserved_component(package_id)
    ):
        problem(f"{label}: missing or invalid id.")
    for key in ("name", "desc"):
        if key in value and (
            not isinstance(value[key], str) or not clean_text(value[key])
        ):
            problem(f"{label}: {key} must be a clean string.")
    sykit_req = value.get("sykit-req", "")
    if not isinstance(sykit_req, str) or (
        sykit_req and VERSION_PATTERN.fullmatch(sykit_req) is None
    ):
        problem(f'{label}: sykit-req must be a version like "0.4.1".')
    deps = value.get("deps", [])
    if isinstance(deps, str):
        deps = [deps]
    if not isinstance(deps, list) or not all(
        isinstance(entry, str) and entry.strip() for entry in deps
    ):
        problem(f"{label}: deps must be a string or list of non-empty strings.")
    else:
        deps = [entry.strip() for entry in deps]
        for entry in deps:
            if (
                len(entry) > DEP_MAX_LENGTH
                or not entry[0].isalnum()
                or not all(32 <= ord(character) <= 126 for character in entry)
            ):
                problem(f"{label}: deps entry {entry!r} is not a valid requirement.")
        folded = [entry.casefold() for entry in deps]
        if len(set(folded)) != len(folded):
            problem(f"{label}: deps may not contain duplicates.")


def check_package_folder(folder: Path) -> None:
    label = folder.name
    if not (folder / MANIFEST_NAME).is_file():
        problem(f"{label}: does not contain {MANIFEST_NAME}.")
        return
    check_manifest(folder)

    for entry in folder.iterdir():
        name = entry.name
        if name in PACKAGE_ENTRIES:
            if name != MANIFEST_NAME and not entry.is_dir():
                problem(f"{label}/{name}: must be a folder.")
            continue
        upper = name.upper()
        if name.startswith(".") or upper.startswith(("README", "LICENSE")):
            continue
        problem(
            f"{label}/{name}: unexpected entry; packages may only contain "
            f"{MANIFEST_NAME} plus add/, edit/ and remove/."
        )

    if not any((folder / section).is_dir() for section in SECTION_DIRS):
        problem(f"{label}: has no add/, edit/, or remove/ folder.")

    folded_paths: set[str] = set()
    for path in sorted(folder.rglob("*")):
        relative = path.relative_to(folder).as_posix()
        if path.is_symlink():
            problem(f"{label}/{relative}: symbolic links are not allowed.")
            continue
        if not path.is_file():
            continue
        folded = relative.casefold()
        if folded in folded_paths:
            problem(f"{label}/{relative}: path collides with another ignoring case.")
        folded_paths.add(folded)
        parts = relative.split("/")
        if parts[0] in ("add", "edit") and len(parts) > 1:
            target = "/".join(parts[1:])
            if not valid_target(target):
                problem(f"{label}/{relative}: unsafe target path.")

    remove_root = folder / "remove"
    if remove_root.is_dir():
        for list_path in sorted(remove_root.rglob("*")):
            if not list_path.is_file():
                continue
            relative = list_path.relative_to(folder).as_posix()
            if list_path.suffix != ".json":
                problem(f"{label}/{relative}: remove/ may only hold .json lists.")
                continue
            try:
                value = load_json(list_path)
            except (OSError, ValueError, json.JSONDecodeError) as error:
                problem(f"{label}/{relative}: could not be parsed: {error}")
                continue
            if not isinstance(value, list) or not all(
                isinstance(item, str) and valid_target(item) for item in value
            ):
                problem(f"{label}/{relative}: must be a list of safe SyKit paths.")


def main() -> int:
    mapping = check_index()

    listed_folders = set()
    for name, path in mapping.items():
        folder = ROOT.joinpath(*path.split("/"))
        listed_folders.add(path.split("/")[0])
        if not folder.is_dir():
            problem(f"index.json entry {name!r}: folder {path!r} does not exist.")
            continue
        check_package_folder(folder)

    for entry in sorted(ROOT.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        if entry.name in listed_folders:
            continue
        if (entry / MANIFEST_NAME).is_file():
            problem(
                f"{entry.name}: looks like a package but is not listed in "
                "index.json."
            )

    if problems:
        print(f"validate: {len(problems)} problem(s) found")
        for message in problems:
            print(f"  - {message}")
        return 1
    count = len(mapping)
    print(f"validate: OK ({count} package(s) listed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
