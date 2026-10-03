**Profile:** feature-change

# Plugin catalog — catalog repo (qgc-plugin-catalog)

## Status — current position / next step

Planning finished 2026-09-30. C1 shipped 2026-10-03: the schemas, their tests, the docs and the
`ci.yml` job. The public GitHub repo `jackhurley303/qgc-plugin-catalog` is `origin`.

C2 shipped 2026-10-03: `tools/validate_entry.py`, its tests and `validate.yml`. C3 shipped
2026-10-03: `tools/build_index.py`, its tests and `publish.yml`. Both were pushed straight to
`main`, and Pages serves the index from "GitHub Actions".

C4 shipped 2026-10-03: `samples/hello-qml/`, `plugins/io.github.jackhurley303.hello-qml.json` and
one test that builds the index from the committed `plugins/`. The zip is 1210 bytes with SHA-256
`6afe4a44…cbd30`. `pack_plugin.py` output is deterministic, so a repack gives the same hash.
C2, C3 and C4 are pushed to `main`, the release `hello-qml-v1.0.0` exists, and Pages is on.
`Publish index` ran green for `8e6b00e`, and the Pages `index.json` lists the sample. On macOS the
user installed it from the Browse tab. The Installed tab showed it Active, and the Tool menu
showed its page.

The last two C2 and C3 checks passed on 2026-10-03:

- Test PR #1 added an entry with an all-zero `sha256`. `Validate entries` failed with "has
  SHA-256 6afe4a44…cbd30, not 0000…0000", and `test` passed. The PR was closed unmerged and its
  branch deleted.
- The `github-pages` environment has one custom deployment branch policy, `main`.
  `can_admins_bypass` is `true`, so a repo admin can still deploy from another branch.

On 2026-10-03, QDrive's Q1 found that the catalog cannot take a plugin whose repo is private. The
user decided four things that day:

- The catalog accepts closed-source plugins. Their packages live in a separate public releases
  repo, named by a new `releaseRepository` field (C5).
- QGC labels each plugin "Open source" or "Closed source". "Open source" needs a public
  `repository` and an OSI-approved license, and QGC links to the repository (C5).
- A maintainer can mark a version "Verified" after reviewing its source. An open-source plugin is
  never verified on its own. For a closed-source plugin, the owner gives the maintainer read access
  to the source (C6).
- The maintainer builds a verified package from the reviewed commit. GitHub build attestations
  stay an option until the coordinating plan's S6 answers. S6 answered on 2026-10-03; see below.

C5 shipped 2026-10-03: `releaseRepository`, an optional `repository`, the OSI license rule and
the public-repo check, with their tests and docs. The suite grew from 131 to 186 tests, and 92 fail
with the source change reverted. A live
run of `validate_entry.py` passed the committed hello-qml entry and refused a made-up repository
as "private or does not exist".

Next: QDrive Q1 (`plugins/qdrive/plans/plugin-catalog.md`) can run once the user creates the public
repo `jackhurley303/qdrive-releases` and the two tokens. C6 waits for the coordinating plan's S6.
C6 run settings: Opus · high · on.

The coordinating plan's S6 shipped 2026-10-03. GitHub build attestations work for a public repo
and are refused for a user-owned private repo. So C6 accepts `method: attestation` only when the
package was built in the entry's public `repository`. A closed-source plugin uses
`maintainer-build`. C6's brief carries the rule.

C6's code is in place, 2026-10-03: `tools/verification.py`, `schema/verification.schema.json`,
`MAINTAINERS`, `verifications/`, the `verified` mark in `build_index.py`, and the docs. The suite
grew from 186 to 273 tests. Before the review fixes, with the three edited source files reverted,
46 of the new tests failed. The other new tests cover `tools/verification.py`, which only exists
after C6. A live run on a copy of the catalog passed a maintainer's record, refused it from the
author "stranger", and marked only the recorded package in the index.

The Opus review found two ways past the CI check, both now fixed. First, a PR could make
`verifications` or `plugins` a symlink to the base checkout, which then sat inside the PR's
checkout. Both sides read the same files, so CI saw no change, and after the merge the build read
files nobody checked. The scripts now refuse those symlinks, and `validate.yml` checks the PR out
into `pr/`, beside `base/`. Second, a stranger could add their login to `MAINTAINERS` in one green
PR. A `MAINTAINERS` change now needs a maintainer as author. The reviewer's own probe script now
fails in CI and in the build.

Next, in this order, to finish C6:

1. The user commits C6 and pushes it straight to `main`, as for C2 to C5. As a PR it would fail:
   its new `validate.yml` passes `--author` to the base branch's old script, which does not know
   it. A push does not run `validate.yml`.
