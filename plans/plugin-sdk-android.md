**Profile:** feature-change
**Autonomy:** auto-run

# Plugin SDK for Android — catalog repo (qgc-plugin-catalog)

## Status — current position / next step

Planned 2026-10-27. CA1 has not run.

This plan runs inside one run with the coordinating plan and the QDrive plan. Its single row, CA1,
sits after the coordinating plan's U1 in that plan's Execution order. The commands are in the
coordinating plan's Status: `~/.claude/local/qgroundcontrol/plans/plugin-sdk-android.md`.

## Goal & summary

The catalog accepts the package key `android-arm64`, beside `macos-universal`, `windows-x64`,
`linux-x64`, `linux-arm64` and `any`. The key is additive to schema v1: a QGC build that does not
know it skips the package (`isKnownPackageKey()` in QGC's `PluginCatalog.cc`).

The validator also refuses a package whose binary was built for another platform than its key.
That matters most for `android-arm64` against `linux-arm64`: both are aarch64 ELF files, and a
binary under the wrong one fails at `dlopen` on the user's device with no useful reason.

The coordinating plan owns the order across repos, the whole-change acceptance and the delivery
decision. QDrive's plan, `~/qgroundcontrol/plugins/qdrive/plans/plugin-sdk-android.md`, publishes the
first entry with an `android-arm64` package.

## Architecture / approach

#### The key list matches the loader's

QGC's loader returns `android-arm64` on an arm64 Android build. The enum lives in
`schema/entry.schema.json:71` and `schema/verification.schema.json:30`. `android-x64` stays out: no
plan ships a package for it.

#### One binary check, shared with the packer

The coordinating plan's U1 adds a check to the fork's `tools/pack_plugin.py`: a binary must match
its key's format, machine and libc. The catalog refreshes `tools/vendor/pack_plugin.py` from the
fork, never edits it. `validate_entry.py` then calls that check on each sdk-tier package's binary
under `bin/<key>/`, beside the Qt version check it already runs (`qt_version_errors()` at line 490).
So the packer and the catalog refuse the same packages for the same reason.

The check runs on every sdk-tier package, on every key, not only on Android. A key whose check the
packer does not define passes as before.

## Repos & key anchors

**qgc-plugin-catalog** (`main`, protected by the "main protection" ruleset)

- **Schemas:** `schema/entry.schema.json`, `schema/verification.schema.json`. Tests:
  `tests/test_schema.py` (the `linux-arm64` cases at line 340 to mirror).
- **Validator:** `tools/validate_entry.py` (`qt_version_errors()` at line 490, `archive_errors()`
  after it). Tests: `tests/test_validate_entry.py` (the `bin/linux-arm64/` case at line 1096).
  Byte-built binaries: `tests/fixtures_qt.py`.
- **Vendored packer:** `tools/vendor/pack_plugin.py` and `tools/_bootstrap.py`.
- **Docs:** `README.md` (the key list at line 143).

## Risks & spikes

None of its own. The mark that tells an Android ELF from a Linux one comes from the coordinating
plan's A1, through U1's packer.

## Units

### CA1 — The `android-arm64` key and the binary check

- **Scope:** add `android-arm64` to both schema enums and the README. Refresh the vendored packer
  from the fork after U1. `validate_entry.py` runs the packer's binary check on each sdk-tier
  package and refuses a mismatch, naming the key and what the binary is.
- **Not in scope:** `android-x64`; a minimum Android API field (the SDK enforces API 28 at build
  time, so the catalog needs none).
- **Files:** `schema/entry.schema.json`, `schema/verification.schema.json`,
  `tools/validate_entry.py`, `tools/vendor/pack_plugin.py`, `README.md`, the tests beside each, and new byte fixtures in `tests/fixtures_qt.py` if the existing ELF builder
  cannot express the mark.
- **Depends on:** the coordinating plan's U1.
- **Done means:** `python3 -m pytest tests` passes. An `android-arm64` package with an Android ELF
  passes the schema and the validator. A glibc ELF under `android-arm64` is refused, an Android ELF
  under `linux-arm64` is refused, and an x86-64 ELF under an `arm64` key is refused, each with its
  reason. `android-x64` is refused by the schema. The committed QDrive and hello-qml entries still
  validate. The review is clean.
- **Run settings:** Sonnet · medium.

## Change acceptance

1. `python3 -m pytest tests` passes.
2. `python3 tools/build_index.py . --out <dir> --generated <the published index's date>` over the
   committed `plugins/` gives a file identical to the published `index.json`, fetched from the
   catalog's Pages URL.
3. The negative cases in CA1's "Done means" each fail for their named reason.
4. `tools/vendor/pack_plugin.py` equals the fork's `tools/pack_plugin.py` at the run's tip
   (`cmp` exits 0).

## Execution order and progress

The coordinating plan's Execution order places this row.

- [ ] **CA1** — the `android-arm64` key and the binary check — [Sonnet · medium]

## Open questions

**In-scope**

- None. The binary mark is the coordinating plan's A1.

**Deferred past this change**

- **A companion-APK package key.** The coordinating plan defers that route. A key for it would be
  additive to schema v1, because QGC ignores keys it does not know.

## Carried forward
