"""Check the maintainer's verification records in verifications/, and turn them into marks.

A record, verifications/<id>.json, says that a maintainer read the source of one version of a
plugin and found nothing malicious. It lists the exact package hashes the review covered.
build_index.py marks a package `verified` only when a record that is not revoked lists that
version, that platform key and the same SHA-256.

Two kinds of check live here:

- record_errors() needs no base branch. validate_entry.py and build_index.py both run it on every
  record, so a record that no longer matches its entry stops the index build.
- change_errors() compares a pull request with its base branch. Only a login in the base
  branch's MAINTAINERS may change verifications/ or MAINTAINERS. A change to verifications/ never
  comes in the same pull request as a change to plugins/. A record only grows: a maintainer
  appends items, or adds `revoked` to one.

No symlink is accepted at verifications/, inside it, or at MAINTAINERS. A symlink could point the
pull request's copy at the base branch's copy, so the comparison would see no change, and after
the merge it could point at files nobody checked.

CI is a second layer here. A pull request runs its own copy of validate.yml, so it can skip
these checks. The CODEOWNERS review that branch protection requires on main is what stops it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent.parent
RECORD_SCHEMA = json.loads((ROOT / "schema" / "verification.schema.json").read_text())

_LOGIN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}$")


# --- Loading --------------------------------------------------------------------------


def load_maintainers(path: Path) -> frozenset[str] | None:
    """The maintainers' GitHub logins, folded to lower case, or None if the file is missing.

    One login per line. Blank lines and lines that start with '#' are skipped. A line that is
    not a GitHub login is skipped too, so a typo removes a maintainer and never adds one.
    """
    if path.is_symlink() or not path.is_file():
        return None
    logins = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if _LOGIN_RE.match(text):
            logins.add(text.casefold())
    return frozenset(logins)


def load_records(directory: Path) -> tuple[dict[str, object], list[str]]:
    """Every record file by name, plus errors for files that are not records.

    A missing directory holds no records. A base branch from before verification had none.
    """
    records: dict[str, object] = {}
    errors: list[str] = []
    if directory.is_symlink():
        return records, ["verifications/ must be a directory, not a symlink"]
    if not directory.is_dir():
        return records, errors
    for path in sorted(directory.iterdir()):
        if path.name == ".gitkeep":
            continue
        where = f"verifications/{path.name}"
        if path.is_symlink():
            errors.append(f"{where}: is a symlink; verifications/ holds only regular files")
            continue
        if not path.is_file() or path.suffix != ".json":
            errors.append(f"{where}: verifications/ holds only <id>.json files")
            continue
        try:
            records[path.name] = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            errors.append(f"{where}: not valid JSON: {exc}")
    return records, errors


def _file_bytes(directory: Path) -> dict[str, bytes]:
    """Every file under directory, by relative path. A missing directory is empty."""
    if not directory.is_dir():
        return {}
    return {
        path.relative_to(directory).as_posix(): path.read_bytes()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def _read(path: Path) -> bytes | None:
    return path.read_bytes() if path.is_file() else None


# --- Checks that need no base branch --------------------------------------------------


def record_errors(file_name: str, record: object, entries: dict[str, dict]) -> list[str]:
    """Every problem with one record, checked against the schema-valid entries by id."""
    validator = Draft202012Validator(RECORD_SCHEMA)
    errors = [f"{error.json_path}: {error.message}" for error in validator.iter_errors(record)]
    if errors:
        return errors
    assert isinstance(record, dict)

    plugin_id = record["id"]
    if file_name != f"{plugin_id}.json":
        errors.append(f"the file name must be {plugin_id}.json")
    entry = entries.get(plugin_id)
    if entry is None:
        return [*errors, f"there is no valid entry plugins/{plugin_id}.json"]

    entry_versions = {version["version"]: version for version in entry["versions"]}
    seen: set[str] = set()
    for index, item in enumerate(record["versions"]):
        text = item["version"]
        where = f"versions[{index}]"
        if text in seen:
            errors.append(f"{where}: version '{text}' already has an item in this record")
            continue
        seen.add(text)
        version = entry_versions.get(text)
        if version is None:
            errors.append(f"{where}: the entry has no version '{text}'")
            continue
        if item["method"] == "attestation" and not entry.get("repository"):
            errors.append(
                f"{where}: method 'attestation' needs an entry with 'repository'; GitHub "
                "attestations work only in a public repository, so a closed-source plugin "
                "uses 'maintainer-build'"
            )
        for key, digest in sorted(item["packages"].items()):
            package = version["packages"].get(key)
            if package is None:
                errors.append(f"{where}: version '{text}' has no package '{key}'")
            elif package["sha256"] != digest:
                errors.append(
                    f"{where}: package '{key}' has SHA-256 {digest} in the record, "
                    f"but {package['sha256']} in the entry"
                )
    return errors


def check_records(directory: Path, entries: dict[str, dict]) -> tuple[dict[str, dict], list[str]]:
    """The records that pass record_errors(), and every problem with the others."""
    loaded, errors = load_records(directory)
    good: dict[str, dict] = {}
    for file_name, record in loaded.items():
        problems = record_errors(file_name, record, entries)
        if problems:
            errors.extend(f"verifications/{file_name}: {problem}" for problem in problems)
        else:
            assert isinstance(record, dict)
            good[file_name] = record
    return good, errors


def verified_marks(records: dict[str, dict]) -> dict[tuple[str, str, str], dict]:
    """The `verified` object for each (id, version, platform key) a live record covers.

    The records must already pass record_errors(), so each hash equals the entry's.
    """
    marks: dict[tuple[str, str, str], dict] = {}
    for record in records.values():
        for item in record["versions"]:
            if "revoked" in item:
                continue
            mark = {"reviewer": item["reviewer"], "date": item["date"], "method": item["method"]}
            for key in item["packages"]:
                marks[(record["id"], item["version"], key)] = mark
    return marks


# --- Checks against the base branch ---------------------------------------------------


def _item_label(index: int, item: object) -> str:
    version = item.get("version") if isinstance(item, dict) else None
    return f"versions[{index}] (version '{version}')"


def history_errors(old: object, new: object) -> tuple[list[str], list[object]]:
    """The edits to an existing record that are not allowed, and the items it appends.

    Existing items keep their order and content. The one allowed edit adds `revoked` to an
    item that has none.
    """
    if not isinstance(old, dict) or not isinstance(new, dict):
        return [], []
    old_items = old.get("versions") if isinstance(old.get("versions"), list) else []
    new_items = new.get("versions") if isinstance(new.get("versions"), list) else []
    errors: list[str] = []
    if new.get("id") != old.get("id"):
        errors.append("the record's 'id' was changed")
    for index, old_item in enumerate(old_items):
        label = _item_label(index, old_item)
        if index >= len(new_items):
            errors.append(f"{label} was removed; a record only grows")
            continue
        new_item = new_items[index]
        if new_item == old_item:
            continue
        revoked_only = (
            isinstance(old_item, dict)
            and isinstance(new_item, dict)
            and "revoked" not in old_item
            and "revoked" in new_item
            and {key: value for key, value in new_item.items() if key != "revoked"} == old_item
        )
        if not revoked_only:
            errors.append(f"{label} was changed; the only allowed edit adds 'revoked'")
    return errors, new_items[len(old_items) :]


def change_errors(
    catalog: Path, base: Path, author: str | None, maintainers: frozenset[str] | None
) -> list[str]:
    """The pull request rules for verifications/ and MAINTAINERS. They apply only when one
    of them changed."""
    records_changed = _file_bytes(catalog / "verifications") != _file_bytes(base / "verifications")
    maintainers_changed = _read(catalog / "MAINTAINERS") != _read(base / "MAINTAINERS")
    if not records_changed and not maintainers_changed:
        return []
    label = " and ".join(
        name
        for name, changed in (
            ("verifications/", records_changed),
            ("MAINTAINERS", maintainers_changed),
        )
        if changed
    )

    errors: list[str] = []
    if maintainers is None:
        errors.append(f"{label}: the base branch has no MAINTAINERS file, so nobody may change it")
    elif not author:
        errors.append(f"{label}: the check needs the pull request author's login (--author)")
    elif author.casefold() not in maintainers:
        errors.append(
            f"{label}: '{author}' is not in the base branch's MAINTAINERS; only a maintainer "
            f"changes {label}"
        )
    if not records_changed:
        return errors

    if _file_bytes(catalog / "plugins") != _file_bytes(base / "plugins"):
        errors.append(
            "verifications/: a pull request that changes verifications/ must not change "
            "plugins/; open two pull requests"
        )

    head_records, _ = load_records(catalog / "verifications")
    base_records, _ = load_records(base / "verifications")
    for file_name in sorted(base_records.keys() - head_records.keys()):
        errors.append(f"verifications/{file_name}: the record was removed; a record only grows")
    for file_name, record in sorted(head_records.items()):
        where = f"verifications/{file_name}"
        if file_name in base_records:
            problems, added = history_errors(base_records[file_name], record)
            errors.extend(f"{where}: {problem}" for problem in problems)
        else:
            added = record.get("versions", []) if isinstance(record, dict) else []
            added = added if isinstance(added, list) else []
        if maintainers is None:
            continue
        for item in added:
            reviewer = item.get("reviewer") if isinstance(item, dict) else None
            if isinstance(reviewer, str) and reviewer.casefold() not in maintainers:
                errors.append(
                    f"{where}: reviewer '{reviewer}' is not in the base branch's MAINTAINERS"
                )
    return errors


def validate(
    catalog: Path, base: Path | None, author: str | None, entries: dict[str, dict]
) -> list[str]:
    """Every problem with the records in catalog, compared with base when it is given."""
    _, errors = check_records(catalog / "verifications", entries)
    if (catalog / "MAINTAINERS").is_symlink():
        errors.append("MAINTAINERS must be a regular file, not a symlink")
    if base is not None:
        maintainers = load_maintainers(base / "MAINTAINERS")
        errors.extend(change_errors(catalog, base, author, maintainers))
    return errors
