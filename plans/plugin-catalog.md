**Profile:** feature-change

# Plugin catalog — catalog repo (qgc-plugin-catalog)

## Status — current position / next step

Planning finished 2026-09-30. The repo exists only on this machine, with no commits.

C1 waits for G1, the go/no-go decision in the coordinating plan. G1 runs after spikes S0 and S1.

Before C1: the user creates the public GitHub repo `jackhurley303/qgc-plugin-catalog` and adds it
as `origin`. It must be public so GitHub Pages is free.

Next, once G1 says go: `/implement-unit ~/qgc-plugin-catalog/plans/plugin-catalog.md C1`. Run
settings: Sonnet · medium · off.

## Goal & summary

This repo is the QGroundControl plugin catalog. Each plugin has one JSON file under `plugins/`. A
developer adds or updates their file through a PR. CI checks every PR. A merge to `main` rebuilds
`index.json` and publishes it to GitHub Pages, where QGC reads it.

The coordinating plan is `~/.claude/local/qgroundcontrol/plans/plugin-catalog.md`. It owns the
order across repos and the whole-change acceptance. QDrive's release pipeline is in
`plugins/qdrive/plans/plugin-catalog.md` in the QGC fork.

## Architecture / approach

#### Layout

- `plugins/<id>.json` — one entry per plugin. The file name equals the entry's `id`.
- `schema/entry.schema.json` and `schema/index.schema.json` — JSON Schema. They must match the
  coordinating plan's "The index is the contract" section, which QGC's `PluginCatalog` parser
  also implements.
- `tools/validate_entry.py` — the PR checks.
- `tools/build_index.py` — merges the entries into `index.json`.
- `samples/` — the qml-tier sample plugin.
- `.github/workflows/validate.yml` runs on `pull_request`. `publish.yml` runs on a push to `main`.
- `README.md` explains how to publish. `CONTRIBUTING.md` holds the review rules. `CODEOWNERS`
  names the maintainer.
- Python 3.12 or later, `ruff` for lint and format, `pytest` for tests.

#### Schema v1

- **Index:** `schemaVersion` (integer, `1`), `generated` (ISO date), `plugins` (list of entries).
- **Entry:** `id`, `name`, `author`, `summary`, `description`, `license`, `homepage`,
  `repository`, `icon`, `screenshots`, `versions`.
- **Version:** `version`, `tier`, `apiVersion`, `qmlApiVersion` (qml tier, optional),
  `hostVersion` (`min`, `max`), `released`, `notes`, `packages`.
