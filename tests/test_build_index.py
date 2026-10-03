import copy
import datetime
import json
from pathlib import Path

import build_index
import pytest

FIXTURES = Path(__file__).resolve().parent / "fixtures"
GENERATED = "2026-10-03"


def _good(name: str) -> dict:
    return json.loads((FIXTURES / f"good-{name}.json").read_text())


def _write(plugins: Path, entry: dict, file_name: str | None = None) -> None:
    plugins.mkdir(exist_ok=True)
    (plugins / (file_name or f"{entry['id']}.json")).write_text(json.dumps(entry))


def _extra_version(entry: dict, version: str) -> dict:
    extra = copy.deepcopy(entry["versions"][0])
    extra["version"] = version
    return extra


@pytest.fixture
def plugins(tmp_path: Path) -> Path:
    directory = tmp_path / "plugins"
    _write(directory, _good("sdk"))
    _write(directory, _good("qml"))
    return directory


def test_index_validates_against_the_schema(plugins: Path):
    index, errors = build_index.build_index(plugins, GENERATED)
    assert errors == []
    assert index is not None
    assert build_index.index_errors(index) == []
    assert index["schemaVersion"] == 1
    assert index["generated"] == GENERATED


def _load_in_reverse(monkeypatch: pytest.MonkeyPatch) -> None:
    """_load_dir already sorts by file name, which equals the id. Reverse it so the sort in
    build_index is the only thing that puts the entries in order."""
    real = build_index.validate_entry._load_dir

    def reversed_load(plugins_dir: Path):
        loaded, errors = real(plugins_dir)
        return dict(reversed(list(loaded.items()))), errors

    monkeypatch.setattr(build_index.validate_entry, "_load_dir", reversed_load)


def test_entries_sort_by_id(plugins: Path, monkeypatch: pytest.MonkeyPatch):
    _load_in_reverse(monkeypatch)
    index, _ = build_index.build_index(plugins, GENERATED)
    assert index is not None
    ids = [entry["id"] for entry in index["plugins"]]
    assert ids == sorted(ids)
    assert len(ids) == 2


def test_versions_sort_numerically(tmp_path: Path):
    entry = _good("qml")
    entry["versions"] = [
        _extra_version(entry, "1.10"),
        _extra_version(entry, "1.9"),
        _extra_version(entry, "1.2.0"),
    ]
    _write(tmp_path / "plugins", entry)
    index, errors = build_index.build_index(tmp_path / "plugins", GENERATED)
    assert errors == []
    assert index is not None
    assert [v["version"] for v in index["plugins"][0]["versions"]] == ["1.2.0", "1.9", "1.10"]


def test_same_input_gives_same_bytes_whatever_the_load_order(
    plugins: Path, monkeypatch: pytest.MonkeyPatch
):
    one, _ = build_index.build_index(plugins, GENERATED)
    _load_in_reverse(monkeypatch)
    two, _ = build_index.build_index(plugins, GENERATED)
    assert one is not None and two is not None
    assert build_index.render(one) == build_index.render(two)


def test_empty_plugins_dir_gives_an_empty_valid_index(tmp_path: Path):
    (tmp_path / "plugins").mkdir()
    (tmp_path / "plugins" / ".gitkeep").write_text("")
    index, errors = build_index.build_index(tmp_path / "plugins", GENERATED)
    assert errors == []
    assert index is not None
    assert index["plugins"] == []


def test_schema_error_refuses_the_build(tmp_path: Path):
    entry = _good("qml")
    entry["sumary"] = "typo"
    _write(tmp_path / "plugins", entry)
    index, errors = build_index.build_index(tmp_path / "plugins", GENERATED)
    assert index is None
    assert any("sumary" in error for error in errors)


def test_file_name_must_equal_id(tmp_path: Path):
    _write(tmp_path / "plugins", _good("qml"), file_name="other.json")
    index, errors = build_index.build_index(tmp_path / "plugins", GENERATED)
    assert index is None
    assert any("the file name must be org.example.hello-qml.json" in e for e in errors)


def test_duplicate_id_refuses_the_build(tmp_path: Path):
    entry = _good("qml")
    _write(tmp_path / "plugins", entry)
    _write(tmp_path / "plugins", entry, file_name="copy.json")
    index, errors = build_index.build_index(tmp_path / "plugins", GENERATED)
    assert index is None
    assert any("already used" in error for error in errors)


