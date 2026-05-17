#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  cat <<'EOF'
Usage: ./install.sh <bmad-project-root>

Installs the portable skill bundle into each supported skill root that
contains complete required dependency skill entrypoints:
  <installed-skill-root>/bmad-story-automator
  <installed-skill-root>/bmad-story-automator-review

Supported skill roots:
  .agents/skills
  .claude/skills
  .codex/skills

If more than one supported root is complete, all complete roots are updated.

The Python helper runtime is installed inside each installed skill root:
  <installed-skill-root>/bmad-story-automator/scripts/story-automator
EOF
}

err() {
  echo "Error: $*" >&2
  exit 1
}

warn() {
  echo "Warn: $*" >&2
}

resolve_abs_dir() {
  local input="$1"
  [ -d "$input" ] || err "Directory not found: $input"
  cd "$input" >/dev/null 2>&1 && pwd
}

skill_file() {
  local skill_name="$1"
  printf '%s/%s/SKILL.md\n' "$TARGET_SKILLS_REL" "$skill_name"
}

backup_if_exists() {
  local path="$1"
  if [ -e "$path" ]; then
    local backup="${path}.backup-$(date -u +%Y%m%dT%H%M%SZ)"
    mv "$path" "$backup"
    echo "Backup: ${backup#$TARGET_ROOT/}"
  fi
}

backup_legacy_story_automator_installs() {
  local legacy_path
  local legacy_paths=(
    "$TARGET_ROOT/_bmad/bmm/4-implementation/bmad-story-automator"
    "$TARGET_ROOT/_bmad/bmm/4-implementation/story-automator"
    "$TARGET_ROOT/_bmad/bmm/4-implementation/story-automator-py"
    "$TARGET_ROOT/_bmad/bmm/4-implementation/bmad-story-automator-review"
    "$TARGET_ROOT/_bmad/bmm/4-implementation/story-automator-review"
    "$TARGET_ROOT/_bmad/bmm/workflows/4-implementation/bmad-story-automator"
    "$TARGET_ROOT/_bmad/bmm/workflows/4-implementation/story-automator"
    "$TARGET_ROOT/_bmad/bmm/workflows/4-implementation/bmad-story-automator-review"
    "$TARGET_ROOT/_bmad/bmm/workflows/4-implementation/story-automator-review"
  )

  for legacy_path in "${legacy_paths[@]}"; do
    backup_if_exists "$legacy_path"
  done
}

wrapper_points_to_skill_tree() {
  local shim="$1"
  grep -Eq '\.(claude|agents|codex)/skills/' "$shim"
}

wrapper_points_to_legacy_target() {
  local shim="$1"
  grep -Eq '_bmad/bmm/(4-implementation|workflows/4-implementation)|_bmad/tea/|/bmad-bmm-|/bmad-tea-' "$shim"
}

remove_obsolete_command_shim_if_legacy() {
  local shim="$1"
  [ -f "$shim" ] || return 0
  if wrapper_points_to_skill_tree "$shim"; then
    return 0
  fi
  if wrapper_points_to_legacy_target "$shim"; then
    rm -f "$shim"
    echo "Removed obsolete command shim: ${shim#$TARGET_ROOT/}"
  fi
}

cleanup_obsolete_command_shims() {
  local command_dir="$TARGET_ROOT/.claude/commands"
  local shim

  rm -f "$command_dir/bmad-bmm-story-automator-py.md"

  for shim in \
    "$command_dir/bmad-bmm-story-automator.md" \
    "$command_dir/bmad-bmm-story-automator-review.md" \
    "$command_dir/bmad-bmm-create-story.md" \
    "$command_dir/bmad-bmm-dev-story.md" \
    "$command_dir/bmad-bmm-retrospective.md" \
    "$command_dir/bmad-bmm-qa-generate-e2e-tests.md" \
    "$command_dir/bmad-tea-testarch-automate.md"; do
    remove_obsolete_command_shim_if_legacy "$shim"
  done
}

