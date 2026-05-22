# Versioning And Release Channels

This doc explains how Automator versions are resolved by BMAD Method, npm, git
tags, and the repo-local plugin metadata. It is the maintainer checklist for
updating preview (`next`) and stable (`main`) installs.

## Current State

As of the `1.15.0` release:

- GitHub repo: `bmad-code-org/bmad-automator`
- default branch: `main`
- stable tag: `v1.15.0`
- preview tag: `v1.15.0-next.1`
- preview branch: `next/codex-runtime-support`
- npm package: `bmad-story-automator@1.15.0`
- official BMAD module code: `automator`

The official BMAD registry sets `automator` to `default_channel: next`.
For Automator, BMAD Method's `next` channel resolves to the repo default branch
HEAD, which is `main`. It does not mean the npm `next` dist-tag, the
`next/codex-runtime-support` branch, or the latest `*-next.*` git tag.

Use `--directory` for unattended installs. Some BMAD Method versions still prompt
for an installation directory even with `--yes` when `--directory` is omitted.

There are two unrelated `next` selectors in common commands:

- `bmad-method@next`: npm dist-tag for the BMAD Method installer package.
- `--next automator`: BMAD Method module channel selector for Automator, which
  resolves to Automator `main`.

## The Four Version Surfaces

Automator has four separate version surfaces. Keep them aligned intentionally.

| Surface | Purpose | Updated For Preview | Updated For Stable |
| --- | --- | --- | --- |
| Git tag | What BMAD Method installs for stable or pinned module installs | `vX.Y.Z-next.N` | `vX.Y.Z` |
| `main` branch | What BMAD Method installs for registry `next` | only after merge | yes |
| npm package | What `npx bmad-story-automator` installs | optional `--tag next` publish | optional `latest` publish |
| Repo metadata | What plugin/module/package manifests report | yes | yes |

BMAD Method module installs mostly use git, not the `bmad-story-automator` npm
package. The npm package is still important for users who run the standalone
installer directly:

```bash
npx bmad-story-automator /absolute/path/to/project
```

## Resolver Rules

BMAD Method resolves the official `automator` module this way:

- `--all-stable` or stable channel: highest pure semver git tag, such as `v1.15.0`
- `--pin automator=<tag>`: exact git tag, including prerelease tags
- `--next automator`: repo default branch HEAD, currently `main`
- unqualified `--modules automator`: registry default channel; currently `next`,
  so it also resolves to `main`
- `--custom-source <repo>@<branch-or-tag>`: clones the requested ref directly

Stable tags must be pure semver:

```text
v1.15.0
v1.15.1
v1.16.0
```

Preview tags must be prerelease semver:

```text
v1.16.0-next.0
v1.16.0-next.1
v1.16.0-next.2
```

Never move a pushed tag. Cut the next tag instead.

## User Install Commands

Stable, latest pure semver tag:

```bash
npx --yes bmad-method install \
  --modules automator \
  --all-stable \
  --tools codex \
  --yes \
  --directory "$PWD"
```

Stable, explicit tag:

```bash
npx --yes bmad-method install \
  --modules automator \
  --pin automator=v1.15.0 \
  --tools codex \
  --yes \
  --directory "$PWD"
```

Registry `next`, which means `main` HEAD:

```bash
npx --yes bmad-method install \
  --modules automator \
  --next automator \
  --tools codex \
  --yes \
  --directory "$PWD"
```

Preview tag, reproducible:

```bash
npx --yes bmad-method install \
  --modules automator \
  --pin automator=v1.16.0-next.0 \
  --tools codex \
  --yes \
  --directory "$PWD"
```

Preview branch, for unpublished branch testing:

```bash
npx --yes bmad-method install \
  --custom-source https://github.com/bmad-code-org/bmad-automator@next/codex-runtime-support \
  --tools codex \
  --yes \
  --directory "$PWD"
```

Custom-source installs can write official registry `next`/`main` metadata into
`_bmad/_config/manifest.yaml` when the source module code is still `automator`.
Verify the cache HEAD and installed runtime files, not only the manifest fields.

## Files To Bump

For a release version `X.Y.Z`, update these files:

- `package.json`: npm package version
- `.claude-plugin/plugin.json`: Claude plugin version
- `.claude-plugin/marketplace.json`: plugin entry version
- `skills/module.yaml`: `module_version`
- `skills/bmad-story-automator/pyproject.toml`: Python package version
- `skills/bmad-story-automator/src/story_automator/__init__.py`: runtime version
- docs or changelog entries that mention the shipped version

