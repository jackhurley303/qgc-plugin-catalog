#!/usr/bin/env python3
"""Merge the entries in plugins/ into index.json, the file QGC reads.

The output depends only on the entries and the generated date, so the same input gives the
same bytes. Entries sort by id, and the versions in each entry sort by version number.

A package gets `verified` when a record in verifications/ that is not revoked lists its
version, its platform key and its SHA-256. tools/verification.py checks the records.

The build runs after a merge, when the PR checks already passed. It repeats the checks that need
no network anyway, on the entries and on the records, and it checks the finished index against
schema/index.schema.json. It never writes a partial index: any error means no file.

Usage:
    python3 tools/build_index.py <catalog-dir> --out <dir> [--generated YYYY-MM-DD]

The catalog directory is a checkout of this repo: it holds plugins/ and verifications/.
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

import validate_entry
import verification
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parent.parent
INDEX_SCHEMA = json.loads((ROOT / "schema" / "index.schema.json").read_text())

# The index schema refers to "entry.schema.json" by relative name.
_REGISTRY = Registry().with_resource(
    validate_entry.ENTRY_SCHEMA["$id"],
    Resource.from_contents(validate_entry.ENTRY_SCHEMA),
)


def index_errors(index: dict) -> list[str]:
    validator = Draft202012Validator(INDEX_SCHEMA, registry=_REGISTRY)
    return [f"{error.json_path}: {error.message}" for error in validator.iter_errors(index)]


def _with_marks(entry: dict, marks: dict[tuple[str, str, str], dict]) -> dict:
    """A copy of entry, versions sorted, with `verified` on each package a record covers."""
    versions = []
    for version in sorted(
        entry["versions"], key=lambda v: validate_entry.version_key(v["version"])
    ):
        packages = {}
        for key, package in version["packages"].items():
            mark = marks.get((entry["id"], version["version"], key))
            packages[key] = {**package, "verified": mark} if mark else package
        versions.append({**version, "packages": packages})
    return {**entry, "versions": versions}


def build_index(
    plugins_dir: Path, generated: str, verifications_dir: Path | None = None
) -> tuple[dict | None, list[str]]:
    """The index for plugins_dir, or None and the reasons it cannot be built."""
    entries, errors = validate_entry._load_dir(plugins_dir)

    valid: dict[str, dict] = {}
    for file_name, entry in entries.items():
        file_errors = validate_entry.schema_errors(entry)
        if file_errors:
            errors.extend(f"{file_name}: {error}" for error in file_errors)
            continue
        assert isinstance(entry, dict)
        valid[file_name] = entry
        errors.extend(
            f"{file_name}: {error}" for error in validate_entry.offline_errors(file_name, entry)
        )
    errors.extend(validate_entry.duplicate_id_errors(valid))
    records: dict[str, dict] = {}
    if verifications_dir is not None:
        by_id = {entry["id"]: entry for entry in valid.values()}
        records, record_errors = verification.check_records(verifications_dir, by_id)
        errors.extend(record_errors)
    if errors:
        return None, errors

    marks = verification.verified_marks(records)
    plugins = [
        _with_marks(entry, marks) for entry in sorted(valid.values(), key=lambda item: item["id"])
    ]
    index = {"schemaVersion": 1, "generated": generated, "plugins": plugins}

    errors = index_errors(index)
    return (None, errors) if errors else (index, [])


def render(index: dict) -> str:
    return json.dumps(index, indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build index.json from the catalog entries.")
    parser.add_argument("catalog", type=Path, help="a checkout of this repo")
    parser.add_argument("--out", type=Path, required=True, help="the directory for index.json")
    parser.add_argument(
        "--generated",
        help="the generated date, YYYY-MM-DD; the default is today's date in UTC",
    )
    args = parser.parse_args(argv)

    plugins_dir = args.catalog / "plugins"
    if not plugins_dir.is_dir():
        print(f"error: {plugins_dir} is not a directory", file=sys.stderr)
        return 1
    generated = args.generated or datetime.datetime.now(datetime.UTC).date().isoformat()

    index, errors = build_index(plugins_dir, generated, args.catalog / "verifications")
    if index is None:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "index.json").write_text(render(index), encoding="utf-8")
    print(f"Wrote {args.out / 'index.json'} with {len(index['plugins'])} plugin(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
