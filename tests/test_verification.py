import copy
import json
from pathlib import Path

import pytest
import validate_entry
import verification
from jsonschema import Draft202012Validator

FIXTURES = Path(__file__).resolve().parent / "fixtures"
PLUGIN_ID = "org.example.hello-sdk"
COMMIT = "0123456789abcdef0123456789abcdef01234567"
MAINTAINER = "jackhurley303"


def _sdk_entry() -> dict:
    return json.loads((FIXTURES / "good-sdk.json").read_text())


def _closed_entry() -> dict:
    """The sdk fixture as a closed-source entry: no repository, packages in a releases repo."""
    entry = _sdk_entry()
    del entry["repository"]
    entry["license"] = "Proprietary"
    entry["releaseRepository"] = "https://github.com/example-author/hello-sdk-releases"
    for package in entry["versions"][0]["packages"].values():
        package["url"] = package["url"].replace("/hello-sdk/", "/hello-sdk-releases/")
    return entry


def _sha(key: str) -> str:
    return _sdk_entry()["versions"][0]["packages"][key]["sha256"]


def _item(**changes) -> dict:
    item = {
        "version": "2.1",
        "packages": {"macos-universal": _sha("macos-universal")},
        "sourceCommit": COMMIT,
        "method": "maintainer-build",
        "reviewer": MAINTAINER,
        "date": "2026-10-04",
    }
    item.update(changes)
    return item


def _record(*items: dict) -> dict:
    return {"id": PLUGIN_ID, "versions": list(items) or [_item()]}


def _catalog(
    root: Path,
    records: list[dict] | None = None,
    entries: list[dict] | None = None,
    maintainers: str | None = f"{MAINTAINER}\n",
) -> Path:
    """A checkout of the catalog repo: plugins/, verifications/ and MAINTAINERS."""
    (root / "plugins").mkdir(parents=True)
    (root / "verifications").mkdir()
    for entry in entries if entries is not None else [_sdk_entry()]:
        (root / "plugins" / f"{entry['id']}.json").write_text(json.dumps(entry, indent=2))
    for record in records or []:
        (root / "verifications" / f"{record['id']}.json").write_text(json.dumps(record, indent=2))
    if maintainers is not None:
        (root / "MAINTAINERS").write_text(maintainers)
    return root


def _validate(head: Path, base: Path | None, author: str | None = MAINTAINER) -> str:
    entries = validate_entry.valid_entries(head / "plugins")
    return "\n".join(verification.validate(head, base, author, entries))


def _record_errors(record: object, entry: dict | None = None) -> str:
    entry = entry or _sdk_entry()
    file_name = f"{record['id']}.json" if isinstance(record, dict) else "x.json"
    return "\n".join(verification.record_errors(file_name, record, {entry["id"]: entry}))


# --- The record schema ------------------------------------------------------------------


def test_record_schema_is_itself_valid():
    Draft202012Validator.check_schema(verification.RECORD_SCHEMA)


def test_good_record_passes():
    record = _record(_item(packages={"macos-universal": _sha("macos-universal")}))
    record["versions"][0]["packages"]["windows-x64"] = _sha("windows-x64")
    assert _record_errors(record) == ""


def test_revoked_record_passes():
    record = _record(_item(revoked={"date": "2026-10-05", "reason": "Found a hidden download."}))
    assert _record_errors(record) == ""


