"""Portable installation/launcher tests. Temporary homes and fixture keys only."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.env = {**os.environ, "HOME": str(self.home), "ANTHROPIC_AUTH_TOKEN": "conflicting-fixture", "CLAUDE_CODE_USE_BEDROCK": "1"}
        self.cli = self.home / "fake claude"
        self.cli.write_text('#!' + sys.executable + '\nimport os,json,sys\nprint(json.dumps({"args":sys.argv[1:],"profile":os.environ.get("CLAUDE_CONFIG_DIR"),"api_key":os.environ.get("ANTHROPIC_API_KEY"),"auth":os.environ.get("ANTHROPIC_AUTH_TOKEN"),"base":os.environ.get("ANTHROPIC_BASE_URL"),"bedrock":os.environ.get("CLAUDE_CODE_USE_BEDROCK")}))\n')
        self.cli.chmod(0o700)
        self.key = self.home / "fixture-token"
        self.key.write_text("disposable-modelscope-fixture\n")

    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(ROOT / "qwen.py"), *args], env=self.env, capture_output=True, text=True, timeout=10)

    def setup(self, *extra):
        result = self.run_cli("setup", "--model", "Qwen/fixture", "--claude", str(self.cli), "--key-file", str(self.key), *extra)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("disposable-modelscope-fixture", result.stdout + result.stderr)

    def test_new_profiles_are_isolated_and_key_file_is_private(self):
        self.setup("--context", "1000000")
        for name, thinking in [(".claude-qwen", False), (".claude-qwen-thinking", True)]:
            data = json.loads((self.home / name / "settings.json").read_text())
            self.assertEqual(data["model"], "Qwen/fixture")
            self.assertEqual(data["alwaysThinkingEnabled"], thinking)
            self.assertEqual(data["env"]["CLAUDE_CODE_MAX_CONTEXT_TOKENS"], "1000000")
            self.assertNotIn("ANTHROPIC_API_KEY", data["env"])
            self.assertFalse((self.home / name / ".claude.json").exists())
        self.assertEqual((self.home / ".config/claude-qwen/modelscope-api-key").stat().st_mode & 0o777, 0o600)
        self.assertTrue((self.home / ".local/bin/claude-qwen").is_symlink())

    def test_direct_routing_clears_conflicting_credentials_and_preserves_arguments(self):
        self.setup()
        r = self.run_cli("-p", "a prompt with spaces")
        self.assertEqual(r.returncode, 0, r.stderr)
        d = json.loads(r.stdout)
        self.assertEqual(d["args"], ["-p", "a prompt with spaces"])
        self.assertEqual(d["api_key"], "disposable-modelscope-fixture")
        self.assertIsNone(d["auth"])
        self.assertIsNone(d["bedrock"])
        self.assertEqual(d["base"], "https://api-inference.modelscope.ai")

    def test_thinking_uses_discovered_executable_and_ephemeral_local_auth(self):
        self.setup()
        r = self.run_cli("--thinking", "-p", "fixture")
        self.assertEqual(r.returncode, 0, r.stderr)
        d = json.loads(r.stdout)
        self.assertTrue(d["profile"].endswith(".claude-qwen-thinking"))
        self.assertTrue(d["base"].startswith("http://127.0.0.1:"))
        self.assertIsNone(d["api_key"])
        self.assertNotEqual(d["auth"], "disposable-modelscope-fixture")
        self.assertTrue(d["auth"])

    def test_reconfiguration_preserves_unrelated_preferences_and_mcp(self):
        self.setup()
        p = self.home / ".claude-qwen/settings.json"
        d = json.loads(p.read_text()); d["theme"] = "dark"; p.write_text(json.dumps(d))
        mcp = p.parent / ".claude.json"; mcp.write_text('{"mcpServers":{"fixture":{"type":"http","url":"https://example.com/mcp"}}}')
        self.setup()
        self.assertEqual(json.loads(p.read_text())["theme"], "dark")
        self.assertIn("fixture", json.loads(mcp.read_text())["mcpServers"])

    def test_existing_other_launcher_requires_explicit_replace(self):
        p = self.home / ".local/bin/claude-qwen"; p.parent.mkdir(parents=True); p.write_text("keep me")
        r = self.run_cli("setup", "--model", "Qwen/fixture", "--claude", str(self.cli), "--key-file", str(self.key))
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(p.read_text(), "keep me")
        self.assertFalse((self.home / ".config/claude-qwen/config.json").exists())

    def test_bad_context_and_key_fail_before_mutation(self):
        r = self.run_cli("setup", "--model", "fixture", "--context", "1")
        self.assertNotEqual(r.returncode, 0)
        self.assertLess(len(r.stderr), 500)
        self.assertFalse((self.home / ".config/claude-qwen").exists())


if __name__ == "__main__":
    unittest.main()