resolve_workflow_path() {
  local candidate
  for candidate in "$@"; do
    if [ -f "$TARGET_ROOT/$candidate" ]; then
      echo "$candidate"
      return 0
    fi
  done
  return 1
}

resolve_required_skill() {
  local skill_name="$1"
  local skill_path
  skill_path="$(skill_file "$skill_name")"
  [ -f "$TARGET_ROOT/$skill_path" ] || err "Required skill file missing: $skill_path"
  printf '%s\n' "$skill_path"
}

resolve_optional_skill() {
  local skill_name="$1"
  local skill_path

  skill_path="$(skill_file "$skill_name")"
  if [ -f "$TARGET_ROOT/$skill_path" ]; then
    printf '%s\n' "$skill_path"
    return 0
  fi

  if resolve_workflow_path \
    "$TARGET_SKILLS_REL/$skill_name/workflow.md" \
    "$TARGET_SKILLS_REL/$skill_name/workflow.yaml" >/dev/null; then
    warn "Optional skill incomplete: missing $TARGET_SKILLS_REL/$skill_name/SKILL.md. Story-automator still installs, but run with 'Skip Automate' enabled unless you fix that skill."
  fi
  return 1
}

skill_root_has_required_skill_files() {
  local skills_root_rel="$1"
  [ -f "$TARGET_ROOT/$skills_root_rel/bmad-create-story/SKILL.md" ] &&
    [ -f "$TARGET_ROOT/$skills_root_rel/bmad-dev-story/SKILL.md" ] &&
    [ -f "$TARGET_ROOT/$skills_root_rel/bmad-retrospective/SKILL.md" ]
}

skill_root_has_required_entrypoints() {
  local skills_root_rel="$1"
  skill_root_has_required_skill_files "$skills_root_rel"
}

skill_root_has_any_required_asset() {
  local skills_root_rel="$1"
  local skill_name
  for skill_name in bmad-create-story bmad-dev-story bmad-retrospective; do
    [ -e "$TARGET_ROOT/$skills_root_rel/$skill_name/SKILL.md" ] && return 0
    [ -e "$TARGET_ROOT/$skills_root_rel/$skill_name/workflow.md" ] && return 0
    [ -e "$TARGET_ROOT/$skills_root_rel/$skill_name/workflow.yaml" ] && return 0
  done
  return 1
}

collect_target_skills_roots() {
  local candidate
  local candidates=(".agents/skills" ".claude/skills" ".codex/skills")

  for candidate in "${candidates[@]}"; do
    if skill_root_has_required_entrypoints "$candidate"; then
      TARGET_SKILLS_RELS+=("$candidate")
    fi
  done
}

select_single_incomplete_diagnostic_root() {
  local candidate
  local found=""
  local candidates=(".agents/skills" ".claude/skills" ".codex/skills")

  for candidate in "${candidates[@]}"; do
    if skill_root_has_any_required_asset "$candidate"; then
      if [ -n "$found" ]; then
        return 1
      fi
      found="$candidate"
    fi
  done

  if [ -n "$found" ]; then
    printf '%s\n' "$found"
    return 0
  fi

  return 1
}

