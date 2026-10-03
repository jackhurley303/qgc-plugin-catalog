import copy
import hashlib
import io
import json
import stat
import urllib.request
import zipfile
from pathlib import Path

import pytest
import validate_entry
from validate_entry import DownloadError

FIXTURES = Path(__file__).resolve().parent / "fixtures"
RELEASES = "https://github.com/example-author/hello-qml/releases/download/v1.0.0"
SDK_RELEASES = "https://github.com/example-author/hello-sdk/releases/download/v2.1"


def _good(name: str) -> dict:
    return json.loads((FIXTURES / f"good-{name}.json").read_text())


def _qml_manifest() -> dict:
    return {
        "id": "org.example.hello-qml",
        "name": "Hello QML",
        "vendor": "Example Author",
        "version": "1.0.0",
        "tier": "qml",
        "qmlApiVersion": 1,
        "hostVersion": {"min": "5.0", "max": ""},
    }


def _sdk_manifest() -> dict:
    return {
        "id": "org.example.hello-sdk",
        "name": "Hello SDK",
        "vendor": "Example Author",
        "version": "2.1",
        "tier": "sdk",
        "apiVersion": 2,
        "hostVersion": {"min": "5.0.0", "max": "6.0"},
    }


def _zip(manifest: dict | None, files: dict[str, bytes] | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        if manifest is not None:
            archive.writestr("qgcplugin.json", json.dumps(manifest))
        for name, content in (files or {}).items():
            archive.writestr(name, content)
    return buffer.getvalue()


def _qml_zip(manifest: dict | None = None, files: dict[str, bytes] | None = None) -> bytes:
    return _zip(manifest or _qml_manifest(), files or {"qml/Main.qml": b"Item {}"})


def _sdk_zip(platform: str) -> bytes:
    return _zip(_sdk_manifest(), {f"bin/{platform}/libhello.dylib": b"\xcf\xfa\xed\xfe"})


class FakeFetch:
    """Serves package bytes by URL and records each download."""

    def __init__(self) -> None:
        self.bodies: dict[str, bytes] = {}
        self.calls: list[str] = []

    def __call__(self, url: str, limit: int) -> bytes:
        self.calls.append(url)
        if url not in self.bodies:
            raise DownloadError(f"download of '{url}' failed: HTTP Error 404: Not Found")
        return self.bodies[url][: limit + 1]

    def serve(self, package: dict, data: bytes) -> None:
        """Point package at data, with a matching size and hash."""
        self.bodies[package["url"]] = data
        package["size"] = len(data)
        package["sha256"] = hashlib.sha256(data).hexdigest()


def _qml_entry(fetch: FakeFetch, data: bytes | None = None) -> dict:
    entry = _good("qml")
    fetch.serve(entry["versions"][0]["packages"]["any"], data or _qml_zip())
    return entry


def _write(directory: Path, *entries: dict, names: list[str] | None = None) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / ".gitkeep").write_text("")
    for index, entry in enumerate(entries):
        name = names[index] if names else f"{entry['id']}.json"
        (directory / name).write_text(json.dumps(entry, indent=2))
    return directory


def _run(tmp_path: Path, entry: dict, fetch: FakeFetch, base: dict | None = None) -> str:
    plugins = _write(tmp_path / "head", entry)
    base_dir = _write(tmp_path / "base", *([base] if base else []))
    return "\n".join(validate_entry.validate(plugins, base_dir, fetch))


def _package(entry: dict) -> dict:
    return next(iter(entry["versions"][0]["packages"].values()))


# --- A good entry passes ----------------------------------------------------------------


def test_good_qml_entry_passes(tmp_path):
    fetch = FakeFetch()
    entry = _qml_entry(fetch)
    assert _run(tmp_path, entry, fetch) == ""
    assert fetch.calls == [_package(entry)["url"]]


def test_good_sdk_entry_with_two_platforms_passes(tmp_path):
    fetch = FakeFetch()
    entry = _good("sdk")
    packages = entry["versions"][0]["packages"]
    fetch.serve(packages["macos-universal"], _sdk_zip("macos-universal"))
    fetch.serve(packages["windows-x64"], _sdk_zip("windows-x64"))
    assert _run(tmp_path, entry, fetch) == ""
    assert len(fetch.calls) == 2


def test_empty_catalog_passes(tmp_path):
    plugins = _write(tmp_path / "head")
    assert validate_entry.validate(plugins, None, FakeFetch()) == []


def test_version_already_on_base_is_not_downloaded(tmp_path):
    fetch = FakeFetch()
    entry = _qml_entry(fetch)
    fetch.bodies.clear()
    assert _run(tmp_path, entry, fetch, base=copy.deepcopy(entry)) == ""
    assert fetch.calls == []


