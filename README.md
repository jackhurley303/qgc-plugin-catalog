# QGroundControl plugin catalog

This repo lists plugins for QGroundControl. Each plugin has one JSON file under `plugins/`. QGC
reads a generated `index.json` from GitHub Pages and shows the plugins in its Plugins page.

**Status:** the schemas and their tests exist. The PR validator, the index build and the Pages
publishing are not built yet. Until they are, a PR gets a human review only.

## Layout

- `plugins/<id>.json` — one entry per plugin. The file name equals the entry's `id`.
- `schema/entry.schema.json` — the schema for one entry.
- `schema/index.schema.json` — the schema for the generated `index.json`.
- `tests/` — `pytest` tests for the schemas.

## Publish a plugin

1. Build and pack your plugin with `tools/pack_plugin.py` from the QGC plugin SDK.
2. Publish the zip as a GitHub Release asset in your own repository.
3. Compute the zip's SHA-256 and its size in bytes.
4. Add `plugins/<id>.json` with your plugin's details (see below), and open a PR.

To release a new version, add a new item to `versions` in your file. Never change or remove an
existing version. A released hash must not change under a user.

## Entry format (schema v1)

An entry has these fields. All are strings unless noted.

- **Required:** `id`, `name`, `author`, `summary`, `description`, `license`, `repository`,
  `versions` (a list with at least one item).
- **Optional:** `homepage`, `icon`, `screenshots` (a list).
- `repository` must look like `https://github.com/<owner>/<repo>`.

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