def test_duplicate_version_refuses_the_build(tmp_path: Path):
    entry = _good("qml")
    entry["versions"].append(_extra_version(entry, "1.00"))
    entry["versions"].append(_extra_version(entry, "1.0"))
    _write(tmp_path / "plugins", entry)
    index, errors = build_index.build_index(tmp_path / "plugins", GENERATED)
    assert index is None
    assert any("repeats version" in error for error in errors)


def _closed_entry() -> dict:
    entry = _good("qml")
    del entry["repository"]
    entry["releaseRepository"] = "https://github.com/example-author/hello-qml-releases"
    entry["license"] = "Proprietary"
    package = entry["versions"][0]["packages"]["any"]
    package["url"] = package["url"].replace("/hello-qml/", "/hello-qml-releases/")
    return entry


def test_closed_source_entry_builds_and_keeps_release_repository(tmp_path: Path):
    _write(tmp_path / "plugins", _closed_entry())
    index, errors = build_index.build_index(tmp_path / "plugins", GENERATED)
    assert errors == []
    assert index is not None
    plugin = index["plugins"][0]
    assert "repository" not in plugin
    assert plugin["releaseRepository"].endswith("/hello-qml-releases")


def test_open_source_entry_with_a_bad_license_refuses_the_build(tmp_path: Path):
    entry = _good("qml")
    entry["license"] = "Proprietary"
    _write(tmp_path / "plugins", entry)
    index, errors = build_index.build_index(tmp_path / "plugins", GENERATED)
    assert index is None
    assert any("is not an OSI-approved SPDX id" in error for error in errors)


def test_package_url_outside_the_release_repository_refuses_the_build(tmp_path: Path):
    entry = _good("qml")
    entry["releaseRepository"] = "https://github.com/example-author/hello-releases"
    _write(tmp_path / "plugins", entry)
    index, errors = build_index.build_index(tmp_path / "plugins", GENERATED)
    assert index is None
    assert any("must be a release asset of" in error for error in errors)


def test_entry_without_either_repository_refuses_the_build(tmp_path: Path):
    entry = _closed_entry()
    del entry["releaseRepository"]
    _write(tmp_path / "plugins", entry)
    index, errors = build_index.build_index(tmp_path / "plugins", GENERATED)
    assert index is None
    assert any("'repository' or 'releaseRepository'" in error for error in errors)


def test_invalid_json_refuses_the_build(tmp_path: Path):
    (tmp_path / "plugins").mkdir()
    (tmp_path / "plugins" / "broken.json").write_text("{")
    index, errors = build_index.build_index(tmp_path / "plugins", GENERATED)
    assert index is None
    assert any("not valid JSON" in error for error in errors)


def test_main_writes_index_json(plugins: Path, tmp_path: Path):
    out = tmp_path / "site"
    code = build_index.main([str(plugins.parent), "--out", str(out), "--generated", GENERATED])
    assert code == 0
    written = json.loads((out / "index.json").read_text())
    assert written["generated"] == GENERATED
    assert len(written["plugins"]) == 2
    assert (out / "index.json").read_text().endswith("}\n")


def test_main_writes_nothing_on_error(tmp_path: Path):
    entry = _good("qml")
    entry["sumary"] = "typo"
    _write(tmp_path / "plugins", entry)
    out = tmp_path / "site"
    code = build_index.main([str(tmp_path), "--out", str(out)])
    assert code == 1
    assert not (out / "index.json").exists()


def test_main_refuses_a_missing_plugins_dir(tmp_path: Path):
    assert build_index.main([str(tmp_path / "nope"), "--out", str(tmp_path / "site")]) == 1


def test_default_generated_date_is_today_in_utc(plugins: Path, tmp_path: Path):
    out = tmp_path / "site"
    before = datetime.datetime.now(datetime.UTC).date()
    assert build_index.main([str(plugins.parent), "--out", str(out)]) == 0
    after = datetime.datetime.now(datetime.UTC).date()
    generated = datetime.date.fromisoformat(
        json.loads((out / "index.json").read_text())["generated"]
    )
    assert before <= generated <= after


def test_committed_plugins_build_a_valid_index():
    index, errors = build_index.build_index(FIXTURES.parent.parent / "plugins", GENERATED)
    assert errors == []
    assert index is not None
    assert "io.github.jackhurley303.hello-qml" in [entry["id"] for entry in index["plugins"]]


# --- Verified packages ---------------------------------------------------------------------

COMMIT = "0123456789abcdef0123456789abcdef01234567"


def _record_item(entry: dict, key: str, **changes) -> dict:
    version = entry["versions"][0]
    item = {
        "version": version["version"],
        "packages": {key: version["packages"][key]["sha256"]},
        "sourceCommit": COMMIT,
        "method": "maintainer-build",
        "reviewer": "jackhurley303",
        "date": "2026-10-04",
    }
    item.update(changes)
    return item


