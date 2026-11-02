# qgc-plugin-catalog

The public plugin index for QGroundControl. Each plugin is one JSON entry in `plugins/`. After a
merge to `main`, `publish.yml` builds `index.json` and deploys it to GitHub Pages, where the QGC
fork's plugin manager reads it. Python tooling only; no QGC code lives here.

## The two documents that own this repo

- `README.md` — the entry format and what CI checks. Read it before changing a schema, an entry or a check.
- `CONTRIBUTING.md` — maintainer review and verification. Read it before touching `verifications/`,
  `MAINTAINERS` or `CODEOWNERS`.

Plans for this repo sit in `plans/`, beside a coordinating plan in
`~/.claude/local/qgroundcontrol/plans/` of the same name. Doc layout: `~/.claude/rules/workflow.md`.

## Invariants

- **Entries are untrusted input.** Keep `tools/validate_entry.py`'s check order; its docstring states it.
- `validate.yml` runs on `pull_request`, never `pull_request_target`, with read-only permissions and
  no secrets. It runs the base branch's tools, but the PR's own copy of the workflow, so a workflow
  change relies on the code-owner review (CONTRIBUTING.md "Every PR").
- Never edit or remove a released version in `plugins/*.json`; add a new item (README.md "Publish a
  plugin").
- A new field goes into the schema first, with tests (CONTRIBUTING.md "Changing the schema").
- The index build is deterministic. A rebuild of `main` with the published file's `--generated`
  date must be byte-identical to the published `index.json`.
- `tools/vendor/pack_plugin.py` and `tools/_bootstrap.py` are byte-identical copies of
  `~/qgroundcontrol/tools/pack_plugin.py` and `~/qgroundcontrol/tools/_bootstrap.py`. Never edit them
  here. Re-copy them, update the commit SHA in `validate_entry.py`'s docstring, and confirm with `cmp`.
- A change to `verifications/` never shares a PR with a change to `plugins/`.

## Conventions

- Run every Python command with `.venv/bin/python` or the venv's own tools. The system `python3`
  lacks `pytest` and `jsonschema`, and a check run under it fails before it tests anything.
- Before a commit, run `.venv/bin/ruff check .`, `.venv/bin/ruff format --check .` and
  `.venv/bin/pytest`. CI runs the same three.
- `tools/validate_entry.py .` with no `--base` downloads every package, so it is slow and needs the
  network.
- The `main protection` ruleset requires a PR, a code-owner review and the `validate` and `test`
  checks. An entry change lands by PR from a branch named `<id>-<version>`. Plan and tool commits go
  straight to `main` through the repo-admin bypass.
- Public repo: CI runs on every push to `main` and every PR.
