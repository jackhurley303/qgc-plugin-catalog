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


def test_invalid_json_refuses_the_build(tmp_path: Path):
    (tmp_path / "plugins").mkdir()
    (tmp_path / "plugins" / "broken.json").write_text("{")
    index, errors = build_index.build_index(tmp_path / "plugins", GENERATED)
    assert index is None
    assert any("not valid JSON" in error for error in errors)


def test_main_writes_index_json(plugins: Path, tmp_path: Path):
    out = tmp_path / "site"
    code = build_index.main([str(plugins), "--out", str(out), "--generated", GENERATED])
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
    code = build_index.main([str(tmp_path / "plugins"), "--out", str(out)])
    assert code == 1
    assert not (out / "index.json").exists()


def test_main_refuses_a_missing_plugins_dir(tmp_path: Path):
    assert build_index.main([str(tmp_path / "nope"), "--out", str(tmp_path / "site")]) == 1


def test_default_generated_date_is_today_in_utc(plugins: Path, tmp_path: Path):
    out = tmp_path / "site"
    before = datetime.datetime.now(datetime.UTC).date()
    assert build_index.main([str(plugins), "--out", str(out)]) == 0
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
