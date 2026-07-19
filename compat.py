"""Compatibility check: install every listed package against a SyKit tree.

Usage: python compat.py <path-to-sykit-checkout>

For each package in index.json, this copies the SyKit tree, installs the
package (SyKit 0.4.0+ flags first, with a fallback for older handlers),
runs the full SyKit test suite, and removes the package again. Packages
listed in a manifest's package-req are installed first and removed last,
in dependency order. Any install, test, or removal failure fails the run.

CI runs this on every push and on a weekly schedule; run it manually
(workflow_dispatch) after each SyKit release to confirm the library still
works against the new version.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
IGNORE_COPY = shutil.ignore_patterns(
    ".git", ".packages", "__pycache__", "*.pyc", "*.pyo"
)


def run_command(
    arguments: list[str], cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(arguments, cwd=cwd, capture_output=True, text=True)


def load_manifest(folder: Path) -> dict:
    return json.loads((folder / "SyKitPackage.json").read_text(encoding="utf-8"))


def requirement_folders(
    manifest: dict, packages: dict, root: Path
) -> list[tuple[str, Path]]:
    """Resolve package-req ids to (id, folder) pairs, dependencies first."""
    ordered: list[tuple[str, Path]] = []
    seen: set[str] = set()

    def visit(requirements) -> None:
        if isinstance(requirements, str):
            requirements = [requirements]
        for requirement in requirements:
            folded = str(requirement).casefold()
            if folded in seen:
                continue
            seen.add(folded)
            for name in sorted(packages):
                folder = root.joinpath(*packages[name].get("path", name).split("/"))
                required = load_manifest(folder)
                if str(required.get("id", "")).casefold() == folded:
                    visit(required.get("package-req", []))
                    ordered.append((required["id"], folder))
                    break
            else:
                raise ValueError(
                    f"required package {requirement!r} is not in index.json"
                )

    visit(manifest.get("package-req", []))
    return ordered


def check_package(
    name: str,
    folder: Path,
    sykit_source: Path,
    base: Path,
    install_deps: bool,
    packages: dict,
) -> str | None:
    """Install, test, and remove one package. Returns an error or None."""
    manifest = load_manifest(folder)
    package_id = manifest["id"]
    deps = manifest.get("deps", [])
    if isinstance(deps, str):
        deps = [deps]
    if deps and install_deps:
        # CI only (--install-deps): local runs must not touch the
        # environment, so declared dependencies stay uninstalled there.
        installed = run_command(
            [sys.executable, "-m", "pip", "install", *deps]
        )
        if installed.returncode != 0:
            return (
                f"{name}: declared dependencies failed to install\n"
                f"{installed.stdout}{installed.stderr}"
            )
        print(f"  installed declared deps: {', '.join(deps)}")
    tool = base / f"SyKit-{name}"
    shutil.copytree(sykit_source, tool, ignore=IGNORE_COPY)

    requirements = requirement_folders(manifest, packages, ROOT)
    for required_id, required_folder in requirements:
        installed = run_command(
            [sys.executable, str(tool), "package", "add", str(required_folder),
             "--yes", "--allow-core"]
        )
        if installed.returncode != 0:
            return (
                f"{name}: required package {required_id} failed to install\n"
                f"{installed.stdout}{installed.stderr}"
            )
        print(f"  installed requirement: {required_id}")

    add = run_command(
        [sys.executable, str(tool), "package", "add", str(folder), "--yes",
         "--allow-core"]
    )
    if add.returncode != 0:
        # Handlers before 0.4.0 do not know the flags; retry plain.
        add = run_command([sys.executable, str(tool), "package", "add", str(folder)])
    if add.returncode != 0:
        return f"{name}: install failed\n{add.stdout}{add.stderr}"
    added = [line for line in add.stdout.splitlines() if line.startswith("Added")]
    print(f"  {added[-1] if added else 'installed'}")

    tests = run_command(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests"], cwd=tool
    )
    if tests.returncode != 0:
        return (
            f"{name}: SyKit test suite failed after install\n"
            f"{tests.stderr[-3000:]}"
        )
    summary = tests.stderr.strip().splitlines()
    print(f"  {summary[-1] if summary else 'tests OK'}")

    remove = run_command([sys.executable, str(tool), "package", "remove", package_id])
    if remove.returncode != 0:
        return f"{name}: removal failed\n{remove.stdout}{remove.stderr}"
    for required_id, _folder in reversed(requirements):
        removed = run_command(
            [sys.executable, str(tool), "package", "remove", required_id]
        )
        if removed.returncode != 0:
            return (
                f"{name}: removing requirement {required_id} failed\n"
                f"{removed.stdout}{removed.stderr}"
            )
    print("  removed cleanly")
    return None


def main() -> int:
    arguments = sys.argv[1:]
    install_deps = "--install-deps" in arguments
    arguments = [entry for entry in arguments if entry != "--install-deps"]
    if len(arguments) != 1:
        print("Usage: python compat.py <path-to-sykit-checkout> [--install-deps]")
        return 2
    sykit_source = Path(arguments[0]).resolve()
    if not (sykit_source / "package.py").is_file():
        print(f"{sykit_source} does not look like a SyKit checkout.")
        return 2

    index = json.loads((ROOT / "index.json").read_text(encoding="utf-8"))
    packages = index.get("packages", {})
    if not packages:
        print("compat: no packages listed; nothing to check.")
        return 0

    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="sykit-compat-") as temporary:
        for name in sorted(packages):
            entry = packages[name]
            folder = ROOT.joinpath(*entry.get("path", name).split("/"))
            print(f"=== {name} ===")
            try:
                error = check_package(
                    name, folder, sykit_source, Path(temporary), install_deps,
                    packages,
                )
            except (OSError, ValueError, KeyError, json.JSONDecodeError) as issue:
                error = f"{name}: {issue}"
            if error:
                failures.append(error)

    if failures:
        print(f"compat: {len(failures)} failure(s)")
        for failure in failures:
            print("-" * 60)
            print(failure)
        return 1
    print(f"compat: OK ({len(packages)} package(s) verified)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