def test_only_the_added_version_is_downloaded(tmp_path):
    fetch = FakeFetch()
    base = _qml_entry(fetch)
    entry = copy.deepcopy(base)
    added = copy.deepcopy(entry["versions"][0])
    added["version"] = "1.1.0"
    added["packages"]["any"]["url"] = f"{RELEASES}/hello-qml-1.1.0.zip"
    manifest = _qml_manifest()
    manifest["version"] = "1.1.0"
    fetch.serve(added["packages"]["any"], _qml_zip(manifest))
    entry["versions"].append(added)
    assert _run(tmp_path, entry, fetch, base=base) == ""
    assert fetch.calls == [added["packages"]["any"]["url"]]


def test_entry_level_fields_may_change(tmp_path):
    fetch = FakeFetch()
    base = _qml_entry(fetch)
    entry = copy.deepcopy(base)
    entry["description"] = "A better description."
    assert _run(tmp_path, entry, fetch, base=base) == ""


def test_repository_owner_case_is_ignored(tmp_path):
    fetch = FakeFetch()
    entry = _good("qml")
    package = entry["versions"][0]["packages"]["any"]
    package["url"] = package["url"].replace("example-author", "Example-Author")
    fetch.serve(package, _qml_zip())
    assert _run(tmp_path, entry, fetch) == ""


# --- Package refusals -------------------------------------------------------------------


def test_wrong_hash_is_refused(tmp_path):
    fetch = FakeFetch()
    entry = _qml_entry(fetch)
    _package(entry)["sha256"] = "0" * 64
    assert "has SHA-256" in _run(tmp_path, entry, fetch)


def test_package_smaller_than_declared_is_refused(tmp_path):
    fetch = FakeFetch()
    entry = _qml_entry(fetch)
    _package(entry)["size"] += 10
    assert "not its declared" in _run(tmp_path, entry, fetch)


def test_package_larger_than_declared_is_refused(tmp_path):
    fetch = FakeFetch()
    entry = _qml_entry(fetch)
    _package(entry)["size"] -= 10
    assert "larger than its declared size" in _run(tmp_path, entry, fetch)


def test_size_over_the_cap_is_refused_without_a_download(tmp_path):
    fetch = FakeFetch()
    entry = _qml_entry(fetch)
    _package(entry)["size"] = validate_entry.MAX_PACKAGE_BYTES + 1
    assert "over the catalog's cap" in _run(tmp_path, entry, fetch)
    assert fetch.calls == []


def test_failed_download_is_refused(tmp_path):
    fetch = FakeFetch()
    entry = _qml_entry(fetch)
    fetch.bodies.clear()
    assert "404" in _run(tmp_path, entry, fetch)


def _url_errors(url: str) -> str:
    return "\n".join(
        validate_entry.package_url_errors(url, "https://github.com/example-author/hello-qml")
    )


URL_REFUSALS = [
    pytest.param(
        "https://github.com/other-author/hello-qml/releases/download/v1/a.zip",
        "must be a release asset of",
        id="other-owner",
    ),
    pytest.param(
        "https://github.com/example-author/other-repo/releases/download/v1/a.zip",
        "must be a release asset of",
        id="other-repo",
    ),
    pytest.param(
        "http://github.com/example-author/hello-qml/releases/download/v1/a.zip",
        "must use https",
        id="http",
    ),
    pytest.param("https://example.org/hello-qml.zip", "must be on github.com", id="other-host"),
    pytest.param(
        "https://github.com.evil.example/example-author/hello-qml/releases/download/v1/a.zip",
        "must be on github.com",
        id="lookalike-host",
    ),
    pytest.param(
        "https://user@github.com/example-author/hello-qml/releases/download/v1/a.zip",
        "must be on github.com",
        id="userinfo",
    ),
    pytest.param(
        "https://github.com:8443/example-author/hello-qml/releases/download/v1/a.zip",
        "must be on github.com",
        id="port",
    ),
    pytest.param(
        "https://github.com/example-author/hello-qml/releases/download/v1/a.zip?x=1",
        "query or a fragment",
        id="query",
    ),
    pytest.param(
        "https://github.com/example-author/hello-qml/releases/download/../../../other/x/a.zip",
        "'..' path segment",
        id="dot-dot",
    ),
    pytest.param(
        "https://github.com/example-author/hello-qml/releases/download/%2e%2e/a.zip",
        "'..' path segment",
        id="encoded-dot-dot",
    ),
    pytest.param(
        "https://github.com/example-author/hello-qml/archive/refs/tags/v1.zip",
        "must be a release asset of",
        id="source-archive",
    ),
    pytest.param(
        "https://github.com/example-author/hello-qml/releases/download/v1",
        "must be a release asset of",
        id="no-asset-name",
    ),
]


