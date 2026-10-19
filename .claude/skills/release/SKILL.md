---
name: release
description: Prepare a fantasyfb release. Bumps the version in pyproject.toml, turns CHANGELOG.md's [Unreleased] section into a dated version section, drafts notes/release_vX.Y.Z.md, and opens a release PR. Stops for explicit approval before creating the GitHub release, since publishing a release pushes the package to PyPI. Use when the user asks to "cut a release", "bump the version", "prep vX.Y.Z", or runs /release.
---

# Release

Publishing a GitHub release triggers `.github/workflows/publish.yml`, which builds and uploads to **PyPI**. That can't be undone (a version number can never be reused on PyPI), so this skill prepares everything and then stops for sign-off.

The version lives only in `pyproject.toml`; `fantasyfb.__version__` reads it from package metadata.

## Procedure

1. **Check the starting state.** On an up-to-date `main` with a clean tree (`git fetch origin && git status`). Read `CHANGELOG.md`'s `## [Unreleased]` section. If it's empty, stop and tell the user there's nothing to release. Also compare against `git log <last tag>..origin/main --oneline` (`git tag --sort=-v:refname | head -1`) and flag any merged PR that changes behavior but has no changelog entry; offer to add them with `/changelog-entry` first.

2. **Propose the version number** using semver on the Unreleased contents: patch for fixes only, minor for anything in Added or a breaking change while the package is still 0.x, and say why. Let the user confirm or override.

3. **Make the release branch and edits** on `release-vX.Y.Z` off `origin/main`:
   - `pyproject.toml`: bump `version`.
   - `CHANGELOG.md`: rename the Unreleased contents into `## [X.Y.Z] — YYYY-MM-DD` (today's date, matching the existing heading format including its dash), and leave a fresh empty `## [Unreleased]` above it. An optional one-line summary under the version heading is fine when the release has a theme.
   - Commit as `Bump version to X.Y.Z`.

4. **Draft `notes/release_vX.Y.Z.md`** (the `notes/` folder is gitignored, so this stays local and becomes the GitHub release body). Follow the shape of the most recent `notes/release_v*.md`:
   - `# fantasyfb vX.Y.Z`, then a one-sentence summary.
   - A `pip install --upgrade fantasyfb` code block.
   - `## Highlights`: a few bullets written for users rather than maintainers, grouping related changelog entries, leading with impact rather than internals. Call out any **Breaking change** explicitly.
   - Close with the link to the full CHANGELOG.md on GitHub.
   - No em-dashes in prose. Say "salary cap draft", never "auction".

5. **Show the user** the version diff, the new CHANGELOG section, and the release notes draft. Revise until they approve.

6. **Push and open the release PR** (`gh pr create --base main`), titled `Release vX.Y.Z`, with the release notes as the PR body plus the standard attribution footer.

7. **Stop.** Tell the user the PR is ready to merge. Only after they've merged it **and** explicitly asked you to publish:
   - Optionally offer a TestPyPI dry run first: `gh workflow run publish.yml` (manual dispatch publishes to TestPyPI only).
   - Publish with `gh release create vX.Y.Z --target main --title "fantasyfb vX.Y.Z" --notes-file notes/release_vX.Y.Z.md`, then watch the run with `gh run watch` and report whether the PyPI upload succeeded.

## Guardrails

- Never create a tag or GitHub release without an explicit "publish" from the user after the release PR is merged. Approving the notes is not approval to publish.
- Never force-push, delete, or re-point an existing tag.
- If the publish workflow fails, report the failing step's log; don't retry by deleting and recreating the release.
