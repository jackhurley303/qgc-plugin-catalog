# QGroundControl plugin catalog

This repo lists plugins for QGroundControl. Each plugin has one JSON file under `plugins/`. QGC
reads a generated `index.json` from GitHub Pages and shows the plugins in its Plugins page.

**Status:** the schemas, the PR validator, the index build, the Pages workflow and closed-source
entries exist. The one entry is the sample plugin `io.github.jackhurley303.hello-qml`.

## Layout

- `plugins/<id>.json` — one entry per plugin. The file name equals the entry's `id`.
- `schema/entry.schema.json` — the schema for one entry.
- `schema/index.schema.json` — the schema for the generated `index.json`.
- `tools/validate_entry.py` — the checks CI runs on every PR.
- `tools/build_index.py` — merges the entries into `index.json`.
- `samples/hello-qml/` — the qml-tier sample plugin behind the first entry.
- `tools/vendor/pack_plugin.py` — a pinned copy of the plugin SDK's packing rules.
- `tools/vendor/osi-licenses.json` — a pinned snapshot of the OSI-approved SPDX license ids. It
  records its source URL and date.
- `.github/workflows/publish.yml` — builds and deploys `index.json` to GitHub Pages after a merge
  to `main`.
- `tests/` — `pytest` tests for the schemas, the validator and the index build.

## Publish a plugin

1. Build and pack your plugin with `tools/pack_plugin.py` from the QGC plugin SDK.
2. Publish the zip as a GitHub Release asset. An open-source plugin uses its own public
   repository. A closed-source plugin uses a separate public releases repository (see "Open
   source or closed source" below).
3. Compute the zip's SHA-256 and its size in bytes.
4. Add `plugins/<id>.json` with your plugin's details (see below), and open a PR.

CI checks each entry that the PR adds or changes:

- Every repository the entry names is public. CI asks the GitHub API with no login. If GitHub's
  rate limit stops the check, the job says so, and you re-run it.
- An entry with `repository` has an OSI-approved `license`.

CI downloads each new package and checks it:

- The URL is `https://github.com/<owner>/<repo>/releases/download/<tag>/<asset>`, in the entry's
  `releaseRepository`. An entry without `releaseRepository` uses its `repository`.
- The package is 50 MB or less. Its size and SHA-256 equal the entry's `size` and `sha256`.
- The zip's `qgcplugin.json` has the same `id`, `version`, `tier`, `apiVersion`, `qmlApiVersion`
  and `hostVersion` as the entry's version.
- The package passes the SDK's `pack_plugin.py` rules.

Check your entry before you open the PR. Install the tools first, as in "Develop" below:

```bash
.venv/bin/python tools/validate_entry.py plugins
```

This local run downloads every version and asks the GitHub API about every entry. CI passes
`--base` with the base branch's `plugins/`, so it downloads only new versions, checks the
repositories of only the entries the PR adds or changes, and also refuses a change to an existing
version.

To release a new version, add a new item to `versions` in your file. Never change or remove an
existing version. A released hash must not change under a user.

## How the index is published

After a merge to `main`, `publish.yml` runs `tools/build_index.py` and deploys the result to GitHub
Pages. QGC reads `https://jackhurley303.github.io/qgc-plugin-catalog/index.json`. The build sorts
entries by `id` and the versions of each entry by version number, so the same entries give the same
file. It refuses to write an index if any entry fails the checks that need no network. To preview
the index on your machine:

```bash
.venv/bin/python tools/build_index.py plugins --out _site
```

The repo's Pages source must be set to "GitHub Actions" once, in Settings → Pages.

## Open source or closed source

QGC will show "Open source" for an entry that has `repository`, with a link to it. It will show
"Closed source" for an entry without it. The entry decides which one applies. QGC's labels are
unit U5 of the coordinating plan and are not built yet.

**Open source.** Set `repository` to the public source. The `license` must be one SPDX id from
`tools/vendor/osi-licenses.json`, for example `MIT` or `GPL-3.0-only`. CI refuses a compound
expression such as `MIT OR Apache-2.0`, and a deprecated id such as `GPL-3.0`. Packages come from
`repository`'s releases, or from `releaseRepository` when the entry has one. If your source is
public but your license is not OSI-approved, leave out `repository`. QGC will then call the
plugin closed source.

**Closed source.** Leave out `repository`. Create a public repository that holds only the release
packages, and set `releaseRepository` to it. The package URLs must be release assets of that
repository. Your source repository can stay private. The `license` field then holds any text, for
example `Proprietary`.

If an entry has both, packages must come from `releaseRepository`. A package URL in `repository`
fails.

## Entry format (schema v1)

An entry has these fields. All are strings unless noted.

- **Required:** `id`, `name`, `author`, `summary`, `description`, `license`, `versions` (a list
  with at least one item), and at least one of `repository` and `releaseRepository`.
- **Optional:** `repository`, `releaseRepository`, `homepage`, `icon`, `screenshots` (a list).
- `repository` and `releaseRepository` must look like `https://github.com/<owner>/<repo>`.
- `repository` is the public source of the plugin. `releaseRepository` is the public repository
  whose release assets hold the packages.

Each item in `versions` has:

- `version` — dotted numbers only, for example `1.2.0`. A pre-release string such as `1.0.0-beta1`
  is refused.
- `tier` — `qml` or `sdk`.
- `apiVersion` — an integer. Required for the `sdk` tier.
- `qmlApiVersion` — an integer of 1 or more. For the `qml` tier only, and optional.
- `hostVersion` — `min` (required) and `max` (optional, may be empty). Both are dotted numbers.
- `released` — a date, `YYYY-MM-DD`.
- `notes` — optional text.
- `packages` — a map from a platform key to `url`, `sha256` and `size`. The platform keys are
  `macos-universal`, `windows-x64` and `linux-x64`. The key `any` is for the `qml` tier only.
  `sha256` is 64 lowercase hex characters. `url` starts with `https://`.

The schema rejects any field it does not list, so a typo fails the check. QGC itself ignores
unknown fields. A new field is therefore added to the schema first.

## Develop

Python 3.12 or later.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/pytest
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the review rules.