@pytest.mark.parametrize(("url", "expected"), URL_REFUSALS)
def test_bad_package_url_is_refused(url, expected):
    assert expected in _url_errors(url)


def test_good_package_url_passes():
    assert _url_errors(f"{RELEASES}/hello-qml-1.0.0.zip") == ""


def test_url_in_another_repo_is_refused_without_a_download(tmp_path):
    fetch = FakeFetch()
    entry = _qml_entry(fetch)
    _package(entry)["url"] = SDK_RELEASES + "/hello-qml-1.0.0.zip"
    assert "must be a release asset of" in _run(tmp_path, entry, fetch)
    assert fetch.calls == []


def test_http_package_url_is_refused(tmp_path):
    # The schema refuses it first; the validator still reports it.
    fetch = FakeFetch()
    entry = _qml_entry(fetch)
    _package(entry)["url"] = _package(entry)["url"].replace("https://", "http://")
    assert "does not match '^https://'" in _run(tmp_path, entry, fetch)
    assert fetch.calls == []


def test_redirect_to_http_is_refused():
    request = urllib.request.Request(f"{RELEASES}/a.zip")
    handler = validate_entry._HttpsOnlyRedirect()
    with pytest.raises(DownloadError, match="non-HTTPS"):
        handler.redirect_request(request, None, 302, "Found", {}, "http://cdn.example/a.zip")


def test_redirect_to_https_is_followed():
    request = urllib.request.Request(f"{RELEASES}/a.zip")
    handler = validate_entry._HttpsOnlyRedirect()
    redirected = handler.redirect_request(
        request, None, 302, "Found", {}, "https://release-assets.githubusercontent.com/a"
    )
    assert redirected.full_url == "https://release-assets.githubusercontent.com/a"


def test_read_capped_stops_one_byte_past_the_limit():
    assert len(validate_entry.read_capped(io.BytesIO(b"x" * 1000), 10)) == 11
    assert validate_entry.read_capped(io.BytesIO(b"abc"), 10) == b"abc"


# --- Zip contents -----------------------------------------------------------------------


def _manifest_with(**changes) -> dict:
    manifest = _qml_manifest()
    manifest.update(changes)
    return manifest


MANIFEST_REFUSALS = [
    pytest.param(_manifest_with(id="org.example.other"), "'id' does not match", id="id"),
    pytest.param(_manifest_with(version="1.0.1"), "'version' does not match", id="version"),
    pytest.param(_manifest_with(version="1.0"), "'version' does not match", id="trailing-zero"),
    pytest.param(_manifest_with(version="1.0.0-beta"), "is not plain numbers", id="prerelease"),
    pytest.param(_manifest_with(tier="sdk", apiVersion=2), "'tier' does not match", id="tier"),
    pytest.param(_manifest_with(apiVersion=2), "'apiVersion' does not match", id="apiversion"),
    pytest.param(
        _manifest_with(qmlApiVersion=2), "'qmlApiVersion' does not match", id="qmlapiversion"
    ),
    pytest.param(
        _manifest_with(hostVersion={"min": "5.1", "max": ""}),
        "'hostVersion.min' does not match",
        id="host-min",
    ),
    pytest.param(
        _manifest_with(hostVersion={"min": "5.0", "max": "6.0"}),
        "'hostVersion.max' does not match",
        id="host-max",
    ),
    pytest.param(
        _manifest_with(tier="internal"), "tier internal cannot be packaged", id="internal"
    ),
]


@pytest.mark.parametrize(("manifest", "expected"), MANIFEST_REFUSALS)
def test_manifest_that_disagrees_with_the_entry_is_refused(tmp_path, manifest, expected):
    fetch = FakeFetch()
    entry = _qml_entry(fetch, _qml_zip(manifest))
    assert expected in _run(tmp_path, entry, fetch)


def test_equal_versions_with_different_spelling_match():
    entry = _good("qml")
    manifest = _manifest_with(version="01.0.0", hostVersion={"min": "5.00"})
    assert validate_entry._manifest_mismatches(manifest, entry, entry["versions"][0]) == []


def _archive_errors(data: bytes) -> str:
    entry = _good("qml")
    return "\n".join(validate_entry.archive_errors(data, entry, entry["versions"][0]))


def _zip_with_symlink() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("qgcplugin.json", json.dumps(_qml_manifest()))
        link = zipfile.ZipInfo("qml/Main.qml")
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(link, "/etc/passwd")
    return buffer.getvalue()