def _write_record(verifications: Path, plugin_id: str, *items: dict) -> None:
    verifications.mkdir(exist_ok=True)
    record = {"id": plugin_id, "versions": list(items)}
    (verifications / f"{plugin_id}.json").write_text(json.dumps(record))


def _packages(index: dict, plugin_id: str) -> dict:
    entry = next(item for item in index["plugins"] if item["id"] == plugin_id)
    return entry["versions"][0]["packages"]


def test_record_marks_its_package_verified(plugins: Path, tmp_path: Path):
    sdk = _good("sdk")
    _write_record(tmp_path / "verifications", sdk["id"], _record_item(sdk, "macos-universal"))
    index, errors = build_index.build_index(plugins, GENERATED, tmp_path / "verifications")
    assert errors == []
    assert index is not None
    packages = _packages(index, sdk["id"])
    assert packages["macos-universal"]["verified"] == {
        "reviewer": "jackhurley303",
        "date": "2026-10-04",
        "method": "maintainer-build",
    }
    # The record lists one platform key, so the other package stays unverified.
    assert "verified" not in packages["windows-x64"]
    assert "verified" not in _packages(index, _good("qml")["id"])["any"]
    assert build_index.index_errors(index) == []


def test_revoked_record_drops_the_mark(plugins: Path, tmp_path: Path):
    sdk = _good("sdk")
    revoked = {"date": "2026-10-05", "reason": "Found a hidden download."}
    item = _record_item(sdk, "macos-universal", revoked=revoked)
    _write_record(tmp_path / "verifications", sdk["id"], item)
    index, errors = build_index.build_index(plugins, GENERATED, tmp_path / "verifications")
    assert errors == []
    assert index is not None
    assert "verified" not in _packages(index, sdk["id"])["macos-universal"]


def test_record_hash_that_differs_refuses_the_build(plugins: Path, tmp_path: Path):
    sdk = _good("sdk")
    item = _record_item(sdk, "macos-universal")
    item["packages"]["macos-universal"] = "f" * 64
    _write_record(tmp_path / "verifications", sdk["id"], item)
    index, errors = build_index.build_index(plugins, GENERATED, tmp_path / "verifications")
    assert index is None
    assert any("in the record, but" in error for error in errors)


def test_build_does_not_change_the_loaded_entries(plugins: Path, tmp_path: Path):
    sdk = _good("sdk")
    _write_record(tmp_path / "verifications", sdk["id"], _record_item(sdk, "macos-universal"))
    first, _ = build_index.build_index(plugins, GENERATED, tmp_path / "verifications")
    second, _ = build_index.build_index(plugins, GENERATED)
    assert first is not None and second is not None
    assert "verified" not in _packages(second, sdk["id"])["macos-universal"]


def test_author_written_verified_refuses_the_build(tmp_path: Path):
    entry = _good("qml")
    entry["versions"][0]["packages"]["any"]["verified"] = {
        "reviewer": "someone",
        "date": "2026-10-04",
        "method": "maintainer-build",
    }
    _write(tmp_path / "plugins", entry)
    index, errors = build_index.build_index(tmp_path / "plugins", GENERATED)
    assert index is None
    assert any("'verified' is added by the catalog" in error for error in errors)


def test_main_reads_the_verifications_dir(plugins: Path, tmp_path: Path):
    sdk = _good("sdk")
    _write_record(tmp_path / "verifications", sdk["id"], _record_item(sdk, "windows-x64"))
    out = tmp_path / "site"
    assert build_index.main([str(tmp_path), "--out", str(out), "--generated", GENERATED]) == 0
    written = json.loads((out / "index.json").read_text())
    assert "verified" in _packages(written, sdk["id"])["windows-x64"]


def test_committed_records_build_a_valid_index():
    root = FIXTURES.parent.parent
    index, errors = build_index.build_index(root / "plugins", GENERATED, root / "verifications")
    assert errors == []
    assert index is not None


def test_symlinked_verifications_dir_refuses_the_build(plugins: Path, tmp_path: Path):
    sdk = _good("sdk")
    elsewhere = tmp_path / "elsewhere"
    _write_record(elsewhere, sdk["id"], _record_item(sdk, "macos-universal"))
    (tmp_path / "verifications").symlink_to(elsewhere)
    index, errors = build_index.build_index(plugins, GENERATED, tmp_path / "verifications")
    assert index is None
    assert errors == ["verifications/ must be a directory, not a symlink"]