def _set(field: str, value):
    def mutate(record: dict) -> None:
        record["versions"][0][field] = value

    return mutate


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (_set("sourceCommit", "abc123"), "does not match"),
        (_set("sourceCommit", COMMIT.upper()), "does not match"),
        (_set("method", "trust-me"), "is not one of"),
        (_set("reviewer", "-bad"), "does not match"),
        (_set("date", "4 Oct 2026"), "does not match"),
        (_set("packages", {}), "should be non-empty"),
        (_set("packages", {"macos-arm64": "0" * 64}), "is not one of"),
        (_set("packages", {"any": "0" * 63}), "does not match"),
        (_set("revoked", {"date": "2026-10-05"}), "'reason' is a required property"),
        (_set("revoked", {"date": "2026-10-05", "reason": ""}), "should be non-empty"),
        (_set("verified", True), "Additional properties are not allowed"),
        (lambda record: record["versions"][0].pop("sourceCommit"), "'sourceCommit' is a required"),
        (lambda record: record.update(versions=[]), "should be non-empty"),
        (lambda record: record.update(note="x"), "Additional properties are not allowed"),
    ],
)
def test_record_that_breaks_the_schema_is_refused(mutate, expected):
    record = _record()
    mutate(record)
    assert expected in _record_errors(record)


# --- A record must match its entry -------------------------------------------------------


def test_record_file_name_must_equal_its_id():
    errors = verification.record_errors("other.json", _record(), {PLUGIN_ID: _sdk_entry()})
    assert errors == [f"the file name must be {PLUGIN_ID}.json"]


def test_record_for_an_id_without_an_entry_is_refused():
    record = _record()
    record["id"] = "org.example.missing"
    assert "there is no valid entry plugins/org.example.missing.json" in _record_errors(record)


def test_record_for_a_version_the_entry_lacks_is_refused():
    assert "the entry has no version '2.2'" in _record_errors(_record(_item(version="2.2")))
    assert "the entry has no version '2.1.0'" in _record_errors(_record(_item(version="2.1.0")))


def test_record_version_must_match_the_entry_spelling_exactly():
    # 2.01 equals 2.1 for QVersionNumber, but a record names the version as the entry spells it.
    assert "the entry has no version '2.01'" in _record_errors(_record(_item(version="2.01")))


def test_record_for_a_platform_key_the_entry_lacks_is_refused():
    record = _record(_item(packages={"linux-x64": _sha("windows-x64")}))
    assert "version '2.1' has no package 'linux-x64'" in _record_errors(record)


def test_record_hash_that_differs_from_the_entry_is_refused():
    record = _record(_item(packages={"macos-universal": "f" * 64}))
    errors = _record_errors(record)
    assert f"has SHA-256 {'f' * 64} in the record" in errors
    assert _sha("macos-universal") in errors


def test_record_that_repeats_a_version_is_refused():
    errors = _record_errors(_record(_item(), _item(date="2026-10-06")))
    assert "versions[1]: version '2.1' already has an item in this record" in errors


def test_attestation_for_an_entry_without_repository_is_refused():
    entry = _closed_entry()
    record = _record(_item(method="attestation"))
    assert "method 'attestation' needs an entry with 'repository'" in _record_errors(record, entry)


def test_attestation_for_an_open_source_entry_passes():
    assert _record_errors(_record(_item(method="attestation"))) == ""


def test_maintainer_build_for_a_closed_source_entry_passes():
    assert _record_errors(_record(), _closed_entry()) == ""


def test_stray_file_and_invalid_json_in_verifications_are_refused(tmp_path):
    head = _catalog(tmp_path / "head")
    (head / "verifications" / "notes.txt").write_text("x")
    (head / "verifications" / f"{PLUGIN_ID}.json").write_text("{")
    errors = _validate(head, None)
    assert "verifications/notes.txt: verifications/ holds only <id>.json files" in errors
    assert f"verifications/{PLUGIN_ID}.json: not valid JSON" in errors


def test_record_checks_run_without_a_base_branch(tmp_path):
    head = _catalog(tmp_path / "head", [_record(_item(version="9.9"))])
    assert "the entry has no version '9.9'" in _validate(head, None)


def test_entry_that_drops_repository_strands_an_attestation_record(tmp_path):
    # The record checks run on every pull request, so an entry change that breaks an existing
    # record fails too.
    record = _record(_item(method="attestation"))
    base = _catalog(tmp_path / "base", [record])
    head = _catalog(tmp_path / "head", [record], [_closed_entry()])
    assert "method 'attestation' needs an entry with 'repository'" in _validate(head, base)