ARCHIVE_REFUSALS = [
    pytest.param(b"not a zip", "not a zip file", id="not-a-zip"),
    pytest.param(_zip(None, {"qml/Main.qml": b""}), "no qgcplugin.json", id="no-manifest"),
    pytest.param(
        _zip(None, {"qgcplugin.json": b"{"}), "malformed qgcplugin.json", id="bad-manifest-json"
    ),
    pytest.param(
        _qml_zip(files={"../evil.qml": b""}), "points outside the package", id="dot-dot-entry"
    ),
    pytest.param(
        _qml_zip(files={"/etc/evil.qml": b""}), "points outside the package", id="absolute-entry"
    ),
    pytest.param(_zip_with_symlink(), "is a symlink", id="symlink-entry"),
    pytest.param(
        _qml_zip(files={"bin/macos-universal/libhello.dylib": b"x"}),
        "qml-tier package must not ship a binary",
        id="qml-ships-binary",
    ),
    pytest.param(
        _qml_zip(files={"QtCore.framework/QtCore": b"x"}),
        "bundles a runtime library",
        id="bundled-qt",
    ),
    pytest.param(
        _zip(
            {**_qml_manifest(), "contributes": {"replay": True}},
            {"qml/Main.qml": b""},
        ),
        "cannot declare 'replay'",
        id="qml-declares-replay",
    ),
]


@pytest.mark.parametrize(("data", "expected"), ARCHIVE_REFUSALS)
def test_bad_archive_is_refused(data, expected):
    assert expected in _archive_errors(data)


def test_oversized_manifest_is_refused():
    big = json.dumps({**_qml_manifest(), "pad": "x" * validate_entry.MAX_MANIFEST_BYTES})
    data = _zip(None, {"qgcplugin.json": big.encode()})
    assert "is over" in _archive_errors(data)


def test_uncompressed_size_over_the_installer_cap_is_refused(monkeypatch):
    monkeypatch.setattr(validate_entry.pack_plugin, "MAX_PACKAGE_BYTES", 100)
    data = _qml_zip(files={"qml/Main.qml": b"x" * 200})
    assert "extraction ceiling" in _archive_errors(data)


def test_sdk_package_without_a_binary_is_refused(tmp_path):
    fetch = FakeFetch()
    entry = _good("sdk")
    packages = entry["versions"][0]["packages"]
    del packages["windows-x64"]
    fetch.serve(packages["macos-universal"], _zip(_sdk_manifest(), {"qml/Main.qml": b""}))
    assert "no plugin binary found" in _run(tmp_path, entry, fetch)


# --- History against the base branch ----------------------------------------------------


def test_changed_existing_version_is_refused(tmp_path):
    fetch = FakeFetch()
    base = _qml_entry(fetch)
    entry = copy.deepcopy(base)
    entry["versions"][0]["notes"] = "Rewritten."
    assert "version '1.0.0' was changed" in _run(tmp_path, entry, fetch, base=base)


def test_changed_existing_hash_is_refused(tmp_path):
    fetch = FakeFetch()
    base = _qml_entry(fetch)
    entry = copy.deepcopy(base)
    fetch.serve(_package(entry), _qml_zip(files={"qml/Other.qml": b"Item {}"}))
    assert "version '1.0.0' was changed" in _run(tmp_path, entry, fetch, base=base)


def test_respelled_existing_version_is_refused(tmp_path):
    fetch = FakeFetch()
    base = _qml_entry(fetch)
    entry = copy.deepcopy(base)
    entry["versions"][0]["version"] = "1.0.00"
    assert "version '1.0.0' was changed" in _run(tmp_path, entry, fetch, base=base)


def test_removed_version_is_refused(tmp_path):
    fetch = FakeFetch()
    base = _qml_entry(fetch)
    entry = copy.deepcopy(base)
    added = copy.deepcopy(entry["versions"][0])
    added["version"] = "1.1.0"
    entry["versions"] = [added]
    assert "version '1.0.0' was removed" in _run(tmp_path, entry, fetch, base=base)


def test_removed_entry_file_is_refused(tmp_path):
    fetch = FakeFetch()
    base = _qml_entry(fetch)
    plugins = _write(tmp_path / "head")
    base_dir = _write(tmp_path / "base", base)
    errors = "\n".join(validate_entry.validate(plugins, base_dir, fetch))
    assert "the entry was removed" in errors


# --- Rules across the catalog -----------------------------------------------------------


