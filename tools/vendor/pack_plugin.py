#!/usr/bin/env python3
"""Pack a QGroundControl plugin package directory into an installable .qgcplugin zip.

A .qgcplugin is the file "Install plugin…" consumes: a zip holding a package directory's
*contents* at its root (qgcplugin.json, optionally bin/<platform>/, qml/, assets/). Making
one is `zip -r`; making one that installs is not, because PluginInstaller rejects a dozen
shapes and every one of those rejections happens on the user's machine, where the author
never sees it. So this tool applies the installer's rules at pack time — the whole point is
that a package which fails to install cannot be produced in the first place.

Each check below mirrors a specific gate in src/PluginSystem/PluginInstaller.cc or
QGCPluginLoader.cc. They are duplicated here deliberately rather than shared: the tool ships
inside the SDK zip and runs where there is no QGC checkout to read the rules from. A test
(tools/tests/test_pack_plugin.py) diffs the duplicated constants against the C++ whenever the
repo is present, so the copy cannot drift silently.

Stdlib only, single file, no local imports — same constraint as verify_plugin_out_of_tree.py,
and for the same reason: it must run from an unpacked SDK zip.

Usage:
    python3 pack_plugin.py <package-dir> [-o <out.qgcplugin>] [--binary <file>]
        [--platform <key>] [--force] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import re
import stat
import sys
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple, NoReturn

if TYPE_CHECKING:
    from collections.abc import Iterable

MANIFEST_FILENAME = "qgcplugin.json"

# PluginInstaller.cc's kMaxPackageBytes. The installer refuses to extract past this, so a
# package over it is unusable however well it zips — checked against the uncompressed total,
# which is what that ceiling actually measures.
MAX_PACKAGE_BYTES = 512 * 1024 * 1024

# QGCPluginLoader::platformBinarySubdir(). The documented per-platform key looked up first;
# the loader also accepts any single binary under bin/<prefix>-* as a fallback.
PLATFORM_KEYS = ("macos-universal", "windows-x64", "linux-x64")

# QGCPluginLoader::pluginBinaryFilters(), flattened. Used to find what the loader would
# consider a plugin binary under bin/.
BINARY_SUFFIXES = (".dylib", ".bundle", ".dll", ".so")

# Never packed: editor/OS/VCS droppings and the author's own build output. A stray .DS_Store
# is harmless; __MACOSX and .git are not, and build/ would bloat the package with the very
# object files the binary was linked from.
EXCLUDED_NAMES = frozenset({".git", ".DS_Store", "__MACOSX", ".gitignore", "__pycache__"})


class PackError(Exception):
    """A reason the package cannot be built, phrased for the author who has to fix it."""


class Entry(NamedTuple):
    """One file destined for the archive."""

    source: Path
    arcname: str
    size: int
    mode: int


def _fail(message: str) -> NoReturn:
    """NoReturn, not None: it lets a type checker narrow after a guard, the same way an
    inline `raise` would, so the checks below read as guards rather than as branches."""
    raise PackError(message)


# --- Manifest ------------------------------------------------------------------------

# QVersionNumber::fromString accepts a leading numeric run ("1", "1.0", "1.0.0"); a string
# that does not start with a digit yields a null version, which PluginManifest rejects.
_VERSION_RE = re.compile(r"^\d+(\.\d+)*")


def load_manifest(package_dir: Path) -> dict[str, object]:
    """Read and validate qgcplugin.json exactly as PluginManifest::fromJson would."""
    manifest_path = package_dir / MANIFEST_FILENAME
    if not manifest_path.is_file():
        _fail(f"{package_dir} has no {MANIFEST_FILENAME} at its root")

    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        _fail(f"malformed {MANIFEST_FILENAME}: {exc}")
    except UnicodeDecodeError as exc:
        _fail(f"{MANIFEST_FILENAME} is not valid UTF-8: {exc}")

    if not isinstance(raw, dict):
        _fail(f"{MANIFEST_FILENAME} must contain a JSON object")

    for field in ("id", "name", "vendor", "version", "tier"):
        value = raw.get(field)
        if not isinstance(value, str) or not value:
            _fail(f"{MANIFEST_FILENAME}: missing or non-string required field '{field}'")

    version = raw["version"]
    if not _VERSION_RE.match(version):
        _fail(f"{MANIFEST_FILENAME}: invalid 'version' value '{version}'")

    tier = raw["tier"]
    if tier not in ("qml", "sdk", "internal"):
        _fail(f"{MANIFEST_FILENAME}: unknown 'tier' value '{tier}'")

    # The installer's own words. Packaging an internal-tier plugin is not a warning to be
    # overridden: its binary could be swapped for another without the loader ever
    # re-checking it against the manifest that granted it trust.
    if tier == "internal":
        _fail(
            "tier internal cannot be packaged (dev-loop only); "
            "use tier sdk for a distributable binary plugin"
        )

    if tier != "qml" and not isinstance(raw.get("apiVersion"), int):
        _fail(f"{MANIFEST_FILENAME}: missing or non-numeric required field 'apiVersion'")

    host_version = raw.get("hostVersion")
    if not isinstance(host_version, dict):
        _fail(f"{MANIFEST_FILENAME}: missing or non-object required field 'hostVersion'")
    minimum = host_version.get("min")
    if not isinstance(minimum, str) or not _VERSION_RE.match(minimum):
        _fail(f"{MANIFEST_FILENAME}: 'hostVersion.min' must be a version string")

    return raw


# --- Entry collection ----------------------------------------------------------------


def collect_entries(package_dir: Path) -> list[Entry]:
    """Every file to pack, sorted by archive name so the output is order-stable."""
    entries: list[Entry] = []
    for path in sorted(package_dir.rglob("*")):
        relative = path.relative_to(package_dir)
        if any(part in EXCLUDED_NAMES for part in relative.parts):
            continue
        # A symlink is followed by zipfile.write(), silently embedding whatever it points
        # at — possibly from outside the package. The installer cannot see through an entry
        # to know that happened, so refuse rather than pack something the author did not
        # mean to ship.
        if path.is_symlink():
            _fail(f"'{relative}' is a symlink; packages must contain regular files only")
        if not path.is_file():
            continue
        stats = path.stat()
        entries.append(
            Entry(
                source=path,
                arcname=relative.as_posix(),
                size=stats.st_size,
                mode=stat.S_IMODE(stats.st_mode),
            )
        )
    return entries


def find_binaries(entries: Iterable[Entry]) -> list[str]:
    """Archive names the loader would treat as this package's plugin binary.

    Mirrors QGCPluginLoader::findPackageBinaries(): only files directly inside a
    bin/<subdir>/ are candidates, which is why a .dylib shipped under qml/ or assets/ is
    not one — and why moving a binary there is not a way around the tier-qml rule.
    """
    found: list[str] = []
    for entry in entries:
        parts = entry.arcname.split("/")
        if len(parts) == 3 and parts[0] == "bin" and entry.source.suffix in BINARY_SUFFIXES:
            found.append(entry.arcname)
    return found


# --- The installer's rules, applied at pack time --------------------------------------


def check_no_bundled_runtime(entries: Iterable[Entry]) -> None:
    """PluginInstaller::findBundledRuntimeEntry.

    A package's manifest and binary are independently trusted — nothing re-validates one
    against the other at load time — so shipping a runtime would let installed content run
    a library the loader never checked.
    """
    for entry in entries:
        for part in entry.arcname.split("/"):
            lowered = part.lower()
            bundles_api = lowered.startswith("libqgcpluginapi") and lowered.endswith(".dylib")
            bundles_qt = lowered.startswith("qt") and lowered.endswith((".framework", ".dylib"))
            if bundles_api or bundles_qt:
                _fail(
                    f"'{entry.arcname}' bundles a runtime library; plugins must link the "
                    "host's QGCPluginAPI/Qt, not ship their own"
                )


def check_size(entries: Iterable[Entry]) -> None:
    total = sum(entry.size for entry in entries)
    if total > MAX_PACKAGE_BYTES:
        _fail(
            f"package contents total {total / 1024 / 1024:.1f} MB, over the installer's "
            f"{MAX_PACKAGE_BYTES // 1024 // 1024} MB extraction ceiling"
        )


def check_tier_layout(tier: str, manifest: dict[str, object], entries: list[Entry]) -> None:
    """QGCPluginLoader::inspectPackage()'s tier-specific layout rules."""
    binaries = find_binaries(entries)

    if tier == "qml":
        if binaries:
            _fail(f"qml-tier package must not ship a binary (found {binaries[0]})")
        contributes = manifest.get("contributes")
        if isinstance(contributes, dict):
            for key in ("replay", "telemetryLogging"):
                if contributes.get(key):
                    _fail(f"qml-tier package cannot declare '{key}' (no binary to implement it)")
        return

    # Tier sdk. The loader resolves exactly one binary or refuses to load the package;
    # both failure modes are silent until install, so both are errors here.
    if not binaries:
        keys = ", ".join(f"bin/{key}/" for key in PLATFORM_KEYS)
        _fail(f"no plugin binary found; tier sdk needs exactly one under a platform dir ({keys})")
    if len(binaries) > 1:
        _fail(
            f"multiple candidate binaries found ({', '.join(binaries)}); expected exactly one. "
            "A package holds one platform's binary — build a separate package per platform."
        )