# --- Who may change verifications/ --------------------------------------------------------


def test_maintainer_adds_a_record(tmp_path):
    base = _catalog(tmp_path / "base")
    head = _catalog(tmp_path / "head", [_record()])
    assert _validate(head, base) == ""


def test_login_comparison_ignores_case(tmp_path):
    base = _catalog(tmp_path / "base")
    head = _catalog(tmp_path / "head", [_record(_item(reviewer="JackHurley303"))])
    assert _validate(head, base, author="JACKHURLEY303") == ""


def test_non_maintainer_change_is_refused(tmp_path):
    base = _catalog(tmp_path / "base")
    head = _catalog(tmp_path / "head", [_record()])
    errors = _validate(head, base, author="stranger")
    assert "'stranger' is not in the base branch's MAINTAINERS" in errors


def test_maintainers_come_from_the_base_branch(tmp_path):
    base = _catalog(tmp_path / "base")
    head = _catalog(
        tmp_path / "head", [_record(_item(reviewer="stranger"))], maintainers="stranger\n"
    )
    errors = _validate(head, base, author="stranger")
    assert "'stranger' is not in the base branch's MAINTAINERS" in errors
    assert "reviewer 'stranger' is not in the base branch's MAINTAINERS" in errors


def test_change_without_an_author_is_refused(tmp_path):
    base = _catalog(tmp_path / "base")
    head = _catalog(tmp_path / "head", [_record()])
    assert "needs the pull request author's login (--author)" in _validate(head, base, None)
    assert "needs the pull request author's login (--author)" in _validate(head, base, "")


def test_change_against_a_base_without_maintainers_is_refused(tmp_path):
    base = _catalog(tmp_path / "base", maintainers=None)
    head = _catalog(tmp_path / "head", [_record()])
    assert "the base branch has no MAINTAINERS file" in _validate(head, base)


def test_change_against_a_base_without_verifications_passes_for_a_maintainer(tmp_path):
    base = _catalog(tmp_path / "base")
    (base / "verifications").rmdir()
    head = _catalog(tmp_path / "head", [_record()])
    assert _validate(head, base) == ""


def test_reviewer_not_in_maintainers_is_refused(tmp_path):
    base = _catalog(tmp_path / "base")
    head = _catalog(tmp_path / "head", [_record(_item(reviewer="someone-else"))])
    assert "reviewer 'someone-else' is not in the base branch's MAINTAINERS" in _validate(
        head, base
    )


def test_changing_plugins_and_verifications_together_is_refused(tmp_path):
    entry = _sdk_entry()
    base = _catalog(tmp_path / "base", entries=[entry])
    changed = copy.deepcopy(entry)
    changed["summary"] = "A changed summary."
    head = _catalog(tmp_path / "head", [_record()], [changed])
    assert "must not change plugins/; open two pull requests" in _validate(head, base)


def test_non_maintainer_may_change_plugins_when_verifications_are_unchanged(tmp_path):
    record = _record()
    base = _catalog(tmp_path / "base", [record])
    changed = _sdk_entry()
    changed["summary"] = "A changed summary."
    head = _catalog(tmp_path / "head", [record], [changed])
    assert _validate(head, base, author="stranger") == ""


# --- A record only grows -----------------------------------------------------------------


def test_maintainer_revokes_an_item(tmp_path):
    base = _catalog(tmp_path / "base", [_record()])
    revoked = _record(_item(revoked={"date": "2026-10-05", "reason": "Found a hidden download."}))
    head = _catalog(tmp_path / "head", [revoked])
    assert _validate(head, base) == ""


