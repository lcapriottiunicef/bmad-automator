from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from story_automator.core.agent_config import (
    AgentTaskConfig,
    build_agents_file,
    parse_agent_config_json,
    resolve_agent_for_task,
    resolve_agents,
)
from story_automator.core.tmux_runtime import agent_cli
from story_automator.commands.orchestrator import cmd_orchestrator_helper
from story_automator.commands.orchestrator_epic_agents import (
    parse_agent_config,
    resolve_agent,
)
from story_automator.commands.state import cmd_build_state_doc
from story_automator.commands.tmux import _build_cmd


REPO_ROOT = Path(__file__).resolve().parents[1]


class AgentCliModelTests(unittest.TestCase):
    def test_agent_cli_without_model_unchanged(self) -> None:
        self.assertEqual(agent_cli("claude"), "claude --dangerously-skip-permissions")
        self.assertEqual(agent_cli("codex"), "codex exec")

    def test_agent_cli_with_model_for_claude(self) -> None:
        self.assertEqual(
            agent_cli("claude", "claude-sonnet-4-6"),
            "claude --dangerously-skip-permissions --model claude-sonnet-4-6",
        )

    def test_agent_cli_with_model_for_codex(self) -> None:
        self.assertEqual(
            agent_cli("codex", "gpt-5.5"),
            "codex exec --model gpt-5.5",
        )

    def test_agent_cli_quotes_model_with_special_chars(self) -> None:
        # 1M-context variant uses brackets which the shell would interpret
        self.assertIn(
            "'claude-opus-4-7[1m]'",
            agent_cli("claude", "claude-opus-4-7[1m]"),
        )

    def test_agent_cli_treats_empty_model_as_absent(self) -> None:
        self.assertEqual(agent_cli("claude", ""), "claude --dangerously-skip-permissions")
        self.assertEqual(agent_cli("claude", "   "), "claude --dangerously-skip-permissions")