2. The user turns on branch protection for `main`: "Require a pull request before merging" and
   "Require review from Code Owners". Admin bypass stays on, because the one maintainer cannot
   approve their own PR. Then read it back with
   `gh api repos/jackhurley303/qgc-plugin-catalog/branches/main/protection`.
3. The red PR from a non-maintainer. Push a throwaway branch `c6-check-base` from `main` whose
   `MAINTAINERS` lists another login. Open a PR into it that adds a record for an existing entry
   and version, with the right `sha256`, so that no other error fires first. `Validate entries`
   must fail with "not in the base branch's MAINTAINERS". Close the PR and delete both branches.
4. Tick C6. Then U5 runs in the coordinating plan.

## Goal & summary

This repo is the QGroundControl plugin catalog. Each plugin has one JSON file under `plugins/`. A
developer adds or updates their file through a PR. CI checks every PR. A merge to `main` rebuilds
`index.json` and publishes it to GitHub Pages, where QGC reads it.

Each plugin is open source or closed source. A maintainer can review a version's source, open or
closed, and mark that version verified. Users see both facts before they install.

The coordinating plan is `~/.claude/local/qgroundcontrol/plans/plugin-catalog.md`. It owns the
order across repos and the whole-change acceptance. QDrive's release pipeline is in
`plugins/qdrive/plans/archive/plugin-catalog.md` in the QGC fork.

## Architecture / approach

#### Layout

- `plugins/<id>.json` — one entry per plugin. The file name equals the entry's `id`.
- `verifications/<id>.json` — the maintainer's verification records for one plugin (C6). Only a
  maintainer changes them.
- `MAINTAINERS` — the GitHub logins of the maintainers, one per line (C6).
- `schema/entry.schema.json`, `schema/index.schema.json` and `schema/verification.schema.json`
  (C6) — JSON Schema. They must match the
  coordinating plan's "The index is the contract" section, which QGC's `PluginCatalog` parser
  also implements.
- `tools/validate_entry.py` — the PR checks.
- `tools/verification.py` — the checks on verification records, and the `verified` marks (C6).
- `tools/build_index.py` — merges the entries into `index.json`.
- `samples/` — the qml-tier sample plugin.
- `.github/workflows/validate.yml` runs on `pull_request`. `publish.yml` runs on a push to `main`.
- `README.md` explains how to publish. `CONTRIBUTING.md` holds the review rules. `CODEOWNERS`
  names the maintainer.
- Python 3.12 or later, `ruff` for lint and format, `pytest` for tests.

#### Schema v1

- **Index:** `schemaVersion` (integer, `1`), `generated` (ISO date), `plugins` (list of entries).
- **Entry:** `id`, `name`, `author`, `summary`, `description`, `license`, `homepage`,
  `repository` (optional), `releaseRepository` (optional), `icon`, `screenshots`, `versions`. An
  entry needs `repository`, `releaseRepository` or both.
- **Version:** `version`, `tier`, `apiVersion`, `qmlApiVersion` (qml tier, optional),
  `hostVersion` (`min`, `max`), `released`, `notes`, `packages`.