def test_non_maintainer_cannot_revoke(tmp_path):
    base = _catalog(tmp_path / "base", [_record()])
    revoked = _record(_item(revoked={"date": "2026-10-05", "reason": "x"}))
    head = _catalog(tmp_path / "head", [revoked])
    assert "'stranger' is not in the base branch's MAINTAINERS" in _validate(
        head, base, author="stranger"
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"date": "2026-10-09"},
        {"reviewer": MAINTAINER, "method": "attestation"},
        {"packages": {"windows-x64": _sha("windows-x64")}},
        {"date": "2026-10-09", "revoked": {"date": "2026-10-10", "reason": "x"}},
    ],
)
def test_edit_to_an_existing_item_is_refused(tmp_path, changes):
    base = _catalog(tmp_path / "base", [_record()])
    head = _catalog(tmp_path / "head", [_record(_item(**changes))])
    assert "versions[0] (version '2.1') was changed; the only allowed edit adds 'revoked'" in (
        _validate(head, base)
    )


def test_edit_to_a_revoked_item_is_refused(tmp_path):
    base = _catalog(
        tmp_path / "base", [_record(_item(revoked={"date": "2026-10-05", "reason": "a"}))]
    )
    head = _catalog(
        tmp_path / "head", [_record(_item(revoked={"date": "2026-10-05", "reason": "b"}))]
    )
    assert "was changed; the only allowed edit adds 'revoked'" in _validate(head, base)


def test_removing_revoked_is_refused(tmp_path):
    base = _catalog(
        tmp_path / "base", [_record(_item(revoked={"date": "2026-10-05", "reason": "a"}))]
    )
    head = _catalog(tmp_path / "head", [_record()])
    assert "was changed; the only allowed edit adds 'revoked'" in _validate(head, base)


def test_removing_an_item_is_refused(tmp_path):
    second_version = _sdk_entry()
    extra = copy.deepcopy(second_version["versions"][0])
    extra["version"] = "2.2"
    second_version["versions"].append(extra)
    record = _record(_item(), _item(version="2.2"))
    base = _catalog(tmp_path / "base", [record], [second_version])
    head = _catalog(tmp_path / "head", [_record()], [second_version])
    assert "versions[1] (version '2.2') was removed; a record only grows" in _validate(head, base)


def test_removing_a_record_file_is_refused(tmp_path):
    base = _catalog(tmp_path / "base", [_record()])
    head = _catalog(tmp_path / "head")
    errors = _validate(head, base)
    assert f"verifications/{PLUGIN_ID}.json: the record was removed; a record only grows" in errors


def test_appending_an_item_checks_only_the_new_reviewer(tmp_path):
    two_versions = _sdk_entry()
    extra = copy.deepcopy(two_versions["versions"][0])
    extra["version"] = "2.2"
    two_versions["versions"].append(extra)
    # The first item's reviewer has left MAINTAINERS since. That item is history, not a change.
    first = _item(reviewer="former-maintainer")
    base = _catalog(tmp_path / "base", [_record(first)], [two_versions])
    head = _catalog(tmp_path / "head", [_record(first, _item(version="2.2"))], [two_versions])
    assert _validate(head, base) == ""


def test_appending_an_item_by_a_reviewer_who_is_not_a_maintainer_is_refused(tmp_path):
    two_versions = _sdk_entry()
    extra = copy.deepcopy(two_versions["versions"][0])
    extra["version"] = "2.2"
    two_versions["versions"].append(extra)
    base = _catalog(tmp_path / "base", [_record()], [two_versions])
    head = _catalog(
        tmp_path / "head",
        [_record(_item(), _item(version="2.2", reviewer="someone-else"))],
        [two_versions],
    )
    assert "reviewer 'someone-else' is not in the base branch's MAINTAINERS" in _validate(
        head, base
    )


def test_changing_a_record_id_is_refused():
    old = _record()
    new = _record()
    new["id"] = "org.example.other"
    errors, _ = verification.history_errors(old, new)
    assert errors == ["the record's 'id' was changed"]


# --- MAINTAINERS ----------------------------------------------------------------------------


def test_maintainers_skips_comments_blank_lines_and_bad_logins(tmp_path):
    path = tmp_path / "MAINTAINERS"
    path.write_text("# The maintainers\n\n  Alice-1  \nnot a login\n@bob\n-carol\ndave\n")
    assert verification.load_maintainers(path) == frozenset({"alice-1", "dave"})