For preview versions, use semver in Node/plugin/module metadata and PEP 440 in
Python metadata:

| Git/npm/plugin/module | Python |
| --- | --- |
| `1.16.0-next.0` | `1.16.0.dev0` |
| `1.16.0-next.1` | `1.16.0.dev1` |
| `1.16.0` | `1.16.0` |

Before tagging, grep for stale version references:

```bash
rg -n '1\.15\.0|v1\.15\.0|1\.16\.0-next\.0|1\.16\.0\.dev0' \
  -g '!skills/bmad-story-automator/dist/**'
```

Adjust the search values for the release being prepared.

## Updating The Preview Version

Use this when testing the next Automator release before making it stable.

1. Start from current `main`.

```bash
git fetch origin main --tags
git switch -c next/<short-purpose> origin/main
```

For the Codex runtime preview, the historical branch was:

```bash
next/codex-runtime-support
```

2. Make the code changes and bump preview metadata.

Example next release after `1.15.0`:

```text
1.16.0-next.0
1.16.0.dev0
v1.16.0-next.0
```

3. Verify locally.

```bash
npm run verify
npm pack --dry-run
```

4. Commit the preview.

```bash
git add package.json .claude-plugin/plugin.json .claude-plugin/marketplace.json \
  skills/module.yaml skills/bmad-story-automator/pyproject.toml \
  skills/bmad-story-automator/src/story_automator/__init__.py
git commit -m "chore: prepare next preview"
```

Include changed source and docs in the same commit or in earlier commits on the
same branch.

5. Tag and push.

```bash
git tag -a v1.16.0-next.0 -m "v1.16.0-next.0"
git push origin next/<short-purpose>
git push origin v1.16.0-next.0
```

6. Verify the pushed refs.

```bash
git ls-remote --heads --tags origin next/<short-purpose> v1.16.0-next.0 main
```

7. Smoke the pinned preview install.

```bash
rm -rf /tmp/automator-next-smoke /tmp/automator-home-next /tmp/automator-npm-next
env HOME=/tmp/automator-home-next NPM_CONFIG_CACHE=/tmp/automator-npm-next \
  npx --yes bmad-method@next install \
    --modules automator \
    --pin automator=v1.16.0-next.0 \
    --tools codex \
    --yes \
    --directory /tmp/automator-next-smoke

rg -n 'name: automator|channel: pinned|version: v1\.16\.0-next\.0|sha:' \
  /tmp/automator-next-smoke/_bmad/_config/manifest.yaml
test -f /tmp/automator-next-smoke/.agents/skills/bmad-story-automator/src/story_automator/core/runtime_layout.py
test -f /tmp/automator-next-smoke/.agents/skills/bmad-story-automator/src/story_automator/core/stop_hooks.py
```

8. Optional: publish npm preview.

Use this only when `npx bmad-story-automator@next` should point at the preview.
This is separate from BMAD Method module installs.

```bash
npm publish --tag next
npm dist-tag ls bmad-story-automator
```

Use the secrets skill for npm auth material. Load credentials into the publish
shell, but never write tokens into files, docs, logs, or commit messages.

## Updating The Stable Main Version

Use this when promoting preview work to the stable release line.

1. Confirm release readiness.

```bash
git fetch origin main --tags
git ls-remote --heads --tags origin main 'v*'
npm view bmad-story-automator dist-tags version --json
```

Check that preview smoke tests passed and no release-blocking review is open.

2. Merge or land the preview branch on `main`.

```bash
git switch main
git pull --ff-only origin main
git merge --no-ff next/<short-purpose> -m "Merge branch 'next/<short-purpose>'"
```

If GitHub PR flow is being used, merge the PR and then pull `main` instead.

3. Bump stable metadata.

Example:

```text
1.16.0-next.0 -> 1.16.0
1.16.0.dev0 -> 1.16.0
```