- **Packages:** a map from a platform key to `url`, `sha256` and `size`. The keys are
  `macos-universal`, `windows-x64`, `linux-x64` (the QGC loader's own keys), and `any` for the qml
  tier only.

The entry schema is strict: it rejects unknown fields, so a typo fails CI. QGC is lenient: it
ignores unknown fields. A new field therefore goes into the schema first, and older QGC builds keep
working.

#### Additions for closed source and verification

All are additive. QGC already reads `repository` as optional (`PluginCatalog.cc:189`) and hides
the "Repository:" line when it is empty.

- **Entry `releaseRepository` (C5, optional):** `https://github.com/<owner>/<repo>`, a public repo
  whose release assets hold the packages. When it is present, package URLs must be release assets
  of it. Otherwise they must be release assets of `repository`.
- **Entry `repository` becomes optional (C5).** An entry needs `repository`, `releaseRepository`
  or both. `repository` means "the public source of this plugin". So it is present only for an
  open-source plugin.
- **Open source (C5):** an entry with `repository` must have a `license` that is an OSI-approved
  SPDX id, and its `repository` must be a public GitHub repo. A plugin with public source and a
  license that is not OSI-approved leaves out `repository`, and QGC calls it closed source. QGC
  therefore derives the label from one fact: `repository` is not empty.
- **Package `verified` (C6, index only):** `reviewer` (a GitHub login), `date`, `method`
  (`maintainer-build`, or `attestation` for an open-source entry; see Verification).
  `build_index.py` adds it to a package when a verification record lists that version, that platform key and the same `sha256`, and the record
  is not revoked. Authors never write it.

#### What CI checks on every PR

- The entry matches the schema, and the file name equals its `id`.
- Every package URL uses HTTPS and points to a release asset in the entry's own
  `releaseRepository`, or in `repository` when there is no `releaseRepository`:
  `https://github.com/<owner>/<repo>/releases/download/...`.
- An entry with `repository` has an OSI-approved `license`, and the repository is public (C5).
- A change under `verifications/` comes from a maintainer, in a PR that changes nothing under
  `plugins/`. Each record matches a version and package hash in the entry (C6).
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
author. For an open-source plugin, the maintainer also checks that `repository` is the plugin's
real source. In v1, an update from the same author still gets a maintainer review.

This entry review does not read the code, and it never makes a plugin verified.

#### Verification

Verification is a separate, later review of one version. It means that a maintainer read the
source of that version and found nothing malicious. It does not mean the plugin has no bugs.

- **It covers one version and its exact packages.** A record lists the version, each platform key
  with its `sha256`, the source commit, the method, the reviewer and the date. An update is not
  verified until a maintainer reviews it.
- **The package must come from the reviewed code.** With `maintainer-build`, the maintainer builds
  the package from the reviewed commit. The author publishes that exact file as the release
  asset, so the entry's `sha256` equals the maintainer's build. The author therefore asks for
  verification before the release. With `attestation`, a GitHub build attestation ties the hash to
  the commit and the workflow, so the author can release first. `attestation` needs an entry with
  `repository`, and the attestation's source repo must be that `repository`. The maintainer checks
  it with `gh attestation verify <package> -R <owner>/<repo> --source-digest <sourceCommit>
  --signer-workflow <owner>/<repo>/.github/workflows/<file> --deny-self-hosted-runners`, where
  `<owner>/<repo>` comes from `repository`. The last flag refuses a build on
  the author's own runner, where the author controls the build machine. S6 (2026-10-03) found that
  a user-owned private repo cannot store an attestation, so a closed-source plugin uses
  `maintainer-build`. The user chose on 2026-10-03 to keep both methods: `attestation` is the
  normal path for open source, because `maintainer-build` makes the maintainer build every
  platform's binary for every verified version.
- **The review covers everything that builds the package:** the source, the build workflow,
  anything CMake downloads, and any bundled binary.
- **Closed source:** the owner adds the maintainer as a read-only collaborator on the private repo,
  and can remove that access after the review. The record keeps the commit SHA and no URL.
  CONTRIBUTING states that the maintainer keeps the code private.
- **A maintainer never verifies their own plugin.** The maintainer enforces this at review time.
  CI cannot check it, because an entry's `author` is a display name and nothing links it to a
  GitHub login. QDrive stays unverified for this reason.
- **Revoking:** the maintainer adds `revoked` (a date and a reason) to the record. The record stays,
  and `build_index.py` stops marking the package verified.

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

This repo has no spike of its own. The coordinating plan owns every spike. Its S0 tests a GitHub
Release download through QGC. Its S6 tested GitHub build attestations on 2026-10-03: public repos
yes, user-owned private repos no.

The main risk is CI downloading files from URLs that strangers write. The host allowlist, the
read-only permissions and the absence of secrets limit it. C2 owns these checks.

C5's public-repo check calls the GitHub API with no login, which allows 60 requests per hour from
one IP address. GitHub-hosted runners share addresses, so other jobs may spend that limit. A
rate-limit response fails with "rate limit ... re-run", never with "private". Measured 2026-10-03:
a public repo answers 200 with `"private": false`, a missing repo answers 404, and both carry
`x-ratelimit-remaining`. A rate-limit reply was not measured live, because it takes 60 calls. The
tests fake it, and treat a 429, or a 403 with `x-ratelimit-remaining: 0`, a `Retry-After` header or
"rate limit" in the body, as rate-limited.

**CI is not the trust boundary; the maintainer's merge is.** A `pull_request` run uses the PR's own
copy of `validate.yml`. Only the script and its dependencies come from the base branch. So a PR can
edit the workflow, skip the checks, or set the environment variable that carries the author's
login. This already holds for C2's checks. C6 therefore makes a branch-protection rule on `main`
the boundary: every merge needs a CODEOWNERS review. CODEOWNERS names the maintainers for
`MAINTAINERS`, `verifications/`, `.github/`, `tools/` and `schema/`. The CI maintainer check is a
second layer that catches mistakes. It does not stop a PR that edits the workflow.

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

### C5 — Closed-source entries and the open-source rule

- **Scope:** the optional `releaseRepository` field, `repository` made optional, and the rule that
  an entry needs one of the two. Package URLs bind to `releaseRepository` when it is present. An
  entry with `repository` needs an OSI-approved SPDX `license` and a public repository. Update the
  README's entry format and "Publish a plugin", and CONTRIBUTING's review rules, including how to
  list a closed-source plugin.
- **Not in scope:** verification (C6). QGC's labels (coordinating plan U5).
- **Files:** `schema/entry.schema.json`, `schema/index.schema.json`, `tools/validate_entry.py`,
  `tools/build_index.py` (if it copies fields by name), new `tools/vendor/osi-licenses.json`, their
  tests, `README.md`, `CONTRIBUTING.md`.
- **Depends on:** C4.
- **The OSI list:** a pinned snapshot of the SPDX license list, filtered to `isOsiApproved` and
  not `isDeprecatedLicenseId`. Record its source URL and date in the file, as
  `tools/vendor/pack_plugin.py` records its commit. `license` must be one id from that list. A
  compound expression such as `MIT OR Apache-2.0` is refused in v1.
- **The public-repo check:** `GET https://api.github.com/repos/<owner>/<repo>` with no login must
  return 200 with `"private": false`. A 404 means private or missing, and both fail. A 403 or 429
  for the rate limit fails with a message to re-run, never as "private". Run it only for an entry
  the PR adds or changes, so an unchanged entry never fails on a network error.
- **Done means:** tests pass, including each refusal: no `repository` and no `releaseRepository`;
  a package URL outside `releaseRepository`; a package URL in `repository` when
  `releaseRepository` is set; `repository` with the license `Proprietary`; `repository` with a
  compound or deprecated license id; `repository` with a private or missing repo. A rate-limit
  response gives the re-run message. A closed-source entry with only `releaseRepository` passes. The
  committed hello-qml entry still passes. The review is clean.
- **As built:** `tools/vendor/osi-licenses.json` is SPDX list v3.29.0 (2026-09-16), 141 ids, from
  the tag URL recorded in the file. `validate()` now takes a fourth argument, `repo_check`, beside
  `fetch`. The check runs for an entry the PR adds or changes in any way, and for both
  `repository` and `releaseRepository`. `build_index.py` copies entries whole. Both scripts now share
  `offline_errors()`, which also checks every package URL of every version against the release
  source, so an entry cannot change `releaseRepository` and strand its released packages. The schema's root `anyOf` message repeats the whole entry, so `schema_errors()`
  replaces it with one line. The schema refuses a `.git` suffix on both repository fields.
  C6 adds its maintainer check next to these.
- **Run settings:** Sonnet · high · off. The review uses Opus, because the URL rule decides where
  CI downloads from.

### C6 — Verification records

- **Scope:** `verifications/<id>.json`, its schema, the `MAINTAINERS` file, the validator's
  maintainer rule, and `build_index.py` adding `verified` to packages. Update CONTRIBUTING with the
  verification process from "Verification" above, for open and closed source. Also correct its
  claim that "a PR that changes the validator is judged by the old one". A PR can edit
  `validate.yml` itself, so the maintainer's review is what stops it.
- **Not in scope:** QGC's display (coordinating plan U5). Verifying any real plugin.
- **Files:** new `schema/verification.schema.json`, new `MAINTAINERS`, `CODEOWNERS`,
  `tools/validate_entry.py`, `tools/build_index.py`, `schema/index.schema.json`,
  `.github/workflows/validate.yml` (pass the PR author's login to the script through `env`), their
  tests, `README.md`, `CONTRIBUTING.md`.
- **The trust boundary:** branch protection on `main` that requires a CODEOWNERS review, as Risks
  describes. The user turns it on in Settings; C6 confirms it through the API.
- **Depends on:** C5 and the coordinating plan's S6, which shipped 2026-10-03.
- **`method`:** `maintainer-build` or `attestation`. The validator refuses `attestation` in a
  record for an entry without `repository`. It does not run `gh attestation verify` itself; the
  maintainer runs it at review time, as Verification says, with `--deny-self-hosted-runners`.
  CONTRIBUTING shows that command, says the build must run on a GitHub-hosted runner, and shows
  the workflow permissions an author needs (`id-token: write`, `attestations: write`).
- **The record:** `id`, and `versions`, a list. Each item has `version`, `packages` (platform key
  to `sha256`), `sourceCommit` (40 hex characters), `method`, `reviewer`, `date`, and optional
  `revoked` (`date`, `reason`).
- **Done means:** tests pass, including each refusal: a `verifications/` change from a login not in
  the base branch's `MAINTAINERS`; a PR that changes `plugins/` and `verifications/` together; a
  record for an id or version the entry lacks; an `attestation` record for an entry without
  `repository`; a `sha256` that differs from the entry's package; a
  `reviewer` not in `MAINTAINERS`; an edit to an existing record other than adding `revoked`; a
  `verified` field written into an entry by its author. The index marks a matching package
  verified, and drops the mark when the record is revoked. A deliberately bad PR from a
  non-maintainer shows red on GitHub. `CODEOWNERS` covers the protected paths, and the branch
  protection rule requires its review. The review is clean.
- **As built:**
  - The record checks live in a new `tools/verification.py`, which imports nothing from
    `validate_entry.py`. `record_errors()` runs on every record in both scripts, with or without a
    base branch. So an entry PR that breaks an existing record also fails: for example, it drops
    `repository` from an entry that has an `attestation` record.
  - `change_errors()` runs only when some file under `verifications/` differs from the base.
  - A record names a version exactly as the entry spells it, and names each version once. A
    record may list some of a version's platform keys.
  - The existing items stay identical and in order; new items go at the end. Only a new item's
    reviewer must be in
    `MAINTAINERS`, so a past reviewer may leave it.
  - A missing `--author`, or a base without `MAINTAINERS`, refuses any change.
  - `MAINTAINERS` skips blank lines, `#` lines and any line that is not a login. Logins compare
    without case.
  - `index.schema.json` uses `$ref` to point at the entry schema, so `verified` went into
    `entry.schema.json`'s `package`. `offline_errors()` refuses it in a `plugins/` file.
  - Both CLIs now take the catalog root: `validate_entry.py pr --base base --author "$PR_AUTHOR"`
    and `build_index.py . --out _site`. The two CI checkouts sit side by side.
  - Both scripts refuse a symlink at `plugins/`, `verifications/` or `MAINTAINERS`, and inside the
    two directories. A `MAINTAINERS` change needs a maintainer as author, like a record change.
- **Run settings:** Opus · high · on. The maintainer rule is the trust boundary for "Verified".

## Change acceptance

The coordinating plan owns the whole-change acceptance. This repo's part:

1. A PR with a bad entry fails CI for each check in C2. A good entry passes.
2. The Pages URL serves an `index.json` that validates against schema v1 and lists the sample and
   QDrive.
3. No workflow uses `pull_request_target`, and no PR run has a secret.
4. A closed-source entry with only `releaseRepository` passes CI. An entry that claims open source
   with a license that is not OSI-approved, or with a private repository, fails.
5. Only a maintainer can add or revoke a verification, and the index marks a package verified
   only when a record matches its hash.

## Execution order and progress

- [x] **C1** — repo scaffold and schema v1 — [Sonnet · medium · off] — 2026-10-03
- [x] **C2** — PR validator — [Opus · medium · on] — 2026-10-03
- [x] **C3** — index build and Pages publishing — [Sonnet · medium · off] — 2026-10-03
- [x] **C4** — qml-tier sample plugin and the first entry — [Sonnet · low · off] — 2026-10-03
  (release, Pages and the macOS install confirmed)
- [x] **C5** — closed-source entries and the open-source rule — [Sonnet · high · off] — 2026-10-03
- [ ] **C6** — verification records — [Opus · high · on] — code in place 2026-10-03; the push,
  branch protection and the red PR wait (see Status)

## Open questions

**In-scope**

- None open. C2 decided three:
  - **The package size cap:** 50 MB, compressed. A QDrive Release binary is 2.8 MB for one
    architecture.
  - **How CI gets `pack_plugin.py`:** a pinned copy at `tools/vendor/pack_plugin.py`.
  - **Rules for plugin ids:** none beyond the schema's pattern. The reviewer checks the id.
- Decided 2026-10-03 for C5 and C6:
  - **"Open source" needs an OSI-approved license** and a public repository, and QGC links to it.
  - **Linking a package to its source:** the maintainer builds the package. After S6, an
    open-source plugin may instead use `attestation` from its public `repository`.
  - **A maintainer never verifies their own plugin.** QDrive stays unverified.

**Deferred past this change**

- **Moving the repo to the `mavlink` GitHub org.** It depends on the coordinating plan's S1.
- **A signed index, download counts, more maintainers.** Later growth. With one maintainer, only
  other authors' plugins can be verified.
- **Warning users who installed a version whose verification was revoked.** QGC shows the version
  as not verified, and gives no alert.
