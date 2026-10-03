**Profile:** feature-change

# Plugin catalog — catalog repo (qgc-plugin-catalog)

## Status — current position / next step

Planning finished 2026-09-30. C1 shipped 2026-10-03: the schemas, their tests, the docs and the
`ci.yml` job. The public GitHub repo `jackhurley303/qgc-plugin-catalog` is `origin`.

C2 shipped 2026-10-03: `tools/validate_entry.py`, its tests and `validate.yml`. Local `ruff` and
`pytest` (116 tests) were green. Two steps wait for the user:

- Push C2 straight to `main`, not through a PR. `validate.yml` runs the base branch's copy of
  the script, so a PR whose base lacks the script fails that job.
- Open a deliberately bad test PR, for example an entry with a wrong `sha256`. Confirm that
  `Validate entries` shows red, then close the PR. Only then does C2's "shows red on GitHub" hold.

C3 shipped 2026-10-03: `tools/build_index.py`, its tests (130 tests pass in all) and `publish.yml`.
Three steps wait for the user, in this order:

- Push C2 and C3 to `main`.
- Enable Pages with the source set to "GitHub Actions" (Settings → Pages). The Pages API returned
  404 on 2026-10-03, so Pages is off. Without this, `deploy-pages` fails.
- After the first `publish.yml` run, open
  `https://jackhurley303.github.io/qgc-plugin-catalog/index.json` and confirm it serves the empty
  index. Only then does C3's "the Pages URL serves `index.json`" hold. Also confirm that the
  `github-pages` environment limits deploys to `main`.

C4 shipped 2026-10-03: `samples/hello-qml/`, `plugins/io.github.jackhurley303.hello-qml.json` and
one test that builds the index from the committed `plugins/`. The zip is 1210 bytes with SHA-256
`6afe4a44…cbd30`. `pack_plugin.py` output is deterministic, so a repack gives the same hash.
C2, C3 and C4 are pushed to `main`, the release `hello-qml-v1.0.0` exists, and Pages is on.
`Publish index` ran green for `8e6b00e`, and the Pages `index.json` lists the sample. On macOS the
user installed it from the Browse tab. The Installed tab showed it Active, and the Tool menu
showed its page. Two C2 and C3 checks still wait for the user:

- Open a deliberately bad test PR and confirm `Validate entries` shows red. Then close the PR.
- Confirm the `github-pages` environment limits deploys to `main`.

Next: the coordinating plan's next row, which sits in
`~/.claude/local/qgroundcontrol/plans/plugin-catalog.md`. Run `/lc-status` there.

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
- **Depends on:** C1. The entry schema (C1) already refuses a pre-release `version`, an uppercase
  or non-64-character `sha256`, an `http` URL, and a `repository` that is not
  `https://github.com/<owner>/<repo>`. C2 runs the schema first, so it only adds its own test for
  the version refusal. The workflow file is `validate.yml`; C1's `ci.yml` stays as the repo's own
  test job. `pytest` has no `pythonpath` entry for `tools/` yet: C2 adds `pythonpath = ["tools"]`
  to `pyproject.toml` when its tests import `validate_entry`. JSON Schema cannot express two
  rules that QGC's parser enforces, so C2's script checks them and tests both. First, versions in
  one entry must be unique as `QVersionNumber` compares them: integer segments, so `1.01`
  equals `1.1`, but trailing zeros count, so `1.0` and `1.0.0` differ (Qt 6.11.1 docs,
  `QVersionNumber::compare`). The parser refuses the whole catalog on a duplicate. Second,
  plugin ids must be unique across `plugins/`. C2's script also checks that the file name equals
  the entry's `id`.
- **As built:** the package rules come from `tools/vendor/pack_plugin.py`, a byte-identical copy
  of the SDK's script. Its source commit is in `validate_entry.py`'s docstring. `validate.yml`
  installs dependencies from, and runs the script of, a second checkout of the base branch, so a
  PR cannot change the checks that judge it. Only versions missing from the base branch are
  downloaded. The script also refuses a zip that repeats a name, a zip entry outside the package
  or a symlink, a manifest `apiVersion` that is a JSON bool, and a version segment over 9 digits.
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

- [x] **C1** — repo scaffold and schema v1 — [Sonnet · medium · off] — 2026-10-03
- [x] **C2** — PR validator — [Opus · medium · on] — 2026-10-03
- [x] **C3** — index build and Pages publishing — [Sonnet · medium · off] — 2026-10-03
- [x] **C4** — qml-tier sample plugin and the first entry — [Sonnet · low · off] — 2026-10-03
  (release, Pages and the macOS install confirmed)

## Open questions

**In-scope**

- None open. C2 decided three:
  - **The package size cap:** 50 MB, compressed. A QDrive Release binary is 2.8 MB for one
    architecture.
  - **How CI gets `pack_plugin.py`:** a pinned copy at `tools/vendor/pack_plugin.py`.
  - **Rules for plugin ids:** none beyond the schema's pattern. The reviewer checks the id.

**Deferred past this change**

- **Moving the repo to the `mavlink` GitHub org.** It depends on the coordinating plan's S1.
- **A signed index, download counts, more maintainers.** Later growth.