Update every file listed in [Files To Bump](#files-to-bump).

4. Verify.

```bash
npm run verify
npm pack --dry-run
```

5. Commit the stable bump if it was not already part of the merge.

```bash
git add package.json .claude-plugin/plugin.json .claude-plugin/marketplace.json \
  skills/module.yaml skills/bmad-story-automator/pyproject.toml \
  skills/bmad-story-automator/src/story_automator/__init__.py
git commit -m "chore: release v1.16.0"
```

6. Tag and push.

```bash
git tag -a v1.16.0 -m "v1.16.0"
git push origin main
git push origin v1.16.0
```

7. Smoke stable, pinned stable, and registry `next`.

```bash
rm -rf /tmp/automator-stable-smoke /tmp/automator-pin-smoke /tmp/automator-main-smoke
rm -rf /tmp/automator-home-stable /tmp/automator-home-pin /tmp/automator-home-main
rm -rf /tmp/automator-npm-stable /tmp/automator-npm-pin /tmp/automator-npm-main

env HOME=/tmp/automator-home-stable NPM_CONFIG_CACHE=/tmp/automator-npm-stable \
  npx --yes bmad-method@next install \
    --modules automator \
    --all-stable \
    --tools codex \
    --yes \
    --directory /tmp/automator-stable-smoke

env HOME=/tmp/automator-home-pin NPM_CONFIG_CACHE=/tmp/automator-npm-pin \
  npx --yes bmad-method@next install \
    --modules automator \
    --pin automator=v1.16.0 \
    --tools codex \
    --yes \
    --directory /tmp/automator-pin-smoke

env HOME=/tmp/automator-home-main NPM_CONFIG_CACHE=/tmp/automator-npm-main \
  npx --yes bmad-method@next install \
    --modules automator \
    --next automator \
    --tools codex \
    --yes \
    --directory /tmp/automator-main-smoke
```

Expected manifest behavior:

- all-stable: `version: v1.16.0`, `channel: stable`
- pinned stable: `version: v1.16.0`, `channel: pinned`
- registry next: `version: main`, `channel: next`, SHA equals current `main`

8. Optional: publish npm stable.

Use this when the standalone package should expose the same stable version.

```bash
npm publish
npm dist-tag ls bmad-story-automator
```

Expected after stable publish:

```text
latest: 1.16.0
```

If a previous npm preview was published, decide whether to keep, advance, or
remove the `next` dist-tag:

```bash
npm dist-tag add bmad-story-automator@1.16.0-next.1 next
npm dist-tag rm bmad-story-automator next
```

## Updating `main` Without A Stable Tag

Because the official registry default is `next`, every push to `main` affects
unqualified BMAD Method installs:

```bash
npx --yes bmad-method install --modules automator --tools codex --yes --directory "$PWD"
```

Only merge changes to `main` when they are acceptable for registry `next` users.
For experimental work, use a preview branch and pinned prerelease tag first.

If `main` receives a fix that should not become stable yet:

- do not create a pure semver tag
- keep stable users on the last `vX.Y.Z` tag
- tell testers to use registry `next` or a pinned preview tag
- verify with `--next automator` and with `--all-stable` to confirm the split

## Rollback Rules

Do not move or delete published tags.

If a preview tag is bad:

1. Fix the preview branch.
2. Bump to the next prerelease, such as `v1.16.0-next.1`.
3. Push the new tag.
4. Tell testers to pin the new tag.

If `main` is bad before a stable tag:

1. Revert or fix `main`.
2. Push `main`.
3. Verify `--next automator`.
4. Stable users remain on the previous pure semver tag.

If a stable tag is bad:

1. Do not move the bad tag.
2. Revert or fix from `main`.
3. Bump to a patch release, such as `v1.16.1`.
4. Tag and publish the patch.
5. Tell users to install `--all-stable` or pin the patch tag.

## Quick Decision Table

| Need | Action |
| --- | --- |
| Reproducible tester preview | prerelease git tag plus `--pin automator=vX.Y.Z-next.N` |
| Test unpublished branch content | `--custom-source <repo>@<branch>` and verify cache/runtime files |
| Update registry `next` install | merge to `main` |
| Update stable BMAD Method install | create pure semver tag `vX.Y.Z` |
| Update standalone `npx bmad-story-automator` stable | `npm publish` |
| Update standalone npm preview | `npm publish --tag next` |
| Roll back preview | fix forward with next prerelease tag |
| Roll back stable | patch release tag; never move old tag |

## Release Evidence To Record

For each preview or stable release, record:

- branch name and commit SHA
- tag name, tag object SHA, and target SHA
- changed version files
- `npm run verify` result
- `npm pack --dry-run` result
- install smoke commands and manifest excerpts
- npm publish status, including skipped publishes
- rollback note and known installer caveats

The historical phase docs under `docs/plans/versioning/` contain the original
`1.15.0` rollout evidence. This doc is the forward-looking maintenance flow.
