#!/usr/bin/env python3
"""Check the catalog entries in a pull request before a maintainer reviews them.

Every check here runs on content a stranger wrote, so the script trusts nothing in an entry
until a check has passed. The order matters: the schema runs first, the URL rule runs before
any download, and a package is opened only after its size and hash match the entry.

Checks that need no network run on every entry. Downloads run only for versions the base
branch does not have yet: a version already on the base branch passed these checks when it
was added, and the history check stops anyone changing it afterwards. The check that a
repository is public runs only for an entry the pull request adds or changes, so an entry
nobody touched never fails on a network error.

An entry with `repository` claims open source. Its license must be an OSI-approved SPDX id
from tools/vendor/osi-licenses.json, a pinned snapshot of the SPDX license list. A closed-source
entry leaves out `repository` and names `releaseRepository`, a public repository that holds
only the release packages.

The package rules come from tools/vendor/pack_plugin.py, a pinned copy of the plugin SDK's
tools/pack_plugin.py (QGroundControl fork, commit cd6d7b0bdcb6df144629015b4c0918963080ab97).
Copy it again byte for byte when the SDK's rules change.

Usage:
    python3 tools/validate_entry.py <plugins-dir> [--base <base-plugins-dir>]
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import io
import json
import re
import stat
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO
from urllib.parse import unquote, urlsplit

from jsonschema import Draft202012Validator
from vendor import pack_plugin

ROOT = Path(__file__).resolve().parent.parent
ENTRY_SCHEMA = json.loads((ROOT / "schema" / "entry.schema.json").read_text())
OSI_LICENSES = frozenset(
    json.loads((ROOT / "tools" / "vendor" / "osi-licenses.json").read_text())["ids"]
)

GITHUB_API_REPOS = "https://api.github.com/repos/"

# The largest package the catalog accepts, compressed. A QDrive release binary is about 3 MB
# per architecture, so this leaves room for growth while keeping CI downloads short.
MAX_PACKAGE_BYTES = 50 * 1024 * 1024

# qgcplugin.json is a small text file. A bigger one is a mistake or a zip bomb.
MAX_MANIFEST_BYTES = 1024 * 1024

DOWNLOAD_TIMEOUT_SECONDS = 60
DOWNLOAD_CHUNK_BYTES = 64 * 1024

# QVersionNumber stores each segment as an int, so a segment is limited to 9 digits.
_PLAIN_VERSION_RE = re.compile(r"^[0-9]{1,9}(\.[0-9]{1,9})*$")


class DownloadError(Exception):
    """A package could not be fetched."""


# fetch(url, limit) returns the body, reading at most limit + 1 bytes. The extra byte tells
# the caller that the body is longer than the limit.
Fetch = Callable[[str, int], bytes]

# repo_check(url) returns None when the repository is public, or the reason it is not.
RepoCheck = Callable[[str], str | None]


# --- Versions -------------------------------------------------------------------------


def version_key(text: object) -> tuple[int, ...] | None:
    """The version as QGC's QVersionNumber sees it, or None if QGC cannot parse it.

    QVersionNumber compares integer segments, so "1.01" equals "1.1". It keeps trailing
    zeros, so "1.0" and "1.0.0" are different versions.
    """
    if not isinstance(text, str) or not _PLAIN_VERSION_RE.match(text):
        return None
    return tuple(int(part) for part in text.split("."))


def _optional_version_key(text: object) -> tuple[int, ...] | None:
    """An absent or empty hostVersion.max means "no upper bound"."""
    if text is None or text == "":
        return None
    return version_key(text)


# --- Checks that need no network ------------------------------------------------------


def schema_errors(entry: object) -> list[str]:
    validator = Draft202012Validator(ENTRY_SCHEMA)
    errors: list[str] = []
    for error in validator.iter_errors(entry):
        if error.validator == "anyOf" and not error.path:
            # The stock message for this rule repeats the whole entry.
            message = "an entry needs 'repository' or 'releaseRepository', or both"
        else:
            message = error.message
        errors.append(f"{error.json_path}: {message}")
    return errors


def license_errors(entry: dict) -> list[str]:
    """An entry with `repository` claims open source, so its license must be OSI-approved.

    The id must be in the pinned list exactly. A compound expression such as "MIT OR
    Apache-2.0" is refused in v1, and so is a deprecated id such as "GPL-3.0".
    """
    if not entry.get("repository"):
        return []
    license_id = entry["license"]
    if license_id in OSI_LICENSES:
        return []
    if license_id != license_id.strip():
        hint = "; it has leading or trailing whitespace"
    elif len(license_id.split()) > 1:
        hint = "; a compound expression is not accepted in v1"
    else:
        hint = ""
    return [
        f"license '{license_id}' is not an OSI-approved SPDX id{hint}. An entry with "
        "'repository' claims open source. Use an id from tools/vendor/osi-licenses.json, "
        "or leave out 'repository' and list the plugin as closed source"
    ]


def release_source(entry: dict) -> str:
    """The repository whose release assets hold the packages."""
    return entry.get("releaseRepository") or entry["repository"]


def source_errors(entry: dict) -> list[str]:
    """Every package URL, in every version, must be a release asset of the release source.

    This needs no network, so it runs on every entry. Without it, an entry could change
    `releaseRepository` and leave its released packages pointing at the old repository.
    """
    errors: list[str] = []
    source = release_source(entry)
    for version in entry["versions"]:
        for key, package in sorted(version["packages"].items()):
            where = f"version '{version['version']}' package '{key}'"
            errors.extend(
                f"{where}: {error}" for error in package_url_errors(package["url"], source)
            )
    return errors


def offline_errors(file_name: str, entry: dict) -> list[str]:
    """The checks on one schema-valid entry that need no network and no base branch."""
    errors: list[str] = []
    if file_name != f"{entry['id']}.json":
        errors.append(f"the file name must be {entry['id']}.json")
    errors.extend(version_errors(entry))
    errors.extend(license_errors(entry))
    errors.extend(source_errors(entry))
    return errors


def version_errors(entry: dict) -> list[str]:
    """QGC refuses the whole catalog when one entry repeats a version or has one it cannot
    parse. The schema allows a segment of any length; QGC does not."""
    errors: list[str] = []
    seen: dict[tuple[int, ...], str] = {}
    for index, version in enumerate(entry["versions"]):
        host = version["hostVersion"]
        for field, value in (
            ("version", version["version"]),
            ("hostVersion.min", host["min"]),
            ("hostVersion.max", host.get("max") or "0"),
        ):
            if version_key(value) is None:
                errors.append(f"versions[{index}]: {field} '{value}' has a segment over 9 digits")
        text = version["version"]
        key = version_key(text)
        if key is None:
            continue
        if key in seen:
            errors.append(f"versions[{index}]: version '{text}' repeats version '{seen[key]}'")
        else:
            seen[key] = text
    return errors


def duplicate_id_errors(entries: dict[str, dict]) -> list[str]:
    """QGC refuses the whole catalog when two entries share an id.

    The comparison ignores case, which is stricter than QGC. Two ids that differ only in
    case would install into the same directory on macOS and Windows.
    """
    errors: list[str] = []
    seen: dict[str, str] = {}
    for file_name, entry in sorted(entries.items()):
        key = str(entry["id"]).casefold()
        if key in seen:
            errors.append(f"{file_name}: id '{entry['id']}' is already used by {seen[key]}")
        else:
            seen[key] = file_name
    return errors


def history_errors(old: dict, new: dict) -> list[str]:
    """A released version never changes or disappears, so its hash never changes under a user."""
    errors: list[str] = []
    new_versions = {version_key(v.get("version")): v for v in new.get("versions", [])}
    for old_version in old.get("versions", []):
        text = old_version.get("version")
        current = new_versions.get(version_key(text))
        if current is None:
            errors.append(f"version '{text}' was removed; released versions cannot be removed")
        elif current != old_version:
            errors.append(
                f"version '{text}' was changed; released versions are frozen, "
                "so add a new version instead"
            )
    return errors


def added_versions(old: dict | None, new: dict) -> list[dict]:
    if old is None:
        return list(new["versions"])
    old_keys = {version_key(v.get("version")) for v in old.get("versions", [])}
    return [v for v in new["versions"] if version_key(v["version"]) not in old_keys]


def package_url_errors(url: str, repository: str) -> list[str]:
    """The package must be a release asset of the entry's release repository on github.com.

    The release repository is `releaseRepository` when the entry has one, else `repository`.
    This runs before any download. It limits CI to fetching from GitHub, from the repository
    the reviewer checked.
    """
    parts = urlsplit(url)
    if parts.scheme != "https":
        return [f"'{url}' must use https"]
    # netloc also holds any user, password or port, so this refuses those too.
    if parts.netloc != "github.com":
        return [f"'{url}' must be on github.com with no user, password or port"]
    if parts.query or parts.fragment:
        return [f"'{url}' must not have a query or a fragment"]

    segments = unquote(parts.path).split("/")[1:]
    if any(segment in ("", ".", "..") or "\\" in segment for segment in segments):
        return [f"'{url}' has an empty, '.' or '..' path segment"]

    owner_repo = urlsplit(repository).path.strip("/").lower().split("/")
    if (
        len(segments) < 6
        or [segment.lower() for segment in segments[:2]] != owner_repo
        or segments[2:4] != ["releases", "download"]
    ):
        return [
            f"'{url}' must be a release asset of {repository}: "
            f"{repository}/releases/download/<tag>/<asset>"
        ]
    return []


# --- Downloading ----------------------------------------------------------------------


class _HttpsOnlyRedirect(urllib.request.HTTPRedirectHandler):
    """GitHub redirects a release download to its file host. Every hop must stay on HTTPS."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlsplit(newurl).scheme != "https":
            raise DownloadError(f"redirect to a non-HTTPS URL: {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_HttpsOnlyRedirect)


def read_capped(stream: BinaryIO, limit: int) -> bytes:
    """Read at most limit + 1 bytes, so a body that is too long is never read in full."""
    buffer = bytearray()
    while len(buffer) <= limit:
        chunk = stream.read(min(DOWNLOAD_CHUNK_BYTES, limit + 1 - len(buffer)))
        if not chunk:
            break
        buffer.extend(chunk)
    return bytes(buffer)


def download(url: str, limit: int) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "qgc-plugin-catalog-validator"})
    try:
        with _OPENER.open(request, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
            return read_capped(response, limit)
    except (OSError, http.client.HTTPException) as exc:
        raise DownloadError(f"download of '{url}' failed: {exc}") from exc


# --- The public-repository check ------------------------------------------------------

# GitHub answers an API call as (status, lower-case headers, body).
ApiReply = tuple[int, dict[str, str], bytes]
ApiGet = Callable[[str], ApiReply]

_MAX_API_BODY_BYTES = 1024 * 1024


def api_get(url: str) -> ApiReply:
    """Call the GitHub API with no login. An HTTP error status is a reply, not an exception."""
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "qgc-plugin-catalog-validator",
            "Accept": "application/vnd.github+json",
        },
    )
    try:
        with _OPENER.open(request, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
            headers = {key.lower(): value for key, value in response.headers.items()}
            return response.status, headers, read_capped(response, _MAX_API_BODY_BYTES)
    except urllib.error.HTTPError as exc:
        headers = {key.lower(): value for key, value in exc.headers.items()}
        return exc.code, headers, read_capped(exc, _MAX_API_BODY_BYTES)
    except (OSError, http.client.HTTPException) as exc:
        raise DownloadError(f"request to '{url}' failed: {exc}") from exc


def _is_rate_limited(status: int, headers: dict[str, str], body: bytes) -> bool:
    if status == 429:
        return True
    return status == 403 and (
        headers.get("x-ratelimit-remaining") == "0"
        or "retry-after" in headers
        or b"rate limit" in body.lower()
    )


def github_repo_problem(repository: str, get: ApiGet = api_get) -> str | None:
    """None when the repository is public, or the reason the check failed.

    The call has no login, so GitHub answers 404 for a private repository exactly as for a
    missing one, and both fail. The limit is 60 calls an hour for one IP address, and the
    runners share addresses. A limit reply must say "re-run", never "private", so a
    rate-limited run is not mistaken for a private repository. Any reply this check does not
    understand fails too: a check that cannot run never passes.
    """
    owner_repo = urlsplit(repository).path.strip("/")
    try:
        status, headers, body = get(GITHUB_API_REPOS + owner_repo)
    except DownloadError as exc:
        return f"could not check that '{repository}' is public ({exc}); re-run the job"
    if _is_rate_limited(status, headers, body):
        return f"GitHub's rate limit stopped the public check for '{repository}'; re-run the job"
    if status == 404:
        return f"'{repository}' is private or does not exist"
    if status != 200:
        return (
            f"could not check that '{repository}' is public (GitHub answered HTTP {status}); "
            "re-run the job"
        )
    try:
        private = json.loads(body)["private"]
    except (ValueError, KeyError, TypeError):
        return f"could not read GitHub's answer for '{repository}'; re-run the job"
    if private is not False:
        return f"'{repository}' is private"
    return None


# --- Checks on a downloaded package ---------------------------------------------------


def _manifest_mismatches(manifest: dict, entry: dict, version: dict) -> list[str]:
    """The zip must describe the same plugin, release and host range as the entry."""
    manifest_host = manifest.get("hostVersion") or {}
    entry_host = version["hostVersion"]
    manifest_version = version_key(manifest.get("version"))
    if manifest_version is None:
        return [f"qgcplugin.json: 'version' {manifest.get('version')!r} is not plain numbers"]
    manifest_max = manifest_host.get("max")
    if manifest_max not in (None, "") and version_key(manifest_max) is None:
        return [f"qgcplugin.json: 'hostVersion.max' {manifest_max!r} is not plain numbers"]
    # QGC reads these as JSON numbers, so a JSON true is not 1 there.
    for field in ("apiVersion", "qmlApiVersion"):
        value = manifest.get(field)
        if value is not None and type(value) is not int:
            return [f"qgcplugin.json: '{field}' {value!r} is not an integer"]

    pairs = [
        ("id", manifest.get("id"), entry["id"]),
        ("version", manifest_version, version_key(version["version"])),
        ("tier", manifest.get("tier"), version["tier"]),
        ("apiVersion", manifest.get("apiVersion"), version.get("apiVersion")),
        ("qmlApiVersion", manifest.get("qmlApiVersion"), version.get("qmlApiVersion")),
        (
            "hostVersion.min",
            version_key(manifest_host.get("min")),
            version_key(entry_host["min"]),
        ),
        (
            "hostVersion.max",
            _optional_version_key(manifest_host.get("max")),
            _optional_version_key(entry_host.get("max")),
        ),
    ]
    errors: list[str] = []
    for field, from_manifest, from_entry in pairs:
        if from_manifest != from_entry:
            errors.append(
                f"qgcplugin.json: '{field}' does not match the entry "
                f"(zip {from_manifest!r}, entry {from_entry!r})"
            )
    return errors


def archive_errors(data: bytes, entry: dict, version: dict) -> list[str]:
    """Open the package without extracting it. Only qgcplugin.json is decompressed."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        return [f"the package is not a zip file: {exc}"]

    with archive:
        infos = archive.infolist()
        counts = Counter(info.filename for info in infos)
        duplicates = sorted(name for name, count in counts.items() if count > 1)
        if duplicates:
            # QGC refuses a zip that repeats a name, and two copies of qgcplugin.json would
            # let this script read a different manifest from the one QGC reads.
            return [f"the zip holds '{duplicates[0]}' more than once"]
        for info in infos:
            name = info.filename
            parts = re.split(r"[/\\]", name)
            if name.startswith(("/", "\\")) or ".." in parts or ":" in parts[0]:
                return [f"the zip entry '{name}' points outside the package"]
            if stat.S_ISLNK(info.external_attr >> 16):
                return [f"the zip entry '{name}' is a symlink; packages hold regular files only"]

        try:
            manifest_info = archive.getinfo(pack_plugin.MANIFEST_FILENAME)
        except KeyError:
            return [f"the package has no {pack_plugin.MANIFEST_FILENAME} at its root"]
        if manifest_info.file_size > MAX_MANIFEST_BYTES:
            return [f"{pack_plugin.MANIFEST_FILENAME} is over {MAX_MANIFEST_BYTES} bytes"]
        # Read one byte past the cap: the size in the zip header can lie.
        with archive.open(manifest_info) as stream:
            manifest_bytes = stream.read(MAX_MANIFEST_BYTES + 1)
        if len(manifest_bytes) > MAX_MANIFEST_BYTES:
            return [f"{pack_plugin.MANIFEST_FILENAME} is over {MAX_MANIFEST_BYTES} bytes"]

    with tempfile.TemporaryDirectory() as temp_dir:
        (Path(temp_dir) / pack_plugin.MANIFEST_FILENAME).write_bytes(manifest_bytes)
        try:
            manifest = pack_plugin.load_manifest(Path(temp_dir))
        except pack_plugin.PackError as exc:
            return [str(exc)]

    errors = _manifest_mismatches(manifest, entry, version)

    # pack_plugin's rules take the file list and the uncompressed sizes, which the zip
    # directory gives without decompressing anything.
    files = [
        pack_plugin.Entry(
            source=Path(info.filename),
            arcname=info.filename,
            size=info.file_size,
            mode=(info.external_attr >> 16) & 0o7777,
        )
        for info in infos
        if not info.is_dir()
    ]
    try:
        pack_plugin.check_no_bundled_runtime(files)
        pack_plugin.check_size(files)
        pack_plugin.check_tier_layout(str(manifest["tier"]), manifest, files)
    except pack_plugin.PackError as exc:
        errors.append(str(exc))
    return errors


def package_errors(package: dict, entry: dict, version: dict, fetch: Fetch) -> list[str]:
    url = package["url"]
    errors = package_url_errors(url, release_source(entry))
    if errors:
        return errors

    declared_size = package["size"]
    if declared_size > MAX_PACKAGE_BYTES:
        return [f"size {declared_size} is over the catalog's cap of {MAX_PACKAGE_BYTES} bytes"]

    try:
        data = fetch(url, declared_size)
    except DownloadError as exc:
        return [str(exc)]
    if len(data) > declared_size:
        return [f"the package at '{url}' is larger than its declared size {declared_size}"]
    if len(data) != declared_size:
        return [f"the package at '{url}' is {len(data)} bytes, not its declared {declared_size}"]

    digest = hashlib.sha256(data).hexdigest()
    if digest != package["sha256"]:
        return [f"the package at '{url}' has SHA-256 {digest}, not {package['sha256']}"]

    return archive_errors(data, entry, version)


# --- The whole pull request -----------------------------------------------------------


def _load_dir(plugins_dir: Path) -> tuple[dict[str, object], list[str]]:
    """Every entry file by name, plus errors for files that are not entries."""
    loaded: dict[str, object] = {}
    errors: list[str] = []
    for path in sorted(plugins_dir.iterdir()):
        if path.name == ".gitkeep":
            continue
        if not path.is_file() or path.suffix != ".json":
            errors.append(f"{path.name}: plugins/ holds only <id>.json files")
            continue
        try:
            loaded[path.name] = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            errors.append(f"{path.name}: not valid JSON: {exc}")
    return loaded, errors


def repository_errors(entry: dict, repo_check: RepoCheck) -> list[str]:
    """Each repository the entry names must be public. One call per distinct repository."""
    errors: list[str] = []
    checked: set[str] = set()
    for field in ("repository", "releaseRepository"):
        url = entry.get(field)
        if url is None or url.lower() in checked:
            continue
        checked.add(url.lower())
        problem = repo_check(url)
        if problem is not None:
            errors.append(f"{field}: {problem}")
    return errors


def validate(
    plugins_dir: Path, base_dir: Path | None, fetch: Fetch, repo_check: RepoCheck
) -> list[str]:
    """Every problem with the entries in plugins_dir, compared with base_dir."""
    entries, errors = _load_dir(plugins_dir)
    base_entries: dict[str, object] = {}
    if base_dir is not None:
        base_entries, _ = _load_dir(base_dir)

    for file_name in sorted(base_entries.keys() - entries.keys()):
        errors.append(f"{file_name}: the entry was removed; released versions cannot be removed")

    valid: dict[str, dict] = {}
    for file_name, entry in entries.items():
        file_errors = schema_errors(entry)
        if file_errors:
            errors.extend(f"{file_name}: {error}" for error in file_errors)
            continue
        assert isinstance(entry, dict)
        valid[file_name] = entry

        errors.extend(f"{file_name}: {error}" for error in offline_errors(file_name, entry))

        old = base_entries.get(file_name)
        old = old if isinstance(old, dict) else None
        if old is not None:
            errors.extend(f"{file_name}: {error}" for error in history_errors(old, entry))
        if old != entry:
            errors.extend(f"{file_name}: {error}" for error in repository_errors(entry, repo_check))

        for version in added_versions(old, entry):
            for key, package in sorted(version["packages"].items()):
                where = f"{file_name}: version '{version['version']}' package '{key}'"
                for error in package_errors(package, entry, version, fetch):
                    errors.append(f"{where}: {error}")

    errors.extend(duplicate_id_errors(valid))
    # A package URL on an added version is refused by source_errors and again by package_errors,
    # with the same text. Report it once.
    return list(dict.fromkeys(errors))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check the catalog entries in a pull request.")
    parser.add_argument("plugins_dir", type=Path, help="the pull request's plugins/ directory")
    parser.add_argument(
        "--base",
        type=Path,
        help="the base branch's plugins/ directory; versions in it are not downloaded again",
    )
    args = parser.parse_args(argv)

    for directory in (args.plugins_dir, args.base):
        if directory is not None and not directory.is_dir():
            print(f"error: {directory} is not a directory", file=sys.stderr)
            return 1

    errors = validate(args.plugins_dir, args.base, download, github_repo_problem)
    for error in errors:
        print(f"error: {error}", file=sys.stderr)
    if errors:
        return 1
    print(f"All entries in {args.plugins_dir} passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