# --- Packing --------------------------------------------------------------------------


def stage_binary(entries: list[Entry], binary: Path, platform_key: str) -> list[Entry]:
    """Add --binary as bin/<platform_key>/<name> without the author laying the tree out."""
    if not binary.is_file():
        _fail(f"--binary {binary} does not exist")
    arcname = f"bin/{platform_key}/{binary.name}"
    if any(entry.arcname == arcname for entry in entries):
        _fail(f"--binary would overwrite '{arcname}', which the package directory already has")
    stats = binary.stat()
    staged = [
        *entries,
        Entry(source=binary, arcname=arcname, size=stats.st_size, mode=stat.S_IMODE(stats.st_mode)),
    ]
    return sorted(staged, key=lambda entry: entry.arcname)


def write_package(entries: Iterable[Entry], output: Path) -> None:
    """Write the zip, preserving each file's mode.

    ZipFile.write() drops the executable bit on some platforms, and a plugin binary that
    arrives non-executable is a confusing dlopen failure rather than a legible one — so
    every entry's mode is set explicitly through external_attr.

    Building ZipInfo by name rather than from_file() also leaves every entry on zip's 1980
    epoch. That is kept, not worked around: with entries already sorted by name, it makes
    two packs of unchanged content byte-identical, so a package's checksum means something.
    """
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for entry in entries:
            info = zipfile.ZipInfo(entry.arcname)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (entry.mode & 0xFFFF) << 16
            archive.writestr(info, entry.source.read_bytes())


