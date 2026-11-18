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

7. Once the release is published, open a tracking issue (or one per project) to rebase each `<project>` branch (e.g. `openrvdas`) and its `<project>_dev` branch (e.g. `openrvdas_dev`) against the newly released `main`, per the branching workflow in `CLAUDE.md`. See [Syncing project branches after a release](#syncing-project-branches-after-a-release) for how, including protecting downstream submodule pins before any force-push. If a rebase-tracking issue from a *previous* release is still open when this happens, close it as superseded (a rebase onto the older release is moot once a newer one exists) and reference the new tracking issue in its place — don't leave both open.

## Syncing project branches after a release

Step 7's tracking issue is worked like this. The OpenRVDAS sync for v1.1.x is a worked example: fastapi-template #56 / #57 and vite-react-template #114.

1. **Trial run.** In a throwaway worktree, merge `main` into `<project>_dev` (`git merge-tree --write-tree --name-only` lists the conflicts) and resolve each conflicting file. This gives the final tree the rebase should produce. Note in the tracking issue which side to keep for each file, and run the full checks on it.
2. **Rebase `<project>_dev` onto `main`.** Resolve each stop toward that final tree. If it's simpler to take the project's version at every stop, finish with one follow-up commit that sets the tree to the trial result, and describe in its message what it re-applies from `main`. Don't hand-merge lockfiles: regenerate them.
3. **Verify** (lint, type checks, tests, build, and anything the tracking issue lists). Compare the result with the pre-rebase `<project>_dev`: apart from the resolutions, it should differ only by `main`'s changes.
4. **Protect downstream pins** (next section). This must happen before any force-push.
5. **Force-push `<project>_dev`** with `git push --force-with-lease=<project>_dev:<old sha> origin <project>_dev`, and wait for CI.
6. **Move `<project>`** to the same commit with `git push --force-with-lease=<project>:<old sha> origin <new sha>:refs/heads/<project>`. First confirm that `<project>` has no commits beyond the pre-rebase `<project>_dev` (`git rev-list --no-merges <old _dev sha>..origin/<project>` is empty). A normal PR would duplicate the rewritten commits.
7. Comment on the tracking issue with the old and new SHAs, the conflicts, what was verified, and any pin tags. Then close it.

### Protecting downstream submodule pins

A downstream project pins exact commits of this repo as a submodule: each OpenRVDAS release tag records one `web_backend` commit. A sync rewrites `<project>` and `<project>_dev`, so those commits can end up on no branch or tag. GitHub may keep serving them by SHA for a while, but nothing guarantees it. Once one is garbage-collected, `git submodule update` fails for every release that pins it. This happened before the procedure existed, and the commits were recovered and tagged after the fact.

Before step 5, with the downstream repo checked out next to this one:

```bash
scripts/check-downstream-pins.sh ../openrvdas web_backend openrvdas
```

The script checks every downstream tag. It prints nothing when all pinned commits survive the sync (they're on another branch or a tag). For each `UNTAGGED` line, tag the commit and push the tag:

```bash
git tag -a openrvdas-v2.7.2-pin <sha> -m "web_backend commit pinned by OpenRVDAS v2.7.0 ... v2.7.2. Kept reachable after the vX.Y.Z sync (#NNN)."
git push origin openrvdas-v2.7.2-pin
```

Name the tag `<project>-<newest pinning release>-pin`, and list every pinning release in the message. A `MISSING` line means GitHub no longer has the commit. Raise that in the project repo, because those releases can't be checked out with submodules any more.

**Preferred long-term fix:** have the downstream project tag its submodule commits in this repo when it cuts a release (e.g. tag `openrvdas-v2.7.3` here when OpenRVDAS v2.7.3 is released). The pin is then protected from day one, and this check becomes a safety net.

## Notes

- The tags `v0.0.1`/`v0.0.2` predate this procedure. `v1.0.0` was tagged manually, ahead of this document existing, reconciling the `pyproject.toml` version field (which already read `1.0.0` with no corresponding tag) with actual release history — treat it as the first release under this procedure in spirit, even though this doc didn't exist yet when it was cut.
- This procedure covers `main` only. `<project>` branches (e.g. `openrvdas`) aren't independently tagged/released under this scheme — they track `main` via the rebase step above instead. Per-project releases, if ever needed, would be a separate addition to this doc.
- GitHub only auto-closes an issue referenced with a closing keyword (`Closes #N`) in a PR once the commit reaches the repository's **default branch** (`main`), not when the PR merges into `dev`, and even then doesn't always fire reliably. Per `CLAUDE.md`'s Branching & PR Workflow, don't rely on this — close the issue manually as soon as its `issue_NNN` → `dev`/`<project>_dev` PR merges, rather than waiting for a release.