install_skill_root() {
  TARGET_SKILLS_REL="$1"

  local target_skills="$TARGET_ROOT/$TARGET_SKILLS_REL"
  local target_story="$target_skills/bmad-story-automator"
  local target_story_review="$target_skills/bmad-story-automator-review"
  local create_story_path
  local dev_story_path
  local retrospective_path
  local optional_automate_skill
  local optional_automate_path=""

  optional_automate_skill="$(skill_file "bmad-qa-generate-e2e-tests")"

  create_story_path="$(resolve_required_skill "bmad-create-story")"
  dev_story_path="$(resolve_required_skill "bmad-dev-story")"
  retrospective_path="$(resolve_required_skill "bmad-retrospective")"

  if ! optional_automate_path="$(resolve_optional_skill "bmad-qa-generate-e2e-tests")"; then
    if [ ! -f "$TARGET_ROOT/$optional_automate_skill" ]; then
      warn "Optional skill not found: $TARGET_SKILLS_REL/bmad-qa-generate-e2e-tests. Story-automator still installs, but run with 'Skip Automate' enabled unless you install that skill."
    fi
  fi

  backup_if_exists "$target_story"
  backup_if_exists "$target_story_review"

  mkdir -p "$target_story" "$target_story_review"
  cp -a "$STORY_SOURCE"/. "$target_story"/
  cp -a "$STORY_REVIEW_SOURCE"/. "$target_story_review"/
  chmod +x "$target_story/scripts/story-automator"

  echo "Installed skill root: $TARGET_SKILLS_REL"
  echo "Installed story-automator skill into: $target_story"
  echo "Installed story-automator-review skill into: $target_story_review"
  echo "Runtime helper: $target_story/scripts/story-automator"
  echo "Verified dependency skill entrypoints:"
  echo "  create-story: $create_story_path"
  echo "  dev-story: $dev_story_path"
  echo "  retrospective: $retrospective_path"
  if [ -n "$optional_automate_path" ]; then
    echo "  qa-generate-e2e-tests: $optional_automate_path"
  fi
}

if [ $# -ne 1 ]; then
  usage
  exit 1
fi

TARGET_ROOT="$(resolve_abs_dir "$1")"
TARGET_BMAD="$TARGET_ROOT/_bmad"
TARGET_SKILLS_REL=""
TARGET_SKILLS_RELS=()
SKILL_SOURCE_ROOT="$SCRIPT_DIR/skills"
STORY_SOURCE="$SKILL_SOURCE_ROOT/bmad-story-automator"
STORY_REVIEW_SOURCE="$SKILL_SOURCE_ROOT/bmad-story-automator-review"

[ -d "$TARGET_BMAD" ] || err "Target is not a BMAD project: missing $TARGET_BMAD"
[ -d "$SKILL_SOURCE_ROOT" ] || err "Missing skills root: $SKILL_SOURCE_ROOT"
[ -d "$STORY_SOURCE" ] || err "Missing story-automator skill: $STORY_SOURCE"
[ -d "$STORY_REVIEW_SOURCE" ] || err "Missing story-automator-review skill: $STORY_REVIEW_SOURCE"
[ -f "$STORY_SOURCE/SKILL.md" ] || err "Missing story-automator SKILL.md: $STORY_SOURCE/SKILL.md"
[ -f "$STORY_SOURCE/scripts/story-automator" ] || err "Missing runtime helper: $STORY_SOURCE/scripts/story-automator"
[ -d "$STORY_SOURCE/src/story_automator" ] || err "Missing runtime package dir: $STORY_SOURCE/src/story_automator"
[ -f "$STORY_SOURCE/pyproject.toml" ] || err "Missing runtime pyproject: $STORY_SOURCE/pyproject.toml"
[ -f "$STORY_REVIEW_SOURCE/SKILL.md" ] || err "Missing review SKILL.md: $STORY_REVIEW_SOURCE/SKILL.md"

collect_target_skills_roots

if [ "${#TARGET_SKILLS_RELS[@]}" -eq 0 ]; then
  if TARGET_SKILLS_REL="$(select_single_incomplete_diagnostic_root)"; then
    resolve_required_skill "bmad-create-story" >/dev/null
    resolve_required_skill "bmad-dev-story" >/dev/null
    resolve_required_skill "bmad-retrospective" >/dev/null
  fi
  err "Required dependency skills not found under any supported skill root (.agents/skills, .claude/skills, .codex/skills). Install bmad-create-story, bmad-dev-story, and bmad-retrospective under at least one supported root before running this installer."
fi

backup_legacy_story_automator_installs

for TARGET_SKILLS_REL in "${TARGET_SKILLS_RELS[@]}"; do
  install_skill_root "$TARGET_SKILLS_REL"
done

cleanup_obsolete_command_shims

echo "Legacy command wrappers are not generated; invoke the bmad-story-automator skill directly."
