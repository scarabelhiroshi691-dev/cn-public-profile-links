"""Configuration isolation, write boundaries and browser reuse guardrails."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))
import runtime_config as config
spec = importlib.util.spec_from_file_location("ppl_setup", PROJECT / "scripts/setup.py")
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class RuntimeConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ppl-config-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write(self, fields):
        path = self.root / "settings.json"
        path.write_text(json.dumps(fields), encoding="utf-8")
        return path

    def test_new_location_resolves_relative_storage_without_old_machine_paths(self):
        path = self.write({"version": 1, "storage": {"root": "portable data"},
                           "browser": {"session": "clean-install"}})
        value = config.load_config(path, project=self.root)
        self.assertEqual(Path(value["root"]), self.root / "portable data")
        self.assertEqual(Path(value["profile"]), self.root / "portable data/browser-profile")
        self.assertEqual(value["session"], "clean-install")
        self.assertTrue(Path(value["cli"]).is_relative_to(self.root))

    def test_frozen_path_is_rejected_before_resolving_or_accessing_it(self):
        with patch.object(config.Path, "resolve", side_effect=AssertionError("must not resolve")):
            with self.assertRaisesRegex(config.ConfigError, "frozen"):
                config.checked_path("E:/never-read")

    def test_unknown_keys_and_missing_explicit_config_fail_closed(self):
        with self.assertRaisesRegex(config.ConfigError, "Unknown"):
            config.load_config(self.write({"broser": {}}), project=self.root)
        with self.assertRaisesRegex(config.ConfigError, "missing"):
            config.load_config(self.root / "absent.json", project=self.root)
        with self.assertRaisesRegex(config.ConfigError, "strings"):
            config.load_config(self.write({"browser": {"session": 0}}), project=self.root)

    def test_output_escaping_configured_roots_is_rejected(self):
        value = config.load_config(self.write({}), project=self.root)
        value["write_roots"] = [str(self.root / "allowed")]
        with patch.object(config, "get_config", return_value=value):
            with self.assertRaisesRegex(config.ConfigError, "outside"):
                config.local_path(self.root / "allowed/../escape", writing=True)
            self.assertEqual(config.local_path(self.root / "allowed/task", writing=True), self.root / "allowed/task")

    def test_profile_outside_allowed_roots_and_option_like_session_are_rejected(self):
        with self.assertRaisesRegex(config.ConfigError, "session"):
            config.load_config(self.write({"browser": {"session": "--other-session"}}), project=self.root)
        with self.assertRaisesRegex(config.ConfigError, "allowed write"):
            config.load_config(self.write({"browser": {"profile": str(Path(sys.executable).parent)}}), project=self.root)

    def test_existing_browser_with_wrong_profile_is_not_accepted(self):
        value = {"profile": str(self.root / "own")}
        for section in ["status: open\nheaded: true\nuser-data-dir: other",
                        "status: open\nheaded: false\nuser-data-dir: " + value["profile"]]:
            with self.assertRaisesRegex(config.ConfigError, "different profile|not visible"):
                setup.validate_session(section, value)
        self.assertIsNone(setup.session_section("- somebody-else:\n  status: open", "own"))

    def test_skill_install_is_repeatable_but_preserves_user_edits(self):
        source = self.root / "skills/cn-public-profile-links"
        source.mkdir(parents=True)
        (source / "SKILL.md").write_text("---\nname: cn-public-profile-links\n---\nTest skill\n", encoding="utf-8")
        with patch.object(setup, "PROJECT", self.root):
            target = Path(setup.install_skill())
            first = (target / "SKILL.md").read_bytes()
            setup.install_skill()
            self.assertEqual((target / "SKILL.md").read_bytes(), first)
            (target / "SKILL.md").write_text("user edit", encoding="utf-8")
            with self.assertRaisesRegex(config.ConfigError, "edited"):
                setup.install_skill()
            self.assertEqual((target / "SKILL.md").read_text(encoding="utf-8"), "user edit")

    def test_node_bridge_uses_same_explicit_config_and_python_environment(self):
        settings = self.write({"browser": {"session": "isolated-cfg"}})
        node = config.executable("node")
        if not node:
            self.skipTest("Node unavailable")
        code = "import {runtimeConfig} from " + json.dumps((PROJECT / "scripts/runtime_config.mjs").as_uri()) + ";console.log(JSON.stringify(await runtimeConfig()));"
        p = subprocess.run([node, "--input-type=module", "-e", code], cwd=self.root,
                           env={**os.environ, "PPL_CONFIG": str(settings), "PPL_PYTHON": sys.executable},
                           text=True, encoding="utf-8", capture_output=True, timeout=15)
        self.assertEqual(p.returncode, 0, p.stderr)
        value = json.loads(p.stdout)
        self.assertEqual(value["session"], "isolated-cfg")
        self.assertEqual(Path(value["config_file"]), settings)
        self.assertEqual(Path(value["python"]), Path(sys.executable))

    def test_browser_child_does_not_inherit_external_playwright_profile_settings(self):
        with patch.dict(os.environ, {"PLAYWRIGHT_MCP_STORAGE_STATE": "unrelated.json", "PLAYWRIGHT_CLI_SESSION": "unrelated"}):
            env = config.child_env()
        self.assertNotIn("PLAYWRIGHT_MCP_STORAGE_STATE", env)
        self.assertNotIn("PLAYWRIGHT_CLI_SESSION", env)
        self.assertEqual(env["PPL_PYTHON"], sys.executable)