class CoreAgentConfigModelTests(unittest.TestCase):
    def test_per_task_model_is_resolved(self) -> None:
        config = parse_agent_config_json(
            json.dumps(
                {
                    "defaultPrimary": "claude",
                    "defaultFallback": False,
                    "perTask": {
                        "review": {"primary": "claude", "fallback": False, "model": "claude-sonnet-4-6"},
                        "dev": {"primary": "claude", "fallback": False, "model": "claude-opus-4-7[1m]"},
                    },
                }
            )
        )
        primary, fallback, model = resolve_agent_for_task(config, "medium", "review")
        self.assertEqual((primary, fallback, model), ("claude", "false", "claude-sonnet-4-6"))
        _primary, _fallback, model = resolve_agent_for_task(config, "medium", "dev")
        self.assertEqual(model, "claude-opus-4-7[1m]")

    def test_complexity_override_wins_over_per_task(self) -> None:
        config = parse_agent_config_json(
            json.dumps(
                {
                    "perTask": {"review": {"primary": "claude", "model": "claude-opus-4-7"}},
                    "complexityOverrides": {
                        "high": {"review": {"primary": "claude", "model": "claude-sonnet-4-6"}}
                    },
                }
            )
        )
        _, _, model = resolve_agent_for_task(config, "high", "review")
        self.assertEqual(model, "claude-sonnet-4-6")
        _, _, model = resolve_agent_for_task(config, "medium", "review")
        self.assertEqual(model, "claude-opus-4-7")

    def test_default_model_applies_when_no_override(self) -> None:
        config = parse_agent_config_json(
            json.dumps({"defaultPrimary": "claude", "defaultModel": "claude-opus-4-7[1m]"})
        )
        _, _, model = resolve_agent_for_task(config, "medium", "dev")
        self.assertEqual(model, "claude-opus-4-7[1m]")

    def test_model_sentinel_values_treated_as_unset(self) -> None:
        for sentinel in ("auto", "default", "false", "none", "null", ""):
            config = parse_agent_config_json(
                json.dumps({"perTask": {"dev": {"primary": "claude", "model": sentinel}}})
            )
            _, _, model = resolve_agent_for_task(config, "medium", "dev")
            self.assertEqual(model, "", f"sentinel {sentinel!r} should resolve to empty")

    def test_build_agents_file_includes_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            state_file = tmp_path / "state.md"
            state_file.write_text(
                "---\nepic: 9\nepicName: Trust & Safety\n---\n", encoding="utf-8"
            )
            complexity_file = tmp_path / "complexity.json"
            complexity_file.write_text(
                json.dumps(
                    {
                        "stories": [
                            {"storyId": "9.1", "title": "Build SafetyShield", "complexity": {"level": "low"}},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            output = tmp_path / "agents.md"
            config_json = json.dumps(
                {
                    "defaultPrimary": "claude",
                    "perTask": {
                        "review": {"primary": "claude", "model": "claude-sonnet-4-6"},
                        "dev": {"primary": "claude", "model": "claude-opus-4-7[1m]"},
                    },
                }
            )
            build_agents_file(state_file, complexity_file, output, config_json)
            text = output.read_text(encoding="utf-8")
            payload = json.loads(text.split("```json", 1)[1].split("```", 1)[0])
            tasks = payload["stories"][0]["tasks"]
            self.assertEqual(tasks["review"]["model"], "claude-sonnet-4-6")
            self.assertEqual(tasks["dev"]["model"], "claude-opus-4-7[1m]")
            self.assertNotIn("model", tasks["create"])
            self.assertNotIn("model", tasks["auto"])

    def test_resolve_agents_returns_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            agents_file = Path(tmp) / "agents.md"
            payload = {
                "version": "1.0.0",
                "stories": [
                    {
                        "storyId": "9.1",
                        "title": "x",
                        "complexity": "low",
                        "tasks": {
                            "review": {"primary": "claude", "fallback": False, "model": "claude-sonnet-4-6"},
                            "dev": {"primary": "claude", "fallback": False},
                        },
                    }
                ],
            }
            agents_file.write_text("```json\n" + json.dumps(payload) + "\n```\n", encoding="utf-8")
            result = resolve_agents(agents_file, "9.1", "review")
            self.assertEqual(result["model"], "claude-sonnet-4-6")
            result = resolve_agents(agents_file, "9.1", "dev")
            self.assertEqual(result["model"], "")


class OrchestratorEpicAgentsModelTests(unittest.TestCase):
    def test_parse_agent_config_extracts_default_model(self) -> None:
        config = parse_agent_config(
            json.dumps({"defaultPrimary": "claude", "defaultModel": "claude-opus-4-7"})
        )
        self.assertEqual(config["defaultModel"], "claude-opus-4-7")

    def test_resolve_agent_picks_model_per_task(self) -> None:
        config = parse_agent_config(
            json.dumps(
                {
                    "defaultPrimary": "claude",
                    "defaultModel": "claude-opus-4-7",
                    "perTask": {"review": {"primary": "claude", "model": "claude-sonnet-4-6"}},
                }
            )
        )
        primary, _fallback, model = resolve_agent(config, "medium", "review")
        self.assertEqual((primary, model), ("claude", "claude-sonnet-4-6"))
        _primary, _fallback, model = resolve_agent(config, "medium", "dev")
        self.assertEqual(model, "claude-opus-4-7")


class StateDocModelSerializationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project_root = Path(self.tmp.name)
        self._install_bundle()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_state_doc_writes_per_task_and_default_model(self) -> None:
        template = self.project_root / ".claude" / "skills" / "bmad-story-automator" / "templates" / "state-document.md"
        output_dir = self.project_root / "_bmad-output" / "story-automator"
        config = {
            "epic": "9",
            "epicName": "Trust & Safety",
            "storyRange": ["9.1"],
            "status": "READY",
            "aiCommand": "claude --dangerously-skip-permissions",
            "agentConfig": {
                "defaultPrimary": "claude",
                "defaultFallback": False,
                "defaultModel": "claude-opus-4-7[1m]",
                "perTask": {
                    "review": {"primary": "claude", "fallback": False, "model": "claude-sonnet-4-6"},
                },
                "complexityOverrides": {
                    "high": {"dev": {"primary": "claude", "model": "claude-opus-4-7[1m]"}},
                },
            },
        }

        stdout = io.StringIO()
        with patch.dict(os.environ, {"PROJECT_ROOT": str(self.project_root)}, clear=False), redirect_stdout(stdout):
            code = cmd_build_state_doc(
                [
                    "--template",
                    str(template),
                    "--output-folder",
                    str(output_dir),
                    "--config-json",
                    json.dumps(config),
                ]
            )
        self.assertEqual(code, 0)
        state_path = Path(json.loads(stdout.getvalue())["path"])
        text = state_path.read_text(encoding="utf-8")
        self.assertIn('defaultModel: "claude-opus-4-7[1m]"', text)
        self.assertIn('model: "claude-sonnet-4-6"', text)
        self.assertIn('model: "claude-opus-4-7[1m]"', text)

    def _install_bundle(self) -> None:
        source_skill = REPO_ROOT / "skills" / "bmad-story-automator"
        source_review = REPO_ROOT / "skills" / "bmad-story-automator-review"
        target_root = self.project_root / ".claude" / "skills"
        target_root.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_skill, target_root / "bmad-story-automator")
        shutil.copytree(source_review, target_root / "bmad-story-automator-review")
        for name in ("bmad-create-story", "bmad-dev-story", "bmad-retrospective", "bmad-qa-generate-e2e-tests"):
            skill_dir = target_root / name
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")
            (skill_dir / "workflow.md").write_text(f"# {name}\n", encoding="utf-8")
        (target_root / "bmad-create-story" / "discover-inputs.md").write_text("# d\n", encoding="utf-8")
        (target_root / "bmad-create-story" / "checklist.md").write_text("# c\n", encoding="utf-8")
        (target_root / "bmad-create-story" / "template.md").write_text("# t\n", encoding="utf-8")
        (target_root / "bmad-dev-story" / "checklist.md").write_text("# c\n", encoding="utf-8")
        (target_root / "bmad-qa-generate-e2e-tests" / "checklist.md").write_text("# c\n", encoding="utf-8")


class StateDocSentinelOmissionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project_root = Path(self.tmp.name)
        self._install_bundle()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_sentinel_models_are_omitted_from_state(self) -> None:
        template = self.project_root / ".claude" / "skills" / "bmad-story-automator" / "templates" / "state-document.md"
        output_dir = self.project_root / "_bmad-output" / "story-automator"
        config = {
            "epic": "9",
            "epicName": "Trust & Safety",
            "storyRange": ["9.1"],
            "status": "READY",
            "aiCommand": "claude --dangerously-skip-permissions",
            "agentConfig": {
                "defaultPrimary": "claude",
                "defaultFallback": False,
                # sentinel — should NOT appear in serialized YAML
                "defaultModel": "auto",
                "perTask": {
                    "review": {"primary": "claude", "fallback": False, "model": "none"},
                    "dev": {"primary": "claude", "fallback": False, "model": "claude-opus-4-7[1m]"},
                },
                "complexityOverrides": {
                    "high": {"review": {"primary": "claude", "model": "false"}},
                },
            },
        }
        stdout = io.StringIO()
        with patch.dict(os.environ, {"PROJECT_ROOT": str(self.project_root)}, clear=False), redirect_stdout(stdout):
            code = cmd_build_state_doc(
                [
                    "--template",
                    str(template),
                    "--output-folder",
                    str(output_dir),
                    "--config-json",
                    json.dumps(config),
                ]
            )
        self.assertEqual(code, 0)
        state_path = Path(json.loads(stdout.getvalue())["path"])
        text = state_path.read_text(encoding="utf-8")
        # Sentinels never serialized
        self.assertNotIn('defaultModel:', text)
        self.assertNotIn('model: "auto"', text)
        self.assertNotIn('model: "none"', text)
        self.assertNotIn('model: "false"', text)
        # Real value still survives
        self.assertIn('model: "claude-opus-4-7[1m]"', text)

    def _install_bundle(self) -> None:
        source_skill = REPO_ROOT / "skills" / "bmad-story-automator"
        source_review = REPO_ROOT / "skills" / "bmad-story-automator-review"
        target_root = self.project_root / ".claude" / "skills"
        target_root.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_skill, target_root / "bmad-story-automator")
        shutil.copytree(source_review, target_root / "bmad-story-automator-review")
        for name in ("bmad-create-story", "bmad-dev-story", "bmad-retrospective", "bmad-qa-generate-e2e-tests"):
            skill_dir = target_root / name
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")
            (skill_dir / "workflow.md").write_text(f"# {name}\n", encoding="utf-8")
        (target_root / "bmad-create-story" / "discover-inputs.md").write_text("# d\n", encoding="utf-8")
        (target_root / "bmad-create-story" / "checklist.md").write_text("# c\n", encoding="utf-8")
        (target_root / "bmad-create-story" / "template.md").write_text("# t\n", encoding="utf-8")
        (target_root / "bmad-dev-story" / "checklist.md").write_text("# c\n", encoding="utf-8")
        (target_root / "bmad-qa-generate-e2e-tests" / "checklist.md").write_text("# c\n", encoding="utf-8")


class AgentCliMissingModelFailFastTests(unittest.TestCase):
    def test_tmux_wrapper_agent_cli_missing_model_value_fails(self) -> None:
        from story_automator.commands.tmux import cmd_tmux_wrapper
        err = io.StringIO()
        with patch.dict(os.environ, {"AI_AGENT": "claude"}, clear=False), \
             __import__("contextlib").redirect_stderr(err):
            code = cmd_tmux_wrapper(["agent-cli", "--model"])
        self.assertEqual(code, 1)
        self.assertIn("--model requires a value", err.getvalue())

    def test_build_cmd_missing_model_value_fails(self) -> None:
        # _build_cmd uses _flag_value which already raises PolicyError for empty
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            target_root = project_root / ".claude" / "skills"
            target_root.mkdir(parents=True, exist_ok=True)
            shutil.copytree(REPO_ROOT / "skills" / "bmad-story-automator", target_root / "bmad-story-automator")
            shutil.copytree(REPO_ROOT / "skills" / "bmad-story-automator-review", target_root / "bmad-story-automator-review")
            for name in ("bmad-create-story", "bmad-dev-story", "bmad-retrospective", "bmad-qa-generate-e2e-tests"):
                skill_dir = target_root / name
                skill_dir.mkdir(parents=True, exist_ok=True)
                (skill_dir / "SKILL.md").write_text("# x\n", encoding="utf-8")
                (skill_dir / "workflow.md").write_text("# x\n", encoding="utf-8")
            (target_root / "bmad-create-story" / "discover-inputs.md").write_text("# d\n", encoding="utf-8")
            (target_root / "bmad-create-story" / "checklist.md").write_text("# c\n", encoding="utf-8")
            (target_root / "bmad-create-story" / "template.md").write_text("# t\n", encoding="utf-8")
            (target_root / "bmad-dev-story" / "checklist.md").write_text("# c\n", encoding="utf-8")
            (target_root / "bmad-qa-generate-e2e-tests" / "checklist.md").write_text("# c\n", encoding="utf-8")

            err = io.StringIO()
            with patch.dict(os.environ, {"PROJECT_ROOT": str(project_root), "AI_AGENT": "claude"}, clear=False), \
                 __import__("contextlib").redirect_stderr(err):
                code = _build_cmd(["review", "9.1", "--agent", "claude", "--model"])
            self.assertEqual(code, 1)
            self.assertIn("--model requires a value", err.getvalue())


class BuildCmdModelFlagTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project_root = Path(self.tmp.name)
        self._install_bundle()
        self._install_required_skills()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_build_cmd_injects_model_for_claude(self) -> None:
        stdout = io.StringIO()
        with patch.dict(os.environ, {"PROJECT_ROOT": str(self.project_root), "AI_AGENT": "claude"}, clear=False), redirect_stdout(stdout):
            code = _build_cmd(["review", "9.1", "--agent", "claude", "--model", "claude-sonnet-4-6"])
        self.assertEqual(code, 0)
        rendered = stdout.getvalue()
        self.assertIn("claude --dangerously-skip-permissions --model claude-sonnet-4-6", rendered)

    def test_build_cmd_injects_model_for_codex(self) -> None:
        stdout = io.StringIO()
        with patch.dict(os.environ, {"PROJECT_ROOT": str(self.project_root), "AI_AGENT": "codex"}, clear=False), redirect_stdout(stdout):
            code = _build_cmd(["review", "9.1", "--agent", "codex", "--model", "gpt-5.5"])
        self.assertEqual(code, 0)
        rendered = stdout.getvalue()
        self.assertIn("--model gpt-5.5", rendered)
        self.assertIn("codex exec -s workspace-write", rendered)

    def test_build_cmd_without_model_unchanged(self) -> None:
        stdout = io.StringIO()
        with patch.dict(os.environ, {"PROJECT_ROOT": str(self.project_root), "AI_AGENT": "claude"}, clear=False), redirect_stdout(stdout):
            code = _build_cmd(["review", "9.1", "--agent", "claude"])
        self.assertEqual(code, 0)
        rendered = stdout.getvalue()
        self.assertNotIn("--model", rendered)

    def _install_bundle(self) -> None:
        source_skill = REPO_ROOT / "skills" / "bmad-story-automator"
        source_review = REPO_ROOT / "skills" / "bmad-story-automator-review"
        target_root = self.project_root / ".claude" / "skills"
        target_root.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_skill, target_root / "bmad-story-automator")
        shutil.copytree(source_review, target_root / "bmad-story-automator-review")

    def _install_required_skills(self) -> None:
        for name in ("bmad-create-story", "bmad-dev-story", "bmad-retrospective", "bmad-qa-generate-e2e-tests"):
            skill_dir = self.project_root / ".claude" / "skills" / name
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")
            (skill_dir / "workflow.md").write_text(f"# {name}\n", encoding="utf-8")
        (self.project_root / ".claude" / "skills" / "bmad-create-story" / "discover-inputs.md").write_text("# discover\n", encoding="utf-8")
        (self.project_root / ".claude" / "skills" / "bmad-create-story" / "checklist.md").write_text("# checklist\n", encoding="utf-8")
        (self.project_root / ".claude" / "skills" / "bmad-create-story" / "template.md").write_text("# template\n", encoding="utf-8")
        (self.project_root / ".claude" / "skills" / "bmad-dev-story" / "checklist.md").write_text("# checklist\n", encoding="utf-8")
        (self.project_root / ".claude" / "skills" / "bmad-qa-generate-e2e-tests" / "checklist.md").write_text("# checklist\n", encoding="utf-8")


class RetroAgentModelFromStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project_root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_retro_agent_reports_model_from_state(self) -> None:
        state_file = self.project_root / "retro-state.md"
        state_file.write_text(
            '---\nagentConfig:\n'
            '  defaultPrimary: "claude"\n'
            '  defaultFallback: false\n'
            '  defaultModel: "claude-opus-4-7[1m]"\n'
            '  perTask:\n'
            '    retro:\n'
            '      primary: "claude"\n'
            '      fallback: false\n'
            '      model: "claude-sonnet-4-6"\n'
            '---\n',
            encoding="utf-8",
        )
        stdout = io.StringIO()
        with patch.dict(os.environ, {"PROJECT_ROOT": str(self.project_root)}, clear=False), redirect_stdout(stdout):
            code = cmd_orchestrator_helper(["retro-agent", "--state-file", str(state_file)])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["model"], "claude-sonnet-4-6")

    def test_retro_agent_falls_back_to_default_model(self) -> None:
        state_file = self.project_root / "retro-state.md"
        state_file.write_text(
            '---\nagentConfig:\n'
            '  defaultPrimary: "claude"\n'
            '  defaultFallback: false\n'
            '  defaultModel: "claude-opus-4-7[1m]"\n'
            '---\n',
            encoding="utf-8",
        )
        stdout = io.StringIO()
        with patch.dict(os.environ, {"PROJECT_ROOT": str(self.project_root)}, clear=False), redirect_stdout(stdout):
            code = cmd_orchestrator_helper(["retro-agent", "--state-file", str(state_file)])
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["model"], "claude-opus-4-7[1m]")