def test_missing_maintainers_file_reads_as_none(tmp_path):
    assert verification.load_maintainers(tmp_path / "MAINTAINERS") is None


def test_committed_maintainers_lists_the_catalog_owner():
    root = FIXTURES.parent.parent
    assert MAINTAINER in verification.load_maintainers(root / "MAINTAINERS")


# --- Marks for the index ------------------------------------------------------------------


def test_marks_cover_each_listed_package_of_a_live_item():
    marks = verification.verified_marks({"r.json": _record()})
    assert marks == {
        (PLUGIN_ID, "2.1", "macos-universal"): {
            "reviewer": MAINTAINER,
            "date": "2026-10-04",
            "method": "maintainer-build",
        }
    }


def test_revoked_item_gives_no_mark():
    record = _record(_item(revoked={"date": "2026-10-05", "reason": "x"}))
    assert verification.verified_marks({"r.json": record}) == {}


# --- Symlinks and MAINTAINERS changes ------------------------------------------------------


def test_symlinked_verifications_dir_is_refused(tmp_path):
    # The CI layout this attack used: the base checkout inside the pull request's checkout,
    # and verifications/ pointed at the base copy, so both sides read the same files.
    head = _catalog(tmp_path / "head")
    base = _catalog(head / "base", [_record()])
    (head / "verifications").rmdir()
    (head / "verifications").symlink_to(base / "verifications")
    errors = _validate(head, base, author="stranger")
    assert "verifications/ must be a directory, not a symlink" in errors


def test_symlinked_record_file_is_refused(tmp_path):
    head = _catalog(tmp_path / "head")
    target = tmp_path / "elsewhere.json"
    target.write_text(json.dumps(_record()))
    (head / "verifications" / f"{PLUGIN_ID}.json").symlink_to(target)
    errors = _validate(head, None)
    assert f"verifications/{PLUGIN_ID}.json: is a symlink" in errors


def test_symlinked_maintainers_is_refused(tmp_path):
    base = _catalog(tmp_path / "base")
    head = _catalog(tmp_path / "head", maintainers=None)
    (head / "MAINTAINERS").symlink_to(base / "MAINTAINERS")
    assert "MAINTAINERS must be a regular file, not a symlink" in _validate(head, base)


def test_symlinked_base_maintainers_reads_as_missing(tmp_path):
    real = tmp_path / "real"
    real.write_text(f"{MAINTAINER}\n")
    (tmp_path / "MAINTAINERS").symlink_to(real)
    assert verification.load_maintainers(tmp_path / "MAINTAINERS") is None


def test_non_maintainer_change_to_maintainers_is_refused(tmp_path):
    base = _catalog(tmp_path / "base")
    head = _catalog(tmp_path / "head", maintainers=f"{MAINTAINER}\nstranger\n")
    errors = _validate(head, base, author="stranger")
    assert "MAINTAINERS: 'stranger' is not in the base branch's MAINTAINERS" in errors


def test_removing_maintainers_needs_a_maintainer(tmp_path):
    base = _catalog(tmp_path / "base")
    head = _catalog(tmp_path / "head", maintainers=None)
    assert "'stranger' is not in the base branch's MAINTAINERS" in _validate(
        head, base, author="stranger"
    )


def test_maintainer_changes_maintainers(tmp_path):
    base = _catalog(tmp_path / "base")
    head = _catalog(tmp_path / "head", maintainers=f"{MAINTAINER}\nnew-maintainer\n")
    assert _validate(head, base) == ""


def test_both_changed_names_both_in_the_error(tmp_path):
    base = _catalog(tmp_path / "base")
    head = _catalog(tmp_path / "head", [_record()], maintainers=f"{MAINTAINER}\nstranger\n")
    errors = _validate(head, base, author="stranger")
    assert "verifications/ and MAINTAINERS: 'stranger' is not in" in errors
