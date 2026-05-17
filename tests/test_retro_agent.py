from __future__ import annotations

import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from story_automator.commands.orchestrator import cmd_orchestrator_helper
from story_automator.commands.orchestrator_epic_agents import parse_agent_config
from story_automator.commands.state import cmd_build_state_doc
from story_automator.commands.tmux import _build_cmd


REPO_ROOT = Path(__file__).resolve().parents[1]


class RetroAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project_root = Path(self.tmp.name)
        self.output_dir = self.project_root / "_bmad-output" / "story-automator"
        self._install_bundle()
        self._install_required_skills()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_build_cmd_supports_codex_retro_prompt(self) -> None:
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = _build_cmd(["retro", "2", "--agent", "codex"])
        self.assertEqual(code, 0)
        rendered = stdout.getvalue()
        self.assertIn('CODEX_HOME="/tmp/sa-codex-home-', rendered)
        self.assertIn("codex exec -s workspace-write", rendered)
        self.assertIn("Execute the BMAD retrospective workflow for epic 2.", rendered)

    def test_retro_agent_uses_per_task_override_from_state(self) -> None:
        state_file = self.project_root / "retro-state.md"
        state_file.write_text(
            "---\nagentConfig:\n  defaultPrimary: \"claude\"\n  defaultFallback: \"codex\"\n  perTask:\n    retro:\n      primary: \"codex\"\n      fallback: false\n---\n",
            encoding="utf-8",
        )

        payload = self._run_retro_agent(state_file)

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["primary"], "codex")
        self.assertEqual(payload["fallback"], "false")

    def test_retro_agent_normalizes_explicit_agent_values(self) -> None:
        state_file = self.project_root / "retro-normalized-state.md"
        state_file.write_text(
            "---\nagentConfig:\n  defaultPrimary: \" Codex \"\n  defaultFallback: \" Claude \"\n---\n",
            encoding="utf-8",
        )

        payload = self._run_retro_agent(state_file)

        self.assertEqual((payload["primary"], payload["fallback"]), ("codex", "claude"))

    def test_parse_agent_config_ignores_null_per_task(self) -> None:
        config = parse_agent_config(
            json.dumps(
                {
                    "defaultPrimary": "codex",
                    "defaultFallback": "claude",
                    "perTask": None,
                    "retro": {"primary": "claude", "fallback": False},
                }
            )
        )

        self.assertEqual(config["perTask"]["retro"]["primary"], "claude")
        self.assertEqual(config["perTask"]["retro"]["fallback"], False)

    def test_retro_agent_inherits_default_primary_when_unset(self) -> None:
        state_file = self.project_root / "retro-default-state.md"
        state_file.write_text(
            "---\nagentConfig:\n  defaultPrimary: \"codex\"\n  defaultFallback: \"claude\"\n---\n",
            encoding="utf-8",
        )

        payload = self._run_retro_agent(state_file)

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["primary"], "codex")
        self.assertEqual(payload["fallback"], "claude")

    def test_retro_agent_accepts_legacy_top_level_retro_override(self) -> None:
        state_file = self.project_root / "retro-legacy-state.md"
        state_file.write_text(
            "---\nagentConfig:\n  defaultPrimary: \"claude\"\n  retro:\n    primary: \"codex\"\n    fallback: false\n---\n",
            encoding="utf-8",
        )

        payload = self._run_retro_agent(state_file)

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["primary"], "codex")
        self.assertEqual(payload["fallback"], "false")

    def test_build_state_doc_preserves_legacy_top_level_retro_override(self) -> None:
        stdout = io.StringIO()
        template = self.project_root / ".claude" / "skills" / "bmad-story-automator" / "templates" / "state-document.md"
        config = self._config()
        config["agentConfig"] = {
            "defaultPrimary": "claude",
            "defaultFallback": "codex",
            "retro": {"primary": "codex", "fallback": False},
        }
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_build_state_doc(
                [
                    "--template",
                    str(template),
                    "--output-folder",
                    str(self.output_dir),
                    "--config-json",
                    json.dumps(config),
                ]
            )

        self.assertEqual(code, 0)
        state_file = Path(json.loads(stdout.getvalue())["path"])
        text = state_file.read_text(encoding="utf-8")
        self.assertIn("perTask:\n    retro:\n      primary: \"codex\"\n      fallback: false\n", text)

    def test_retro_agent_uses_complexity_override_from_state(self) -> None:
        state_file = self.project_root / "retro-complexity-state.md"
        state_file.write_text(
            "---\nagentConfig:\n  defaultPrimary: \"claude\"\n  defaultFallback: \"codex\"\n  complexityOverrides:\n    medium:\n      retro:\n        primary: \"codex\"\n        fallback: false\n---\n",
            encoding="utf-8",
        )

        payload = self._run_retro_agent(state_file)

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["primary"], "codex")
        self.assertEqual(payload["fallback"], "false")

    def test_retro_agent_ignores_inline_yaml_comments(self) -> None:
        state_file = self.project_root / "retro-comment-state.md"
        state_file.write_text(
            "---\nagentConfig:\n  defaultPrimary: \"codex\"    # Default agent\n  defaultFallback: \"claude\"    # Default fallback\n---\n",
            encoding="utf-8",
        )

        payload = self._run_retro_agent(state_file)

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["primary"], "codex")
        self.assertEqual(payload["fallback"], "claude")

    def _run_retro_agent(self, state_file: Path) -> dict[str, object]:
        stdout = io.StringIO()
        with patch_env(self.project_root), redirect_stdout(stdout):
            code = cmd_orchestrator_helper(["retro-agent", "--state-file", str(state_file)])
        self.assertEqual(code, 0)
        return json.loads(stdout.getvalue())

    def _config(self) -> dict[str, object]:
        return {
            "epic": "1",
            "epicName": "Epic 1",
            "storyRange": ["1.1"],
            "status": "READY",
            "aiCommand": "claude --dangerously-skip-permissions",
        }

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


class patch_env:
    def __init__(self, project_root: Path) -> None:
        self.project_root = str(project_root)
        self.previous = None

    def __enter__(self) -> None:
        import os

        self.previous = os.environ.get("PROJECT_ROOT")
        os.environ["PROJECT_ROOT"] = self.project_root

    def __exit__(self, exc_type, exc, tb) -> None:
        import os

        if self.previous is None:
            os.environ.pop("PROJECT_ROOT", None)
        else:
            os.environ["PROJECT_ROOT"] = self.previous


if __name__ == "__main__":
    unittest.main()
