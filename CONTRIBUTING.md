# Contributing

## Adding or updating a plugin

Open a PR that adds or changes one file, `plugins/<id>.json`. See the [README](README.md) for the
entry format.

A passing CI run is required. It is not enough. A maintainer reviews every PR.

## What the maintainer checks

**A new plugin**

- The author is who the entry says.
- The entry is open source or closed source, as the README describes. QGC will label it from
  `repository`.
- For an open-source entry, the `repository` is the plugin's real source, and the release assets
  match that source.
- For a closed-source entry, the `releaseRepository` is a public repository that holds only the
  release packages. The maintainer cannot check the packages against source.
- The entry review does not read code. A plugin will become verified only through a separate
  verification review (catalog unit C6).
- For the `sdk` tier, the plugin runs native code in QGC. The maintainer reads the entry with
  that in mind.

**A plugin that claims open source** must have a public source repository. The maintainer checks
that the `license` is the one the repository's own license file states. CI checks only that the
id is OSI-approved.

**Listing a closed-source plugin.** The README's "Open source or closed source" section gives the
steps. The entry never names the author's private source repository.

**An update from the same author** gets a maintainer review too, in v1.

**Every PR**

- Only the plugin's own file changes.

CI checks the rest, with `tools/validate_entry.py`. It refuses a change to or removal of an
existing version. It refuses a package URL outside the entry's own `releaseRepository`, or outside
its `repository` when the entry has no `releaseRepository`. It refuses an entry with `repository`
whose `license` is not an OSI-approved SPDX id, and an entry whose repository is private or
missing. It also refuses a package whose size, hash or `qgcplugin.json` disagrees with the entry.
CI runs the base branch's copy of the script, so a PR that changes the validator is judged by the
old one.

## Changing the schema

A new field goes into `schema/entry.schema.json` first. QGC ignores unknown fields, so older QGC
builds keep working. Add tests in `tests/test_schema.py` in the same PR. Run `ruff check .`,
`ruff format --check .` and `pytest` before you push.
