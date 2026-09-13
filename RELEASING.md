# Releasing

How to cut a release of this template's `main` branch. This is a manual, checklist-driven procedure — no release tooling/automation is involved.

## When to release

Once a batch of base-improvement PRs has merged into `dev` and is ready to ship to `main`.

## Choosing the version number

This repo follows [SemVer](https://semver.org/) (`MAJOR.MINOR.PATCH`):

- **MAJOR** — breaking changes to the template's public surface: API route contracts, required env vars, auth dependency signatures (`app/auth.py`), or a DB schema change that isn't a straightforward `alembic upgrade head`
- **MINOR** — new features or additions that stay backwards-compatible
- **PATCH** — bug fixes, dependency/security updates, docs-only changes

## Steps

1. Confirm CI is green on `dev`.
2. Open a PR from `dev` into `main` via the GitHub UI, titled `Release vX.Y.Z`.
3. As part of that PR, bump the `version` field in `pyproject.toml`'s `[tool.poetry]` section to `X.Y.Z`.
4. Get the PR reviewed and merge it into `main` via the GitHub UI.
5. On the resulting `main` commit, create and push an annotated tag:

   ```bash
   git checkout main
   git pull
   git tag -a vX.Y.Z -m "vX.Y.Z"
   git push origin vX.Y.Z
   ```

6. Create a GitHub Release from that tag, reviewing/editing the generated notes for clarity:

   ```bash
   gh release create vX.Y.Z --generate-notes
   ```

7. Once the release is published, open a tracking issue (or one per project) to rebase each `<project>` branch (e.g. `openrvdas`) and its `<project>_dev` branch (e.g. `openrvdas_dev`) against the newly released `main`, per the branching workflow in `CLAUDE.md`.

## Notes

- The tags `v0.0.1`/`v0.0.2` predate this procedure. `v1.0.0` was tagged manually, ahead of this document existing, reconciling the `pyproject.toml` version field (which already read `1.0.0` with no corresponding tag) with actual release history — treat it as the first release under this procedure in spirit, even though this doc didn't exist yet when it was cut.
- This procedure covers `main` only. `<project>` branches (e.g. `openrvdas`) aren't independently tagged/released under this scheme — they track `main` via the rebase step above instead. Per-project releases, if ever needed, would be a separate addition to this doc.
- GitHub only auto-closes an issue referenced with a closing keyword (`Closes #N`) in a PR once the commit reaches the repository's **default branch** (`main`), not when the PR merges into `dev`. Issues closed via `issue_NNN` → `dev` PRs will appear to auto-close only once that `dev` → `main` release PR merges — don't be surprised if they don't close immediately, and double-check after a release that everything that should have closed did (GitHub's auto-close doesn't always fire reliably even then; verify and close manually if needed).
