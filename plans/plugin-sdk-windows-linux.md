**Profile:** feature-change
**Autonomy:** auto-run

# Plugin SDK for Windows and Linux — catalog repo (qgc-plugin-catalog)

## Status — current position / next step

Planning finished 2026-10-26. No row has run. The plan doc is not committed yet.

This plan runs inside one run with the coordinating plan and the QDrive plan. Its single row, CA1,
sits after the coordinating plan's U2 in that plan's Execution order. The commands are in the
coordinating plan's Status: `~/.claude/local/qgroundcontrol/plans/plugin-sdk-windows-linux.md`.

## Goal & summary

The catalog accepts two additions that the Windows and Linux plugin SDK needs:

- the package key `linux-arm64`, beside `macos-universal`, `windows-x64`, `linux-x64` and `any`;
- an optional version-level `qtVersion` for the sdk tier, which QGC uses to hide a version built
  against a newer Qt than it runs.

Both are additive to schema v1. A QGC build that does not know them ignores them.

The coordinating plan owns the order across repos, the whole-change acceptance, and the index
contract (the "The index is the contract" section of
`~/.claude/local/qgroundcontrol/plans/plugin-catalog.md`, which its U2 extends). QDrive's plan,
`~/qgroundcontrol/plugins/qdrive/plans/plugin-sdk-windows-linux.md`, publishes the first entry that
uses both additions.

## Architecture / approach

#### The key list matches the loader's

The coordinating plan's U1 makes QGC's loader return `<os>-<arch>` off macOS. Only `linux-arm64`
joins the catalog. `windows-arm64` and `android-*` stay out until a plan ships a package for them.
The enum lives in `schema/entry.schema.json:65` and `schema/verification.schema.json:30`. The
vendored packer, `tools/vendor/pack_plugin.py`, is refreshed from the QGC fork's copy, not edited.

#### `qtVersion` is checked against the binary

An entry's `qtVersion` must equal the build Qt major and minor read from each sdk-tier package's
binary. The validator already downloads each package to check its SHA-256. It then finds the binary
under `bin/<key>/` and reads the Qt metadata header that follows the `QTMETADATA !` magic. The
coordinating plan's K1 writes the header layout into that plan's Carried forward. A package whose
binary disagrees with the entry is refused, with both values in the error.

The scan reads raw bytes, so it works the same on Mach-O, ELF and PE files. A universal dylib holds
one header per slice. Every match must give the same Qt version, or the package is refused. No
match at all is refused too.

The field stays optional. The QDrive 1.0.0 entry lacks it, and so will 1.0.1, which the plugin-catalog
plan's E1 releases. `build_index.py` copies it into the index when it is present.

## Repos & key anchors

**qgc-plugin-catalog** (`main`, protected by the "main protection" ruleset)

- **Schemas:** `schema/entry.schema.json`, `schema/verification.schema.json`,
  `schema/index.schema.json`. Tests: `tests/test_schema.py`.
- **Validator:** `tools/validate_entry.py`. Tests: `tests/test_validate_entry.py`, fixtures in
  `tests/fixtures/`.
- **Index build:** `tools/build_index.py` (`--generated YYYY-MM-DD` fixes the date). Tests:
  `tests/test_build_index.py`.
- **Vendored packer:** `tools/vendor/pack_plugin.py` (a copy of the fork's `tools/pack_plugin.py`).
- **Docs:** `README.md` (the key list at line 137), `CONTRIBUTING.md`.

## Risks & spikes

None of its own. The header layout comes from the coordinating plan's K1.

## Units

### CA1 — The `linux-arm64` key and the `qtVersion` field

- **Scope:** add `linux-arm64` to both schema enums and the README. Refresh the vendored packer
  from the fork. Add optional `qtVersion` (pattern `^[0-9]+\.[0-9]+$`) to a version, sdk tier only.
  The validator reads each sdk-tier package's build Qt and checks it equals `qtVersion` when the
  field is present. `build_index.py` copies it.
- **Not in scope:** making `qtVersion` required; QDrive's entry (the QDrive plan's QD2).
- **Files:** `schema/entry.schema.json`, `schema/verification.schema.json`,
  `schema/index.schema.json`, `tools/validate_entry.py`, `tools/build_index.py`,
  `tools/vendor/pack_plugin.py`, `README.md`, `CONTRIBUTING.md`, the tests beside each.
- **Depends on:** the coordinating plan's U1 (the key), K1 (the header layout) and U2 (the contract
  text).
- **Done means:** tests pass. A `linux-arm64` package passes the schema, and `linux-armhf` is
  refused. A `qtVersion` on a qml-tier version is refused. A package whose binary claims Qt 6.13
  under an entry that says 6.12 is refused with both values. A version without `qtVersion` passes as
  before. Byte fixtures cover a single header (as in ELF and PE), two agreeing headers (a universal
  dylib), two disagreeing headers, and no header. The review is clean.
- **Run settings:** Sonnet · medium.

## Change acceptance

1. `python3 -m pytest tests` passes.
2. `python3 tools/build_index.py . --out <dir> --generated <the published index's date>` over the
   committed `plugins/` gives a file identical to the published `index.json`.
3. The negative cases in CA1's "Done means" each fail for their named reason.

## Execution order and progress

The coordinating plan's Execution order places this row.

- [ ] **CA1** — the `linux-arm64` key and the `qtVersion` field — [Sonnet · medium]

## Open questions

**In-scope**

- None. The header layout is the coordinating plan's K1.

**Deferred past this change**

- **Making `qtVersion` required for new sdk-tier versions.** It would refuse a third-party author
  who has not updated their tooling. Revisit after the demo.
- **`windows-arm64` and `android-*` keys.** The plans that ship those packages add them.

## Carried forward
