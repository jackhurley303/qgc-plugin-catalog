#!/usr/bin/env python3
"""Merge the entries in plugins/ into index.json, the file QGC reads.

The output depends only on the entries and the generated date, so the same input gives the
same bytes. Entries sort by id, and the versions in each entry sort by version number.

The build runs after a merge, when the PR checks already passed. It repeats the checks that need
no network anyway, and it checks the finished index against schema/index.schema.json. It never
writes a partial index: any error means no file.

Usage:
    python3 tools/build_index.py <plugins-dir> --out <dir> [--generated YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

import validate_entry
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


def build_index(plugins_dir: Path, generated: str) -> tuple[dict | None, list[str]]:
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
        if file_name != f"{entry['id']}.json":
            errors.append(f"{file_name}: the file name must be {entry['id']}.json")
        errors.extend(f"{file_name}: {error}" for error in validate_entry.version_errors(entry))
    errors.extend(validate_entry.duplicate_id_errors(valid))
    if errors:
        return None, errors

    plugins = []
    for entry in sorted(valid.values(), key=lambda item: item["id"]):
        versions = sorted(entry["versions"], key=lambda v: validate_entry.version_key(v["version"]))
        plugins.append({**entry, "versions": versions})
    index = {"schemaVersion": 1, "generated": generated, "plugins": plugins}

    errors = index_errors(index)
    return (None, errors) if errors else (index, [])


def render(index: dict) -> str:
    return json.dumps(index, indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build index.json from the catalog entries.")
    parser.add_argument("plugins_dir", type=Path, help="the plugins/ directory")
    parser.add_argument("--out", type=Path, required=True, help="the directory for index.json")
    parser.add_argument(
        "--generated",
        help="the generated date, YYYY-MM-DD; the default is today's date in UTC",
    )
    args = parser.parse_args(argv)

    if not args.plugins_dir.is_dir():
        print(f"error: {args.plugins_dir} is not a directory", file=sys.stderr)
        return 1
    generated = args.generated or datetime.datetime.now(datetime.UTC).date().isoformat()

    index, errors = build_index(args.plugins_dir, generated)
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
