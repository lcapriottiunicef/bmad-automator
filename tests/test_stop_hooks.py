from __future__ import annotations

import io
import json
import os
import shlex
import shutil
import tempfile
import tomllib
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from story_automator.commands.basic import cmd_ensure_stop_hook, cmd_stop_hook


REPO_ROOT = Path(__file__).resolve().parents[1]


class StopHookTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project_root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_ensure_stop_hook_installs_codex_hook_and_feature_flag(self) -> None:
        self._install_bundle(".agents")
        stdout = io.StringIO()

        with (
            patch.dict(os.environ, {"PROJECT_ROOT": str(self.project_root), "AI_AGENT": "codex"}, clear=False),
            patch("os.getcwd", return_value=str(self.project_root)),
            redirect_stdout(stdout),
        ):
            code = cmd_ensure_stop_hook(
                [
                    "--settings",
                    str(self.project_root / ".claude" / "settings.json"),
                    "--command",
                    "story-automator stop-hook",
                ]
            )

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["provider"], "codex")
        self.assertEqual(payload["reason"], "codex_hook_configured")
        self.assertEqual(payload["verificationState"], "configured")
        self.assertFalse(payload["trusted"])
        self.assertTrue(payload["changed"])
        self.assertFalse((self.project_root / ".claude" / "settings.json").exists())
        hooks = json.loads((self.project_root / ".codex" / "hooks.json").read_text(encoding="utf-8"))
        hook = hooks["hooks"]["Stop"][0]["hooks"][0]
        self.assertEqual(hook["type"], "command")
        self.assertIn("story-automator stop-hook", hook["command"])
        self.assertEqual(hook["timeout"], 10)
        self.assertEqual(hook["statusMessage"], "Checking story automator state")
        config = tomllib.loads((self.project_root / ".codex" / "config.toml").read_text(encoding="utf-8"))
        self.assertIs(config["features"]["hooks"], True)

    def test_ensure_stop_hook_accepts_unquoted_command_value(self) -> None:
        self._install_bundle(".agents")
        stdout = io.StringIO()

        with (
            patch.dict(os.environ, {"PROJECT_ROOT": str(self.project_root), "AI_AGENT": "codex"}, clear=False),
            patch("os.getcwd", return_value=str(self.project_root)),
            redirect_stdout(stdout),
        ):
            code = cmd_ensure_stop_hook(
                [
                    "--settings",
                    str(self.project_root / ".claude" / "settings.json"),
                    "--command",
                    "story-automator",
                    "stop-hook",
                    "--timeout",
                    "10",
                ]
            )

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["provider"], "codex")
        hooks = json.loads((self.project_root / ".codex" / "hooks.json").read_text(encoding="utf-8"))
        hook = hooks["hooks"]["Stop"][0]["hooks"][0]
        self.assertIn("story-automator stop-hook", hook["command"])
        self.assertEqual(shlex.split(hook["command"])[-1], "stop-hook")
        self.assertEqual(hook["timeout"], 10)
        self.assertEqual(hook["statusMessage"], "Checking story automator state")
        config = tomllib.loads((self.project_root / ".codex" / "config.toml").read_text(encoding="utf-8"))
        self.assertIs(config["features"]["hooks"], True)

    def test_ensure_stop_hook_codex_is_idempotent(self) -> None:
        self._install_bundle(".agents")
        self._write_codex_trust_level("trusted")

        first = self._run_ensure_stop_hook("codex")
        second = self._run_ensure_stop_hook("codex")

        self.assertTrue(first["changed"])
        self.assertFalse(second["changed"])
        self.assertEqual(second["reason"], "already_configured")
        self.assertEqual(second["verificationState"], "verified")
        self.assertTrue(second["trusted"])
        self.assertEqual(second["hooksReason"], "already_configured")
        self.assertEqual(second["configReason"], "already_enabled")

    def test_ensure_stop_hook_codex_uses_global_project_trust(self) -> None:
        self._install_bundle(".agents")
        global_config = self._write_global_codex_config(self._trusted_entry())

        with patch("story_automator.core.stop_hooks._codex_global_config_path", return_value=global_config):
            first = self._run_ensure_stop_hook("codex")
            second = self._run_ensure_stop_hook("codex")

        self.assertTrue(first["changed"])
        self.assertTrue(first["trusted"])
        self.assertEqual(first["verificationState"], "configured")
        self.assertFalse(second["changed"])
        self.assertEqual(second["reason"], "already_configured")
        self.assertTrue(second["trusted"])
        self.assertEqual(second["verificationState"], "verified")

    def test_ensure_stop_hook_codex_ignores_missing_global_config(self) -> None:
        self._install_bundle(".agents")
        global_config = self.project_root / "missing-home" / ".codex" / "config.toml"

        with patch("story_automator.core.stop_hooks._codex_global_config_path", return_value=global_config):
            first = self._run_ensure_stop_hook("codex")
            second = self._run_ensure_stop_hook("codex")

        self.assertTrue(first["changed"])
        self.assertFalse(first["trusted"])
        self.assertEqual(first["verificationState"], "configured")
        self.assertFalse(second["changed"])
        self.assertEqual(second["reason"], "pending_trust")
        self.assertFalse(second["trusted"])
        self.assertEqual(second["verificationState"], "pending_trust")

    def test_ensure_stop_hook_codex_ignores_invalid_global_config(self) -> None:
        self._install_bundle(".agents")
        global_config = self._write_global_codex_config("[projects\n")

        with patch("story_automator.core.stop_hooks._codex_global_config_path", return_value=global_config):
            first = self._run_ensure_stop_hook("codex")
            second = self._run_ensure_stop_hook("codex")

        self.assertTrue(first["changed"])
        self.assertFalse(first["trusted"])
        self.assertEqual(first["verificationState"], "configured")
        self.assertFalse(second["changed"])
        self.assertEqual(second["reason"], "pending_trust")
        self.assertFalse(second["trusted"])
        self.assertEqual(second["verificationState"], "pending_trust")

    def test_ensure_stop_hook_codex_preserves_existing_config(self) -> None:
        self._install_bundle(".agents")
        codex_dir = self.project_root / ".codex"
        codex_dir.mkdir(parents=True, exist_ok=True)
        (codex_dir / "config.toml").write_text(
            'model = "gpt-5.2"\n\n[features]\nexperimental_resume = true\n',
            encoding="utf-8",
        )
        (codex_dir / "hooks.json").write_text(
            json.dumps(
                {
                    "hooks": {
                        "PreToolUse": [
                            {
                                "matcher": "Bash",
                                "hooks": [{"type": "command", "command": "echo check"}],
                            }
                        ]
                    }
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        payload = self._run_ensure_stop_hook("codex")

        self.assertTrue(payload["changed"])
        config = tomllib.loads((codex_dir / "config.toml").read_text(encoding="utf-8"))
        self.assertEqual(config["model"], "gpt-5.2")
        self.assertIs(config["features"]["experimental_resume"], True)
        self.assertIs(config["features"]["hooks"], True)
        hooks = json.loads((codex_dir / "hooks.json").read_text(encoding="utf-8"))
        self.assertIn("PreToolUse", hooks["hooks"])
        self.assertIn("Stop", hooks["hooks"])

    def test_ensure_stop_hook_codex_normalizes_existing_story_hook(self) -> None:
        self._install_bundle(".agents")
        codex_dir = self.project_root / ".codex"
        codex_dir.mkdir(parents=True, exist_ok=True)
        (codex_dir / "config.toml").write_text(
            f'[features]\nhooks = true\n\n[projects.{json.dumps(str(self.project_root.resolve()))}]\ntrust_level = "trusted"\n',
            encoding="utf-8",
        )
        (codex_dir / "hooks.json").write_text(
            json.dumps(
                {
                    "hooks": {
                        "Stop": [
                            {
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": "./story-automator stop-hook",
                                        "timeout": 1,
                                    }
                                ]
                            }
                        ]
                    }
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        payload = self._run_ensure_stop_hook("codex")

        self.assertEqual(payload["reason"], "codex_hook_configured" if payload["changed"] else "hook_normalized")
        self.assertEqual(payload["verificationState"], "configured" if payload["changed"] else "verified")
        self.assertTrue(payload["trusted"])
        hooks = json.loads((codex_dir / "hooks.json").read_text(encoding="utf-8"))
        hook = hooks["hooks"]["Stop"][0]["hooks"][0]
        self.assertIn("story-automator stop-hook", hook["command"])
        self.assertEqual(hook["timeout"], 10)
        self.assertEqual(hook["statusMessage"], "Checking story automator state")

    def test_ensure_stop_hook_codex_preserves_other_story_automator_commands(self) -> None:
        self._install_bundle(".agents")
        codex_dir = self.project_root / ".codex"
        codex_dir.mkdir(parents=True, exist_ok=True)
        existing_command = "story-automator derive-project-slug"
        (codex_dir / "config.toml").write_text("[features]\nhooks = true\n", encoding="utf-8")
        (codex_dir / "hooks.json").write_text(
            json.dumps(
                {
                    "hooks": {
                        "Stop": [
                            {
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": existing_command,
                                        "timeout": 1,
                                    }
                                ]
                            }
                        ]
                    }
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        payload = self._run_ensure_stop_hook("codex")

        self.assertTrue(payload["changed"])
        self.assertEqual(payload["reason"], "codex_hook_configured")
        self.assertEqual(payload["hooksReason"], "added")
        self.assertIn("restart Codex", payload["message"])
        hooks = json.loads((codex_dir / "hooks.json").read_text(encoding="utf-8"))
        stop_hooks = hooks["hooks"]["Stop"]
        self.assertEqual(len(stop_hooks), 2)
        existing_hook = stop_hooks[0]["hooks"][0]
        self.assertEqual(existing_hook["command"], existing_command)
        self.assertEqual(existing_hook["timeout"], 1)
        new_hook = stop_hooks[1]["hooks"][0]
        self.assertIn("story-automator stop-hook", new_hook["command"])
        self.assertEqual(shlex.split(new_hook["command"])[-1], "stop-hook")
        self.assertEqual(new_hook["timeout"], 10)
        self.assertEqual(new_hook["statusMessage"], "Checking story automator state")

    def test_ensure_stop_hook_codex_normalizes_env_wrapped_story_hook(self) -> None:
        self._install_bundle(".agents")
        codex_dir = self.project_root / ".codex"
        codex_dir.mkdir(parents=True, exist_ok=True)
        (codex_dir / "config.toml").write_text("[features]\nhooks = true\n", encoding="utf-8")
        (codex_dir / "hooks.json").write_text(
            json.dumps(
                {
                    "hooks": {
                        "Stop": [
                            {
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": "env PROJECT_ROOT=/old/root /old/install/story-automator stop-hook",
                                        "timeout": 1,
                                    }
                                ]
                            }
                        ]
                    }
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        payload = self._run_ensure_stop_hook("codex")

        self.assertTrue(payload["changed"])
        hooks = json.loads((codex_dir / "hooks.json").read_text(encoding="utf-8"))
        stop_hooks = hooks["hooks"]["Stop"]
        self.assertEqual(len(stop_hooks), 1)
        hook = stop_hooks[0]["hooks"][0]
        self.assertEqual(shlex.split(hook["command"])[-1], "stop-hook")
        self.assertEqual(hook["timeout"], 10)

    def test_ensure_stop_hook_claude_still_uses_settings_json(self) -> None:
        self._install_bundle(".claude")

        payload = self._run_ensure_stop_hook("claude")

        self.assertTrue(payload["changed"])
        self.assertEqual(payload["provider"], "claude")
        self.assertTrue((self.project_root / ".claude" / "settings.json").is_file())
        self.assertFalse((self.project_root / ".codex" / "hooks.json").exists())

    def test_ensure_stop_hook_quotes_paths_with_spaces(self) -> None:
        self._install_bundle(".claude")
        workflow_root = self.project_root / "bmad automator bundle"
        script = workflow_root / "scripts" / "story-automator"
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
        script.chmod(0o755)

        with patch("story_automator.commands.basic._workflow_root", return_value=workflow_root):
            self._run_ensure_stop_hook("claude")

        settings = json.loads((self.project_root / ".claude" / "settings.json").read_text(encoding="utf-8"))
        command = settings["hooks"]["Stop"][0]["hooks"][0]["command"]
        self.assertEqual(
            shlex.split(command),
            ["env", f"PROJECT_ROOT={self.project_root.resolve()}", str(script.resolve()), "stop-hook"],
        )

    def test_ensure_stop_hook_claude_ignores_ai_agent_override(self) -> None:
        self._install_bundle(".claude")
        stdout = io.StringIO()

        with (
            patch.dict(os.environ, {"PROJECT_ROOT": str(self.project_root), "AI_AGENT": "codex"}, clear=False),
            patch("os.getcwd", return_value=str(self.project_root)),
            redirect_stdout(stdout),
        ):
            code = cmd_ensure_stop_hook(
                [
                    "--settings",
                    str(self.project_root / ".claude" / "settings.json"),
                    "--command",
                    "story-automator stop-hook",
                ]
            )

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["provider"], "claude")
        self.assertTrue((self.project_root / ".claude" / "settings.json").is_file())
        self.assertFalse((self.project_root / ".codex" / "hooks.json").exists())

    def test_ensure_stop_hook_codex_reports_pending_trust_until_project_is_trusted(self) -> None:
        self._install_bundle(".agents")

        first = self._run_ensure_stop_hook("codex")
        second = self._run_ensure_stop_hook("codex")

        self.assertTrue(first["changed"])
        self.assertEqual(first["verificationState"], "configured")
        self.assertFalse(first["trusted"])
        self.assertFalse(second["changed"])
        self.assertEqual(second["reason"], "pending_trust")
        self.assertEqual(second["verificationState"], "pending_trust")
        self.assertFalse(second["trusted"])
        self.assertIn("not yet trusted", second["message"])

    def test_init_step_halts_on_codex_pending_trust(self) -> None:
        step_text = (REPO_ROOT / "skills" / "bmad-story-automator" / "steps-c" / "step-01-init.md").read_text(encoding="utf-8")

        self.assertIn("verification_state=", step_text)
        self.assertIn('verification_state == "pending_trust"', step_text)
        self.assertIn("HALT", step_text)

    def test_stop_hook_uses_project_root_env_when_invoked_from_nested_directory(self) -> None:
        self._install_bundle(".agents")
        marker = self.project_root / ".agents" / ".story-automator-active"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps({"storiesRemaining": 2}), encoding="utf-8")
        stdout = io.StringIO()
        nested = self.project_root / "nested" / "deeper"
        nested.mkdir(parents=True, exist_ok=True)

        with (
            patch.dict(os.environ, {"PROJECT_ROOT": str(self.project_root)}, clear=False),
            patch("story_automator.commands.basic.sys.stdin", io.StringIO("{}")),
            patch("os.getcwd", return_value=str(nested)),
            redirect_stdout(stdout),
        ):
            code = cmd_stop_hook([])

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["decision"], "block")

    def test_ensure_stop_hook_codex_updates_dotted_features_toml(self) -> None:
        self._install_bundle(".agents")
        codex_dir = self.project_root / ".codex"
        codex_dir.mkdir(parents=True, exist_ok=True)
        (codex_dir / "config.toml").write_text("features.experimental_resume = true\nfeatures.codex_hooks = false\n", encoding="utf-8")

        payload = self._run_ensure_stop_hook("codex")

        self.assertTrue(payload["changed"])
        text = (codex_dir / "config.toml").read_text(encoding="utf-8")
        self.assertNotIn("[features]", text)
        self.assertNotIn("codex_hooks", text)
        config = tomllib.loads(text)
        self.assertIs(config["features"]["experimental_resume"], True)
        self.assertIs(config["features"]["hooks"], True)
        self.assertNotIn("codex_hooks", config["features"])

    def test_ensure_stop_hook_codex_updates_dotted_features_toml_with_comment(self) -> None:
        self._install_bundle(".agents")
        codex_dir = self.project_root / ".codex"
        codex_dir.mkdir(parents=True, exist_ok=True)
        (codex_dir / "config.toml").write_text(
            "features.experimental_resume = true\nfeatures.codex_hooks = false # disabled until setup\n",
            encoding="utf-8",
        )

        payload = self._run_ensure_stop_hook("codex")

        self.assertTrue(payload["changed"])
        text = (codex_dir / "config.toml").read_text(encoding="utf-8")
        self.assertIn("features.hooks = true", text)
        self.assertNotIn("codex_hooks", text)
        config = tomllib.loads(text)
        self.assertIs(config["features"]["experimental_resume"], True)
        self.assertIs(config["features"]["hooks"], True)
        self.assertNotIn("codex_hooks", config["features"])

    def test_ensure_stop_hook_codex_updates_commented_features_table(self) -> None:
        self._install_bundle(".agents")
        codex_dir = self.project_root / ".codex"
        codex_dir.mkdir(parents=True, exist_ok=True)
        (codex_dir / "config.toml").write_text(
            '[features] # runtime feature flags\nexperimental_resume = true\n\n[projects."/tmp/example"]\ntrust_level = "trusted"\n',
            encoding="utf-8",
        )

        payload = self._run_ensure_stop_hook("codex")

        self.assertTrue(payload["changed"])
        text = (codex_dir / "config.toml").read_text(encoding="utf-8")
        self.assertIn("[features] # runtime feature flags\nhooks = true\nexperimental_resume = true", text)
        config = tomllib.loads(text)
        self.assertIs(config["features"]["experimental_resume"], True)
        self.assertIs(config["features"]["hooks"], True)
        self.assertEqual(config["projects"]["/tmp/example"]["trust_level"], "trusted")

    def test_ensure_stop_hook_codex_updates_inline_features_toml(self) -> None:
        self._install_bundle(".agents")
        codex_dir = self.project_root / ".codex"
        codex_dir.mkdir(parents=True, exist_ok=True)
        (codex_dir / "config.toml").write_text("features = { experimental_resume = true }\n", encoding="utf-8")

        payload = self._run_ensure_stop_hook("codex")

        self.assertTrue(payload["changed"])
        config = tomllib.loads((codex_dir / "config.toml").read_text(encoding="utf-8"))
        self.assertIs(config["features"]["experimental_resume"], True)
        self.assertIs(config["features"]["hooks"], True)

    def test_ensure_stop_hook_codex_updates_inline_features_toml_with_comment(self) -> None:
        self._install_bundle(".agents")
        codex_dir = self.project_root / ".codex"
        codex_dir.mkdir(parents=True, exist_ok=True)
        (codex_dir / "config.toml").write_text(
            "features = { experimental_resume = true, codex_hooks = false } # keep inline\n",
            encoding="utf-8",
        )

        payload = self._run_ensure_stop_hook("codex")

        self.assertTrue(payload["changed"])
        text = (codex_dir / "config.toml").read_text(encoding="utf-8")
        self.assertIn("# keep inline", text)
        self.assertNotIn("codex_hooks", text)
        config = tomllib.loads(text)
        self.assertIs(config["features"]["experimental_resume"], True)
        self.assertIs(config["features"]["hooks"], True)
        self.assertNotIn("codex_hooks", config["features"])

    def test_ensure_stop_hook_codex_migrates_legacy_codex_hooks_table(self) -> None:
        self._install_bundle(".agents")
        codex_dir = self.project_root / ".codex"
        codex_dir.mkdir(parents=True, exist_ok=True)
        (codex_dir / "config.toml").write_text(
            'model = "gpt-5.2"\n\n[features]\ncodex_hooks = true\n',
            encoding="utf-8",
        )

        payload = self._run_ensure_stop_hook("codex")

        self.assertTrue(payload["configChanged"])
        self.assertEqual(payload["configReason"], "hooks_enabled")
        text = (codex_dir / "config.toml").read_text(encoding="utf-8")
        self.assertNotIn("codex_hooks", text)
        config = tomllib.loads(text)
        self.assertEqual(config["model"], "gpt-5.2")
        self.assertIs(config["features"]["hooks"], True)
        self.assertNotIn("codex_hooks", config["features"])

    def test_ensure_stop_hook_codex_leaves_correct_hooks_flag_untouched(self) -> None:
        self._install_bundle(".agents")
        codex_dir = self.project_root / ".codex"
        codex_dir.mkdir(parents=True, exist_ok=True)
        config_path = codex_dir / "config.toml"
        config_path.write_text("[features]\nhooks = true\n", encoding="utf-8")

        payload = self._run_ensure_stop_hook("codex")

        self.assertFalse(payload["configChanged"])
        self.assertEqual(payload["configReason"], "already_enabled")
        self.assertEqual(config_path.read_text(encoding="utf-8"), "[features]\nhooks = true\n")

    def test_ensure_stop_hook_codex_enables_disabled_hooks_flag(self) -> None:
        self._install_bundle(".agents")
        codex_dir = self.project_root / ".codex"
        codex_dir.mkdir(parents=True, exist_ok=True)
        (codex_dir / "config.toml").write_text("[features]\nhooks = false\n", encoding="utf-8")

        payload = self._run_ensure_stop_hook("codex")

        self.assertTrue(payload["configChanged"])
        self.assertEqual(payload["configReason"], "hooks_enabled")
        config = tomllib.loads((codex_dir / "config.toml").read_text(encoding="utf-8"))
        self.assertIs(config["features"]["hooks"], True)

    def test_ensure_stop_hook_codex_drops_legacy_key_when_current_key_present(self) -> None:
        self._install_bundle(".agents")
        codex_dir = self.project_root / ".codex"
        codex_dir.mkdir(parents=True, exist_ok=True)
        (codex_dir / "config.toml").write_text(
            "[features]\ncodex_hooks = true\nhooks = true\n",
            encoding="utf-8",
        )

        payload = self._run_ensure_stop_hook("codex")

        self.assertTrue(payload["configChanged"])
        self.assertEqual(payload["configReason"], "hooks_enabled")
        text = (codex_dir / "config.toml").read_text(encoding="utf-8")
        self.assertNotIn("codex_hooks", text)
        config = tomllib.loads(text)
        self.assertIs(config["features"]["hooks"], True)
        self.assertNotIn("codex_hooks", config["features"])

    def test_ensure_stop_hook_codex_reports_invalid_hooks_json(self) -> None:
        self._install_bundle(".agents")
        codex_dir = self.project_root / ".codex"
        codex_dir.mkdir(parents=True, exist_ok=True)
        (codex_dir / "hooks.json").write_text("{not-json\n", encoding="utf-8")

        payload = self._run_ensure_stop_hook("codex", expected_code=1)

        self.assertEqual(payload["error"], "invalid_json")
        self.assertEqual(payload["provider"], "codex")
        self.assertFalse((codex_dir / "config.toml").exists())

    def test_ensure_stop_hook_codex_reports_invalid_config_toml(self) -> None:
        self._install_bundle(".agents")
        codex_dir = self.project_root / ".codex"
        codex_dir.mkdir(parents=True, exist_ok=True)
        (codex_dir / "config.toml").write_text("[features\n", encoding="utf-8")

        payload = self._run_ensure_stop_hook("codex", expected_code=1)

        self.assertEqual(payload["error"], "invalid_toml")
        self.assertEqual(payload["provider"], "codex")
        self.assertEqual((codex_dir / "config.toml").read_text(encoding="utf-8"), "[features\n")
        self.assertFalse((codex_dir / "hooks.json").exists())

    def _install_bundle(self, runtime_dir: str) -> None:
        source_skill = REPO_ROOT / "skills" / "bmad-story-automator"
        source_review = REPO_ROOT / "skills" / "bmad-story-automator-review"
        if not source_skill.is_dir() or not source_review.is_dir():
            self.fail(f"test fixture skills missing under {REPO_ROOT / 'skills'}")
        target_root = self.project_root / runtime_dir / "skills"
        target_root.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_skill, target_root / "bmad-story-automator")
        shutil.copytree(source_review, target_root / "bmad-story-automator-review")

    def _run_ensure_stop_hook(self, provider: str, *, expected_code: int = 0) -> dict[str, object]:
        stdout = io.StringIO()
        env = {"PROJECT_ROOT": str(self.project_root)}
        if provider:
            env["BMAD_RUNTIME_PROVIDER"] = provider
        with (
            patch.dict(os.environ, env, clear=False),
            patch("os.getcwd", return_value=str(self.project_root)),
            redirect_stdout(stdout),
        ):
            code = cmd_ensure_stop_hook(
                [
                    "--settings",
                    str(self.project_root / ".claude" / "settings.json"),
                    "--command",
                    "story-automator stop-hook",
                ]
            )

        self.assertEqual(code, expected_code)
        return json.loads(stdout.getvalue())

    def _trusted_entry(self) -> str:
        return f'[projects.{json.dumps(str(self.project_root.resolve()))}]\ntrust_level = "trusted"\n'

    def _write_codex_trust_level(self, trust_level: str) -> None:
        codex_dir = self.project_root / ".codex"
        codex_dir.mkdir(parents=True, exist_ok=True)
        config_path = codex_dir / "config.toml"
        prefix = config_path.read_text(encoding="utf-8") if config_path.exists() else "[features]\nhooks = true\n"
        if not prefix.endswith("\n"):
            prefix += "\n"
        config_path.write_text(
            prefix + f'\n[projects.{json.dumps(str(self.project_root.resolve()))}]\ntrust_level = "{trust_level}"\n',
            encoding="utf-8",
        )

    def _write_global_codex_config(self, body: str) -> Path:
        global_config = self.project_root / "global-home" / ".codex" / "config.toml"
        global_config.parent.mkdir(parents=True, exist_ok=True)
        global_config.write_text(body, encoding="utf-8")
        return global_config


if __name__ == "__main__":
    unittest.main()