class MarkdownHandoffShellContractTests(unittest.TestCase):
    """Mirrors the bash pattern used by the workflow markdown snippets.

    Reproduces two regressions that purely-Python argv tests miss:
      1. fallback attempts must NOT inherit the primary agent's model;
      2. bracketed model IDs like `claude-opus-4-7[1m]` must reach Python
         as one literal argv element, even when a matching file exists in cwd.

    The bash snippet exactly mirrors the helper defined in
    `data/retry-fallback-strategy.md` and the call shape used in
    `data/retry-fallback-implementation.md`.
    """

    # Mirrors the helper + call-site pattern used by every workflow snippet.
    # POSIX-compatible (works under bash 3.2 / dash / zsh).
    BASH_SNIPPET = r'''
set -eu

# Mirrors `should_apply_primary_model` in data/retry-fallback-strategy.md.
should_apply_primary_model() {
  [ -n "$primary_model" ] && [ "$1" = "$primary_agent" ]
}

# Stand-in for `tmux-wrapper build-cmd`: a Python child that prints its
# argv one per line so the test can assert exactly what reached argv.
if should_apply_primary_model "$current_agent"; then
  python3 - "$current_agent" --model "$primary_model" <<'PY'
import sys
for arg in sys.argv[1:]:
    print(arg)
PY
else
  python3 - "$current_agent" <<'PY'
import sys
for arg in sys.argv[1:]:
    print(arg)
PY
fi
'''

    def _run(self, *, primary_agent: str, current_agent: str, primary_model: str, cwd) -> list[str]:
        import subprocess
        env = {
            **os.environ,
            "primary_agent": primary_agent,
            "current_agent": current_agent,
            "primary_model": primary_model,
        }
        result = subprocess.run(
            ["bash", "-c", self.BASH_SNIPPET],
            capture_output=True,
            check=True,
            cwd=str(cwd),
            env=env,
            text=True,
        )
        return result.stdout.splitlines()

    def test_primary_attempt_passes_configured_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            argv = self._run(
                primary_agent="claude",
                current_agent="claude",
                primary_model="claude-sonnet-4-6",
                cwd=tmp,
            )
        # argv layout: <current_agent> [--model <id>]
        self.assertEqual(argv, ["claude", "--model", "claude-sonnet-4-6"])

    def test_fallback_attempt_does_not_inherit_primary_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            argv = self._run(
                primary_agent="claude",
                current_agent="codex",
                primary_model="claude-sonnet-4-6",
                cwd=tmp,
            )
        self.assertEqual(argv, ["codex"])
        self.assertNotIn("--model", argv)
        self.assertNotIn("claude-sonnet-4-6", argv)

    def test_bracketed_model_id_survives_shell_expansion(self) -> None:
        """Repro from bma-d's review comment: a `claude-opus-4-71` file in
        cwd must not cause `claude-opus-4-7[1m]` to glob-expand."""
        with tempfile.TemporaryDirectory() as tmp:
            # File whose name matches the bracketed glob pattern
            (Path(tmp) / "claude-opus-4-71").write_text("decoy\n")
            argv = self._run(
                primary_agent="claude",
                current_agent="claude",
                primary_model="claude-opus-4-7[1m]",
                cwd=tmp,
            )
        self.assertEqual(argv, ["claude", "--model", "claude-opus-4-7[1m]"])

    def test_no_model_configured_emits_no_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            argv = self._run(
                primary_agent="claude",
                current_agent="claude",
                primary_model="",
                cwd=tmp,
            )
        self.assertEqual(argv, ["claude"])


if __name__ == "__main__":
    unittest.main()