- **Packages:** a map from a platform key to `url`, `sha256` and `size`. The keys are
  `macos-universal`, `windows-x64`, `linux-x64` (the QGC loader's own keys), and `any` for the qml
  tier only.

The entry schema is strict: it rejects unknown fields, so a typo fails CI. QGC is lenient: it
ignores unknown fields. A new field therefore goes into the schema first, and older QGC builds keep
working.

#### What CI checks on every PR

- The entry matches the schema, and the file name equals its `id`.
- Every package URL uses HTTPS and points to a release asset in the entry's own `repository`:
  `https://github.com/<owner>/<repo>/releases/download/...`.
- CI downloads each package. Its size is under the cap and equals `size`. Its SHA-256 equals
  `sha256`.
- CI opens the zip and reads `qgcplugin.json`. Its `id`, `version`, `tier`, `apiVersion` and host
  range equal the entry's.
- The package passes `pack_plugin.py`'s rules. The plugin SDK ships that script at
  `tools/pack_plugin.py`.
- `version` is plain dotted numbers. No existing version is changed or removed. Versions only get
  added, so a released hash never changes under a user.
- The workflow uses `pull_request`, never `pull_request_target`, with
  `permissions: contents: read` and no secrets. CI downloads files from URLs a stranger wrote, so
  it must hold nothing worth stealing.

#### Review

A passing CI run is required, but it is not enough. For a new plugin, the maintainer checks the
author, the source repository, and that the release comes from that source. In v1, an update from
the same author still gets a maintainer review.

#### Publishing

`publish.yml` runs `build_index.py`, which sorts entries so the output is the same for the same
input. It adds `generated` and deploys to Pages at
`https://jackhurley303.github.io/qgc-plugin-catalog/index.json`.

## Repos & key anchors

- **QGC fork** (`~/qgroundcontrol`): `tools/pack_plugin.py` (rules and `PLATFORM_KEYS`),
  `src/PluginSystem/PluginManifest.h` (manifest fields), `src/PluginSystem/QGCPluginLoader.cc:43-53`
  (platform keys), `plugins/example/qgcplugin.json.in` (a real manifest).
- **CI hardening to mirror:** `plugins/qdrive/.github/workflows/build.yml` in the QGC fork
  (`step-security/harden-runner`, `persist-credentials: false`, `permissions: contents: read`).

## Risks & spikes

This repo has no spike. The coordinating plan's S0 tests a GitHub Release download through QGC.

The main risk is CI downloading files from URLs that strangers write. The host allowlist, the
read-only permissions and the absence of secrets limit it. C2 owns these checks.

## Units

### C1 — Repo scaffold and schema v1

- **Scope:** the layout, both schemas, the developer README, `CONTRIBUTING.md`, `CODEOWNERS`, the
  `pytest` and `ruff` setup, and a CI job that runs tests and lint.
- **Not in scope:** downloads in the validator, publishing, entries.
- **Files:** all new.
- **Depends on:** the coordinating plan's G1 says go; the user has created the GitHub repo.
- **Done means:** schema tests pass on good and bad fixtures: a missing `sha256`, `any` on an
  sdk-tier version, an unknown platform key, an unknown field. CI is green. The review is clean.
- **Run settings:** Sonnet · medium · off.

### C2 — PR validator

- **Scope:** `tools/validate_entry.py` and `validate.yml`, with every check in "What CI checks on
  every PR".
- **Not in scope:** publishing.
- **Files:** new `tools/validate_entry.py`, `tests/test_validate_entry.py` (the tests build small
  fixture zips), `.github/workflows/validate.yml`.
- **Depends on:** C1.
- **Done means:** tests pass, including each refusal: a wrong hash, a size mismatch, a size over
  the cap, a URL in another repo, an `http` URL, a zip `id` mismatch, a changed existing version,
  and a pre-release version string. A deliberately bad test PR shows red on GitHub. The review is
  clean.
- **Run settings:** Opus · medium · on.

### C3 — Index build and Pages publishing

- **Scope:** `tools/build_index.py`, `publish.yml`, and GitHub Pages turned on.
- **Not in scope:** entries.
- **Files:** new `tools/build_index.py`, `tests/test_build_index.py`,
  `.github/workflows/publish.yml`.
- **Depends on:** C2.
- **Done means:** tests pass. The output is the same for the same input, and it validates against
  the index schema. After a merge, the Pages URL serves `index.json`. The review is clean.
- **Run settings:** Sonnet · medium · off.

### C4 — Qml-tier sample plugin and the first entry

- **Scope:** a minimal qml-tier plugin under `samples/`, packed with `pack_plugin.py`, released as
  a GitHub Release of this repo, and its entry in `plugins/` with the package key `any`.
- **Not in scope:** sdk-tier samples.
- **Files:** new `samples/<sample>/` (a manifest and QML), `plugins/<id>.json`.
- **Depends on:** C3.
- **Done means:** the entry's PR passes CI and is merged, and the index lists it. The package
  installs through "Install plugin…" on macOS and shows its contribution.
- **Run settings:** Sonnet · low · off.

## Change acceptance

The coordinating plan owns the whole-change acceptance. This repo's part:

1. A PR with a bad entry fails CI for each check in C2. A good entry passes.
2. The Pages URL serves an `index.json` that validates against schema v1 and lists the sample and
   QDrive.
3. No workflow uses `pull_request_target`, and no PR run has a secret.

## Execution order and progress

- [ ] **C1** — repo scaffold and schema v1 — [Sonnet · medium · off]
- [ ] **C2** — PR validator — [Opus · medium · on]
- [ ] **C3** — index build and Pages publishing — [Sonnet · medium · off]
- [ ] **C4** — qml-tier sample plugin and the first entry — [Sonnet · low · off]

## Open questions

**In-scope**

- **The package size cap.** Default 50 MB. C2 decides after checking QDrive's package size.
- **How CI gets `pack_plugin.py`.** It can download the SDK from a QGC build, or keep a pinned
  copy here. C2 decides.
- **Rules for plugin ids.** For example, must the id's domain match the repository owner? Default:
  no rule, and the reviewer checks. C2 decides.

**Deferred past this change**

- **Moving the repo to the `mavlink` GitHub org.** It depends on the coordinating plan's S1.
- **A signed index, download counts, more maintainers.** Later growth.
