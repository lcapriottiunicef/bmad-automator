# Installation And Layout

This doc explains what `npx bmad-story-automator` installs, what it requires, and how it handles migration from older installs.

## Installer Flow

```mermaid
flowchart TD
    A["Run install.sh <project>"] --> B["Verify target is a BMAD project"]
    B --> C["Verify root skills exist in this repo"]
    C --> D["Verify required sibling skills exist in target project"]
    D --> E["Resolve optional QA skill if present"]
    E --> F["Backup current installs and legacy story-automator paths"]
    F --> G["Copy skills into each qualifying skill root"]
    G --> H["Remove obsolete legacy command shims"]
    H --> I["Print installed paths and verified sibling entrypoints"]
```

## Target Paths

The npm installer writes into every qualifying skill root.

Terminology:

- Supported roots are `.agents/skills`, `.claude/skills`, and `.codex/skills`.
- Qualifying roots are supported roots that contain the required dependency skill entrypoints (`SKILL.md`).
- Installed skill roots are the qualifying roots where `bmad-story-automator` and `bmad-story-automator-review` are copied.

Supported roots:

- `.agents/skills`
- `.claude/skills`
- `.codex/skills`

Unlike the older workflow-root layout, this Python port installs into the pure skill tree.
Use `.agents/skills` when you want a shared skill tree that multiple runtimes can see. Use `.claude/skills` or `.codex/skills` when provider-specific isolation is useful. Runtime provider/layout is still resolved separately from install targets: explicit provider env wins first, then active skill-root context, then project-layout fallback. In that fallback, active `.agents` or `.codex` roots map to Codex-style hook/config layout, while `.claude` maps to Claude-style layout.

Installer behavior and runtime behavior are different:

- The installer has no precedence among qualifying roots; it updates every qualifying root it finds.
- Runtime resolution does have an order for active execution context: explicit `BMAD_SKILLS_ROOT`, current installed helper root, project `.agents`, project `.claude`, project `.codex`, then home roots.

Claude-only, Codex-only, and mixed projects are supported. If more than one root contains all required dependency `SKILL.md` files, the installer updates each qualifying root. If a root is present but missing required skill entrypoints while another root qualifies, the incomplete root is left unchanged.

The repo-local source skills live under `skills/`. The installer copies those same directly usable skill folders into each qualifying root.

## Installed Tree

```mermaid
flowchart TD
    A["<installed-skill-root>/"] --> B["bmad-story-automator/"]
    A --> C["bmad-story-automator-review/"]
    B --> D["SKILL.md"]
    B --> E["workflow.md"]
    B --> F["steps-c/ steps-v/ steps-e/"]
    B --> G["data/ templates/"]
    B --> H["scripts/story-automator"]
    B --> I["src/story_automator/"]
    B --> J["pyproject.toml README.md LICENSE"]
    C --> K["SKILL.md workflow.yaml instructions.xml checklist.md"]
```

## Required Inputs

The target project must already contain these BMAD skills under at least one supported skill root:

- `bmad-create-story`
- `bmad-dev-story`
- `bmad-retrospective`

Only the `SKILL.md` entrypoint is required for sibling BMAD skills. Extra files such as `workflow.md`, `workflow.yaml`, checklists, and templates are resolved when present, but install must not depend on those internal layouts.

If the required dependency skills are missing from all supported roots, the installer exits before copying anything and reports the supported roots that can satisfy the dependency requirement.

Optional:

- `bmad-qa-generate-e2e-tests`

If the optional QA skill is missing:

- install still succeeds
- a warning is printed
- the operator should run with `Skip Automate = true`

## Migration And Backups

Before copying new content, the installer backs up the existing install targets under each qualifying skill root:

- existing `bmad-story-automator`
- existing `bmad-story-automator-review`
- legacy installs under `_bmad/bmm/4-implementation/...`
- legacy installs under `_bmad/bmm/workflows/4-implementation/...`

The goal is migration safety, not in-place overwrite.

## Command Shim Cleanup

The installer removes obsolete shims only when they still target legacy workflow-root installs.

Important nuance:

- this repo does not generate new Claude command wrappers
- it only cleans up stale legacy wrappers
- the intended entrypoint is the installed skill itself

## Runtime Entry

The installed helper entrypoint is:

```text
<installed-skill-root>/bmad-story-automator/scripts/story-automator
```

Codex uses the active installed skill root for this helper, but writes hook/config state to `.codex/hooks.json` and `.codex/config.toml`.

That wrapper:

- sets `PYTHONPATH` to the bundled `src`
- runs `python3 -m story_automator`

## Runtime Provider Resolution

Top-level runtime behavior is resolved separately from child-agent selection:

- runtime provider decides hook/config syntax
- child-agent selection decides whether spawned work uses Claude or Codex

Provider resolution checks, in order:

1. `BMAD_RUNTIME_PROVIDER`
2. `STORY_AUTOMATOR_RUNTIME_PROVIDER`
3. installed/current story-automator skill root
4. project-local runtime layout fallback

`AI_AGENT` is only for spawned child sessions. It does not decide whether `ensure-stop-hook` writes `.claude/settings.json` or `.codex/{config.toml,hooks.json}`.

## Repo Layout

Repo layout:

- `skills/` for directly copyable skill folders
- `skills/bmad-story-automator/` for the main skill and bundled Python runtime
- `skills/bmad-story-automator-review/` for the bundled review skill
- `.claude-plugin/plugin.json` for Claude Code plugin loading
- `install.sh` for installation logic
- `bin/bmad-story-automator` for npm entrypoint
- `scripts/` for repo-level smoke verification

No installer-only payload tree exists. The installer copies the same skill folders that can be manually copied into `.claude/skills/`.

## Operator Notes

- install target must be a BMAD project with `_bmad/`
- required sibling skill `SKILL.md` files must already exist under `.agents/skills`, `.claude/skills`, or `.codex/skills`
- the review workflow is installed alongside the main orchestrator because review gating is part of completion semantics
- Windows support currently means Windows via WSL, not native Windows shells

## Read Next

- [How It Works](./how-it-works.md)
- [CLI Reference](./cli-reference.md)
- [Development](./development.md)
