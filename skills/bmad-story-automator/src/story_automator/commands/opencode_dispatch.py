"""OpenCode-native task dispatch command.

When the automator detects an OpenCode harness, instead of spawning a tmux
session with a CLI command, it generates a task dispatch payload that the
orchestrating OpenCode agent reads and passes to its native task tool.

Usage:
    story-automator opencode-dispatch <step> <story_id> [--model MODEL] [--state-file PATH] [extra_instruction]

Model resolution order:
    1. --model CLI flag (explicit override)
    2. opencode.models.<step> from _bmad/bmm/config.yaml
    3. Empty string = OpenCode uses its default model
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from story_automator.core.agent_config import normalize_model
from story_automator.core.prompt_rendering import render_step_prompt
from story_automator.core.runtime_policy import PolicyError, load_runtime_policy, step_contract
from story_automator.core.runtime_layout import runtime_provider
from story_automator.core.utils import (
    get_project_root,
    print_json,
    read_text,
    strip_inline_yaml_comment,
    unquote_scalar,
)

# Default subagent type when not overridden by config
DEFAULT_SUBAGENT_TYPE = "coder"


def cmd_opencode_dispatch(args: list[str]) -> int:
    """Generate an OpenCode task dispatch payload.

    Reads the step, story_id, optional model, state-file, and extra
    instruction from args. Resolves model from:
        1. --model CLI flag
        2. opencode.models.<step> from config.yaml
        3. Empty string = OpenCode uses its default model

    Outputs a JSON payload suitable for the OpenCode task tool.
    """
    if not args or args[0] in {"--help", "-h"}:
        _usage(0 if args and args[0] in {"--help", "-h"} else 1)
        return 0 if args and args[0] in {"--help", "-h"} else 1

    step = args[0]
    story_id = args[1] if len(args) > 1 else ""
    if not story_id:
        print("story_id is required", file=sys.stderr)
        return 1

    model = ""
    state_file = ""
    extra = ""
    tail = args[2:]
    idx = 0
    while idx < len(tail):
        if tail[idx] == "--model" and idx + 1 < len(tail):
            model = tail[idx + 1]
            idx += 2
            continue
        if tail[idx] == "--state-file" and idx + 1 < len(tail):
            state_file = tail[idx + 1]
            idx += 2
            continue
        extra = f"{extra} {tail[idx]}".strip()
        idx += 1

    # Resolve model: CLI flag > config.yaml > empty (opencode default)
    if not model:
        model = _resolve_model_from_config(step)

    root = get_project_root()
    story_prefix = story_id.replace(".", "-")

    try:
        policy = load_runtime_policy(root, state_file=state_file)
        contract = step_contract(policy, step)
        prompt = render_step_prompt(
            contract,
            project_root=root,
            story_id=story_id,
            story_prefix=story_prefix,
            extra_instruction=extra,
        )
    except (OSError, PolicyError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    configured_subagent_type = _resolve_subagent_type_from_config()
    if configured_subagent_type:
        subagent_type = configured_subagent_type
    else:
        # Map step names to subagent_type for the task tool
        subagent_map = {
            "create": "coder",
            "dev": "coder",
            "auto": "coder",
            "review": "reviewer",
            "retro": "coder",
        }
        subagent_type = subagent_map.get(step, DEFAULT_SUBAGENT_TYPE)

    payload = {
        "dispatch": "opencode_task",
        "step": step,
        "storyId": story_id,
        "prompt": prompt,
        "model": model,
        "subagent_type": subagent_type,
    }
    print_json(payload)
    return 0


def _resolve_model_from_config(step: str) -> str:
    """Read opencode.models.<step> from _bmad/bmm/config.yaml.

    Uses the project's simple line-by-line YAML parser (no PyYAML dependency).

    Resolution order:
        1. opencode.models.<step> (per-step override)
        2. opencode.models.orchestrator (global override)
        3. "" (empty = opencode uses its default)

    Returns normalized model ID or "" for opencode default.
    """
    root = get_project_root()
    config_path = Path(root) / "_bmad" / "bmm" / "config.yaml"
    if not config_path.is_file():
        return ""

    try:
        raw = read_text(config_path)
    except (OSError, UnicodeDecodeError):
        return ""

    # Simple parser: extract opencode.models.<key> values
    # Config structure:
    #   opencode:
    #     models:
    #       orchestrator: "model-name"
    #       create: "model-name"
    #       dev: "model-name"
    #       auto: "model-name"
    #       review: "model-name"
    #       retro: "model-name"
    in_opencode = False
    in_models = False
    models: dict[str, str] = {}

    for raw_line in raw.splitlines():
        cleaned = strip_inline_yaml_comment(raw_line).rstrip()
        line = cleaned.strip()
        if not line or ":" not in line:
            continue

        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")

        # Track nesting: opencode > models
        if key == "opencode":
            in_opencode = True
            in_models = False
            continue
        if in_opencode and key == "models":
            in_models = True
            continue

        # Reset nesting when indent level decreases (new top-level key)
        is_top_level = raw_line == raw_line.lstrip(" \t")
        if is_top_level:
            in_opencode = False
            in_models = False

        # Capture model values under opencode.models
        if in_opencode and in_models and value:
            models[key] = value

    # Per-step model override first
    step_model = models.get(step)
    if step_model:
        return normalize_model(step_model)

    # Fallback to orchestrator-level model
    orchestrator_model = models.get("orchestrator")
    if orchestrator_model:
        return normalize_model(orchestrator_model)

    return ""


def _resolve_subagent_type_from_config() -> str:
    """Read opencode.subagent_type from _bmad/bmm/config.yaml."""
    root = get_project_root()
    config_path = Path(root) / "_bmad" / "bmm" / "config.yaml"
    if not config_path.is_file():
        return ""

    try:
        raw = read_text(config_path)
    except (OSError, UnicodeDecodeError):
        return ""

    in_opencode_block = False
    for raw_line in raw.splitlines():
        cleaned = strip_inline_yaml_comment(raw_line).rstrip()
        line = cleaned.strip()
        if not line:
            continue

        is_top_level = raw_line == raw_line.lstrip(" \t")
        if is_top_level and line == "opencode:":
            in_opencode_block = True
            continue
        if is_top_level and in_opencode_block:
            in_opencode_block = False

        if not in_opencode_block or ":" not in line:
            continue

        key, value = line.split(":", 1)
        if key.strip() == "subagent_type":
            return unquote_scalar(value.strip())

    return ""


def _usage(code: int) -> int:
    target = sys.stderr if code else sys.stdout
    print("Usage: opencode-dispatch <step> <story_id> [--model MODEL] [--state-file PATH] [extra_instruction]", file=target)
    print("", file=target)
    print("Generate an OpenCode task dispatch payload (JSON) for native execution.", file=target)
    print("", file=target)
    print("Steps: create, dev, auto, review, retro", file=target)
    print("", file=target)
    print("Model resolution:", file=target)
    print("  1. --model CLI flag (explicit override)", file=target)
    print("  2. opencode.models.<step> from _bmad/bmm/config.yaml", file=target)
    print("  3. Empty string = OpenCode uses its default model", file=target)
    return code
