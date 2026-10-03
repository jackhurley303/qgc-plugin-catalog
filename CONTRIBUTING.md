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
- The entry review does not read code. A plugin becomes verified only through a separate
  verification review (see "Verification" below).
- For the `sdk` tier, the plugin runs native code in QGC. The maintainer reads the entry with
  that in mind.

**A plugin that claims open source** must have a public source repository. The maintainer checks
that the `license` is the one the repository's own license file states. CI checks only that the
id is OSI-approved.

**Listing a closed-source plugin.** The README's "Open source or closed source" section gives the
steps. The entry never names the author's private source repository.

**An update from the same author** gets a maintainer review too, in v1.

**Every PR**

- Only the plugin's own file changes. A verification PR changes only `verifications/`.

CI checks the rest, with `tools/validate_entry.py`. It refuses a change to or removal of an
existing version. It refuses a package URL outside the entry's own `releaseRepository`, or outside
its `repository` when the entry has no `releaseRepository`. It refuses an entry with `repository`
whose `license` is not an OSI-approved SPDX id, and an entry whose repository is private or
missing. It also refuses a package whose size, hash or `qgcplugin.json` disagrees with the entry.

CI runs the base branch's copy of the script, but the PR's own copy of `validate.yml`. A PR can
therefore edit the workflow and skip the checks. CI catches mistakes; it does not stop an attack.
Branch protection on `main` requires a review from a code owner, and `CODEOWNERS` names the
maintainers for `.github/`, `tools/`, `schema/`, `verifications/` and `MAINTAINERS`. That review
is what stops a PR that changes the checks.

## Verification

Verification is a separate review of one version, after its entry is listed. It means that a
maintainer read the source of that version and found nothing malicious. It does not mean the
plugin has no bugs.

**What a verification covers**

- One version and its exact packages. An update is not verified until a maintainer reviews it.
- Everything that builds the package: the source, the build workflow, anything CMake downloads,
  and any bundled binary.

**How to ask for it.** Open an issue that names the plugin, the version and the source commit.
The package must come from the reviewed code. There are two ways to prove that:

- **`maintainer-build`** — for any plugin. The maintainer builds the package from the reviewed
  commit. You then publish that exact file as the release asset, so the entry's `sha256` equals
  the maintainer's build. So ask for verification before you release the version.
- **`attestation`** — for an open-source entry only. A GitHub build attestation ties the
  package's hash to the commit and the workflow, so you can release first. The build must run in
  the entry's public `repository`, on a GitHub-hosted runner. GitHub refuses attestations in a
  user-owned private repository, so a closed-source plugin uses `maintainer-build`.

For `attestation`, the build job needs these permissions:

```yaml
permissions:
  contents: read
  id-token: write
  attestations: write
```

The job attests the package with `actions/attest-build-provenance`. The maintainer checks it with:

```bash
gh attestation verify <package> -R <owner>/<repo> --source-digest <sourceCommit> \
  --signer-workflow <owner>/<repo>/.github/workflows/<file> --deny-self-hosted-runners
```

`<owner>/<repo>` is the entry's `repository` without `https://github.com/`.
`--deny-self-hosted-runners` refuses a build on the author's own runner, where the author
controls the build machine.

**Closed source.** Add the maintainer as a read-only collaborator on your private repository. You
can remove that access after the review. The maintainer keeps your code private: the record holds
the commit SHA and no URL, and nothing from the source is published.

**A maintainer never verifies their own plugin.** CI cannot check this, because an entry's
`author` is a display name and nothing links it to a GitHub login. The maintainer enforces it at
review time.

### The record

The maintainer writes `verifications/<id>.json`, in a PR that changes nothing under `plugins/`.
`schema/verification.schema.json` defines it:

```json
{
  "id": "org.example.hello",
  "versions": [
    {
      "version": "1.2.0",
      "packages": { "macos-universal": "<the package's sha256>" },
      "sourceCommit": "<the reviewed commit, 40 hex characters>",
      "method": "maintainer-build",
      "reviewer": "<the maintainer's GitHub login>",
      "date": "2026-01-15"
    }
  ]
}
```

A record may list some of a version's platform keys. Only the listed packages become verified.
A record has one item per version, so a revoked version stays unverified, and the item lists
every package the review covers.

`build_index.py` adds `verified` (`reviewer`, `date`, `method`) to a package in the index when a
record lists that version, that platform key and the same `sha256`, and the item is not revoked.

**Revoking.** The maintainer adds `revoked` to the item, with a `date` and a `reason`. The item
stays in the record, and the package is no longer marked verified.

CI checks every record against its entry: the id, the version, each platform key and its
`sha256`. It refuses `attestation` for an entry without `repository`. When a PR changes
`verifications/`, CI also checks:

- The PR author is in the base branch's `MAINTAINERS`. The same rule applies to a PR that changes
  `MAINTAINERS`.
- The PR changes nothing under `plugins/`.
- A new item's `reviewer` is in the base branch's `MAINTAINERS`.
- No record or item is removed. The one allowed edit to an existing item adds `revoked`.

CI refuses a symlink at `plugins/`, `verifications/` or `MAINTAINERS`, and inside the two
directories.

## Changing the schema

A new field goes into `schema/entry.schema.json` first. QGC ignores unknown fields, so older QGC
builds keep working. Add tests in `tests/test_schema.py` in the same PR. Run `ruff check .`,
`ruff format --check .` and `pytest` before you push.