def build(args: argparse.Namespace) -> int:
    package_dir: Path = args.package_dir.resolve()
    if not package_dir.is_dir():
        _fail(f"{package_dir} is not a directory")

    manifest = load_manifest(package_dir)
    tier = str(manifest["tier"])

    entries = collect_entries(package_dir)
    if args.binary is not None:
        if tier == "qml":
            _fail("--binary is meaningless for a qml-tier package, which ships no binary")
        entries = stage_binary(entries, args.binary.resolve(), args.platform)

    check_no_bundled_runtime(entries)
    check_size(entries)
    check_tier_layout(tier, manifest, entries)

    output: Path = args.output or Path(f"{manifest['id']}-{manifest['version']}.qgcplugin")
    if output.exists() and not args.force:
        _fail(f"{output} already exists; pass --force to overwrite")

    if args.dry_run:
        print(f"{output} would contain {len(entries)} file(s):")
        for entry in entries:
            print(f"  {entry.arcname}  ({entry.size} bytes)")
        return 0

    write_package(entries, output)
    total = sum(entry.size for entry in entries)
    print(f"Wrote {output} — {len(entries)} file(s), {total / 1024:.1f} KiB uncompressed")
    print(f"  id      {manifest['id']}")
    print(f"  version {manifest['version']}")
    print(f"  tier    {tier}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Pack a QGroundControl plugin package directory into a .qgcplugin zip.",
        epilog=(
            "The package directory must hold qgcplugin.json at its root; its contents are "
            "packed at the archive root, which is the layout PluginInstaller expects."
        ),
    )
    parser.add_argument("package_dir", type=Path, help=f"directory holding {MANIFEST_FILENAME}")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="output path (default: <id>-<version>.qgcplugin in the current directory)",
    )
    parser.add_argument(
        "--binary",
        type=Path,
        help="plugin binary to place at bin/<platform>/, for a package dir that has no bin/ tree",
    )
    parser.add_argument(
        "--platform",
        default=PLATFORM_KEYS[0],
        help=f"platform key for --binary (default: %(default)s; known: {', '.join(PLATFORM_KEYS)})",
    )
    parser.add_argument("--force", action="store_true", help="overwrite an existing output file")
    parser.add_argument("--dry-run", action="store_true", help="list what would be packed and exit")
    args = parser.parse_args(argv)

    # A key outside the known set still resolves through the loader's bin/<prefix>-*
    # fallback, so this is a warning rather than a rejection — a single-arch
    # bin/macos-x86_64/ is a legitimate layout the loader documents.
    if args.binary is not None and args.platform not in PLATFORM_KEYS:
        print(
            f"warning: '{args.platform}' is not a documented platform key "
            f"({', '.join(PLATFORM_KEYS)}); the loader will find it only via its "
            "bin/<platform>-* fallback",
            file=sys.stderr,
        )

    try:
        return build(args)
    except PackError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
