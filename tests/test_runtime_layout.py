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

from story_automator import __version__ as runtime_version
from story_automator.commands.orchestrator import cmd_orchestrator_helper
from story_automator.core import runtime_layout
from story_automator.core.agent_config import parse_agent_config_json, resolve_agent_for_task
from story_automator.core.runtime_layout import (
    active_marker_path,
    active_marker_project_entry,
    resolve_portable_path,
    resolve_skill_dir,
    runtime_provider,
)
from story_automator.core.runtime_policy import load_effective_policy
from story_automator.core.tmux_runtime import agent_type


REPO_ROOT = Path(__file__).resolve().parents[1]


class RuntimeLayoutTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project_root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_codex_project_skill_root_uses_agents_marker(self) -> None:
        self._install_bundle(".agents")

        self.assertEqual(runtime_provider(str(self.project_root)), "codex")
        self.assertEqual(active_marker_path(self.project_root), (self.project_root / ".agents" / ".story-automator-active").resolve())
        self.assertEqual(active_marker_project_entry(self.project_root), ".agents/.story-automator-active")

    def test_codex_project_skill_root_uses_codex_marker(self) -> None:
        self._install_bundle(".codex")

        self.assertEqual(runtime_provider(str(self.project_root)), "codex")
        self.assertEqual(active_marker_path(self.project_root), (self.project_root / ".codex" / ".story-automator-active").resolve())
        self.assertEqual(active_marker_project_entry(self.project_root), ".codex/.story-automator-active")

    def test_claude_project_skill_root_uses_claude_marker(self) -> None:
        self._install_bundle(".claude")

        self.assertEqual(runtime_provider(str(self.project_root)), "claude")
        self.assertEqual(active_marker_path(self.project_root), (self.project_root / ".claude" / ".story-automator-active").resolve())
        self.assertEqual(active_marker_project_entry(self.project_root), ".claude/.story-automator-active")

    def test_codex_provider_without_installed_skill_uses_agents_marker(self) -> None:
        with patch.dict(os.environ, {"BMAD_RUNTIME_PROVIDER": "codex"}, clear=False):
            self.assertEqual(active_marker_path(self.project_root), (self.project_root / ".agents" / ".story-automator-active").resolve())

    def test_ai_agent_does_not_override_runtime_provider(self) -> None:
        self._install_bundle(".claude")

        with patch.dict(os.environ, {"AI_AGENT": "codex"}, clear=False):
            self.assertEqual(runtime_provider(str(self.project_root)), "claude")
            self.assertEqual(active_marker_path(self.project_root), (self.project_root / ".claude" / ".story-automator-active").resolve())

    def test_current_skill_root_wins_when_multiple_runtime_roots_exist(self) -> None:
        self._install_bundle(".agents")
        self._install_bundle(".claude")
        fake_file = self.project_root / ".claude" / "skills" / "bmad-story-automator" / "src" / "story_automator" / "core" / "runtime_layout.py"
        fake_file.parent.mkdir(parents=True, exist_ok=True)
        fake_file.write_text("# simulated installed runtime\n", encoding="utf-8")

        with patch.object(runtime_layout, "__file__", str(fake_file)):
            self.assertEqual(runtime_layout.runtime_provider(str(self.project_root)), "claude")
            self.assertEqual(runtime_layout.active_marker_path(self.project_root), (self.project_root / ".claude" / ".story-automator-active").resolve())

    def test_mixed_project_source_execution_uses_preferred_skill_root(self) -> None:
        self._install_bundle(".agents")
        self._install_bundle(".codex")
        stdout = io.StringIO()

        resolved = resolve_skill_dir(self.project_root, "bmad-story-automator")
        with patch.dict(os.environ, {"PROJECT_ROOT": str(self.project_root)}, clear=False), redirect_stdout(stdout):
            code = cmd_orchestrator_helper(["marker", "path"])

        self.assertEqual(resolved, (self.project_root / ".agents" / "skills" / "bmad-story-automator").resolve())
        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["file"], str((self.project_root / ".agents" / ".story-automator-active").resolve()))

    def test_explicit_skill_root_can_point_at_skill_directory(self) -> None:
        self._install_bundle(".agents")
        explicit_skill = self.project_root / ".agents" / "skills" / "bmad-story-automator"

        with patch.dict(os.environ, {"BMAD_SKILLS_ROOT": str(explicit_skill)}, clear=False):
            resolved = resolve_skill_dir(self.project_root, "bmad-story-automator")

        self.assertEqual(resolved, explicit_skill.resolve())

    def test_neutral_portable_path_resolves_to_active_agents_skill_root(self) -> None:
        self._install_bundle(".agents")
        target = self.project_root / ".agents" / "skills" / "bmad-story-automator-review" / "contract.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{}\n", encoding="utf-8")

        resolved = resolve_portable_path("<skills-root>/bmad-story-automator-review/contract.json", self.project_root)

        self.assertEqual(resolved, target.resolve())

    def test_legacy_portable_claude_path_still_resolves_to_active_agents_skill_root(self) -> None:
        self._install_bundle(".agents")
        target = self.project_root / ".agents" / "skills" / "bmad-story-automator-review" / "contract.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{}\n", encoding="utf-8")

        resolved = resolve_portable_path(".claude/skills/bmad-story-automator-review/contract.json", self.project_root)

        self.assertEqual(resolved, target.resolve())

    def test_malformed_portable_path_returns_none(self) -> None:
        self._install_bundle(".agents")

        resolved = resolve_portable_path(".claude/skills/../escape.txt", self.project_root)

        self.assertIsNone(resolved)

    def test_effective_policy_loads_from_agents_skill_tree(self) -> None:
        self._install_bundle(".agents")
        self._install_required_skills(".agents")

        policy = load_effective_policy(str(self.project_root))

        self.assertEqual(policy["steps"]["review"]["success"]["contractPath"], str((self.project_root / ".agents" / "skills" / "bmad-story-automator-review" / "contract.json").resolve()))
        self.assertEqual(policy["steps"]["create"]["assets"]["files"]["skill"], ".agents/skills/bmad-create-story/SKILL.md")

    def test_auto_agent_defaults_follow_active_runtime_provider(self) -> None:
        self._install_bundle(".agents")

        with patch.dict(os.environ, {"PROJECT_ROOT": str(self.project_root), "AI_AGENT": ""}, clear=False):
            config = parse_agent_config_json("{}")
            primary, fallback = resolve_agent_for_task(config, "medium", "dev")

            self.assertEqual(agent_type(), "codex")
            self.assertEqual((primary, fallback), ("codex", "false"))

    def test_runtime_version_tracks_python_preview_version(self) -> None:
        self.assertEqual(runtime_version, "1.15.0.dev0")

    def test_explicit_agent_values_are_normalized(self) -> None:
        config = parse_agent_config_json('{"defaultPrimary":" Codex ","defaultFallback":" Claude "}')

        self.assertEqual(resolve_agent_for_task(config, "medium", "dev"), ("codex", "claude"))

    def test_marker_path_command_uses_runtime_layout(self) -> None:
        self._install_bundle(".agents")
        stdout = io.StringIO()

        with patch.dict(os.environ, {"PROJECT_ROOT": str(self.project_root)}, clear=False), redirect_stdout(stdout):
            code = cmd_orchestrator_helper(["marker", "path"])

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["file"], str((self.project_root / ".agents" / ".story-automator-active").resolve()))
        self.assertEqual(payload["entry"], ".agents/.story-automator-active")

    def test_marker_create_and_remove_use_active_runtime_layout(self) -> None:
        self._install_bundle(".agents")
        stdout = io.StringIO()

        with patch.dict(os.environ, {"PROJECT_ROOT": str(self.project_root)}, clear=False), redirect_stdout(stdout):
            code = cmd_orchestrator_helper(
                [
                    "marker",
                    "create",
                    "--epic",
                    "1",
                    "--story",
                    "1.1",
                    "--remaining",
                    "2",
                    "--state-file",
                    "_bmad-output/story-automator/orchestration.md",
                    "--project-slug",
                    "project",
                    "--pid",
                    "123",
                    "--heartbeat",
                    "2026-05-01T00:00:00Z",
                ]
            )

        marker = self.project_root / ".agents" / ".story-automator-active"
        self.assertEqual(code, 0)
        self.assertTrue(marker.is_file())
        self.assertFalse((self.project_root / ".claude" / ".story-automator-active").exists())

        stdout = io.StringIO()
        with patch.dict(os.environ, {"PROJECT_ROOT": str(self.project_root)}, clear=False), redirect_stdout(stdout):
            code = cmd_orchestrator_helper(["marker", "remove"])

        self.assertEqual(code, 0)
        self.assertFalse(marker.exists())

    def _install_bundle(self, runtime_dir: str) -> None:
        source_skill = REPO_ROOT / "skills" / "bmad-story-automator"
        source_review = REPO_ROOT / "skills" / "bmad-story-automator-review"
        if not source_skill.is_dir() or not source_review.is_dir():
            self.fail(f"test fixture skills missing under {REPO_ROOT / 'skills'}")
        target_root = self.project_root / runtime_dir / "skills"
        target_root.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_skill, target_root / "bmad-story-automator")
        shutil.copytree(source_review, target_root / "bmad-story-automator-review")

    def _install_required_skills(self, runtime_dir: str) -> None:
        self._make_skill(runtime_dir, "bmad-create-story", extras={"discover-inputs.md": "# discover\n", "checklist.md": "# checklist\n", "template.md": "# template\n"})
        self._make_skill(runtime_dir, "bmad-dev-story", extras={"checklist.md": "# checklist\n"})
        self._make_skill(runtime_dir, "bmad-retrospective")
        self._make_skill(runtime_dir, "bmad-qa-generate-e2e-tests", extras={"checklist.md": "# checklist\n"})

    def _make_skill(self, runtime_dir: str, name: str, *, extras: dict[str, str] | None = None) -> None:
        skill_dir = self.project_root / runtime_dir / "skills" / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(f"# {name}\n", encoding="utf-8")
        for rel, content in (extras or {}).items():
            (skill_dir / rel).write_text(content, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
