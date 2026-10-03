# Contributing

## Adding or updating a plugin

Open a PR that adds or changes one file, `plugins/<id>.json`. See the [README](README.md) for the
entry format.

A passing CI run is required. It is not enough. A maintainer reviews every PR.

## What the maintainer checks

**A new plugin**

- The author is who the entry says.
- The `repository` is the plugin's real source.
- The release assets come from that repository and match the source.
- For the `sdk` tier, the plugin runs native code in QGC. The maintainer reads the source with
  that in mind.

**An update from the same author** gets a maintainer review too, in v1.

**Every PR**

- Only the plugin's own file changes.
- Existing versions are not changed or removed. Versions are only added.
- Package URLs point to release assets in the entry's own `repository`.

## Changing the schema

A new field goes into `schema/entry.schema.json` first. QGC ignores unknown fields, so older QGC
builds keep working. Add tests in `tests/test_schema.py` in the same PR. Run `ruff check .`,
`ruff format --check .` and `pytest` before you push.