def test_prerelease_version_is_refused(tmp_path):
    fetch = FakeFetch()
    entry = _qml_entry(fetch)
    entry["versions"][0]["version"] = "1.0.0-beta1"
    assert "'1.0.0-beta1' does not match" in _run(tmp_path, entry, fetch)
    assert fetch.calls == []


@pytest.mark.parametrize(
    ("first", "second", "repeats"),
    [("1.1", "1.01", True), ("1.0.0", "1.0.0", True), ("1.0", "1.0.0", False)],
)
def test_duplicate_version_follows_qversionnumber(first, second, repeats):
    entry = _good("qml")
    version = entry["versions"][0]
    entry["versions"] = [{**version, "version": first}, {**version, "version": second}]
    errors = validate_entry.version_errors(entry)
    assert bool(errors) is repeats


def test_file_name_must_equal_id(tmp_path):
    fetch = FakeFetch()
    entry = _qml_entry(fetch)
    plugins = _write(tmp_path / "head", entry, names=["hello.json"])
    errors = "\n".join(validate_entry.validate(plugins, None, fetch))
    assert "the file name must be org.example.hello-qml.json" in errors


def test_duplicate_id_is_refused(tmp_path):
    fetch = FakeFetch()
    entry = _qml_entry(fetch)
    plugins = _write(
        tmp_path / "head", entry, entry, names=["a.json", "org.example.hello-qml.json"]
    )
    errors = "\n".join(validate_entry.validate(plugins, None, fetch))
    assert "is already used by a.json" in errors


def test_ids_differing_only_in_case_are_refused():
    first, second = _good("qml"), _good("qml")
    second["id"] = "Org.Example.Hello-QML"
    errors = validate_entry.duplicate_id_errors({"a.json": first, "b.json": second})
    assert errors and "is already used by a.json" in errors[0]


def test_stray_file_in_plugins_is_refused(tmp_path):
    plugins = _write(tmp_path / "head")
    (plugins / "notes.txt").write_text("hello")
    errors = "\n".join(validate_entry.validate(plugins, None, FakeFetch()))
    assert "holds only <id>.json files" in errors


def test_invalid_json_is_refused(tmp_path):
    plugins = _write(tmp_path / "head")
    (plugins / "broken.json").write_text("{")
    errors = "\n".join(validate_entry.validate(plugins, None, FakeFetch()))
    assert "not valid JSON" in errors


def test_main_exits_nonzero_on_an_error(tmp_path, capsys):
    plugins = _write(tmp_path / "head")
    (plugins / "broken.json").write_text("{")
    assert validate_entry.main([str(plugins)]) == 1
    assert "error: broken.json" in capsys.readouterr().err


def test_main_passes_an_empty_catalog(tmp_path):
    plugins = _write(tmp_path / "head")
    assert validate_entry.main([str(plugins), "--base", str(plugins)]) == 0


def test_zip_with_two_manifests_is_refused():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("qgcplugin.json", json.dumps(_manifest_with(id="evil")))
        with pytest.warns(UserWarning, match="Duplicate name"):
            archive.writestr("qgcplugin.json", json.dumps(_qml_manifest()))
    assert "holds 'qgcplugin.json' more than once" in _archive_errors(buffer.getvalue())


@pytest.mark.parametrize("name", ["C:evil.qml", "..\\evil.qml", "qml\\..\\..\\evil.qml"])
def test_windows_style_escaping_entry_is_refused(name):
    assert "points outside the package" in _archive_errors(_qml_zip(files={name: b""}))


def test_manifest_apiversion_given_as_a_bool_is_refused():
    entry = _good("sdk")
    manifest = {**_sdk_manifest(), "apiVersion": True}
    entry["versions"][0]["apiVersion"] = 1
    errors = validate_entry._manifest_mismatches(manifest, entry, entry["versions"][0])
    assert errors and "'apiVersion' True is not an integer" in errors[0]


def test_manifest_host_max_that_does_not_parse_is_refused():
    entry = _good("qml")
    manifest = _manifest_with(hostVersion={"min": "5.0", "max": "garbage"})
    errors = validate_entry._manifest_mismatches(manifest, entry, entry["versions"][0])
    assert errors and "'hostVersion.max' 'garbage' is not plain numbers" in errors[0]


@pytest.mark.parametrize(
    ("field", "value"),
    [("version", "1.1234567890"), ("min", "5.1234567890"), ("max", "1234567890")],
)
def test_version_segment_over_nine_digits_is_refused(tmp_path, field, value):
    fetch = FakeFetch()
    entry = _qml_entry(fetch)
    version = entry["versions"][0]
    if field == "version":
        version["version"] = value
    else:
        version["hostVersion"][field] = value
    assert "has a segment over 9 digits" in _run(tmp_path, entry, fetch)
