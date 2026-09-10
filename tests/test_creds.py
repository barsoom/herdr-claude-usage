import json
import tempfile
import unittest
from pathlib import Path

from claude_usage import creds


class ResolveConfigDir(unittest.TestCase):
    def test_prefers_the_panes_own_claude_config_dir(self):
        got = creds.resolve_config_dir(
            env={"CLAUDE_CONFIG_DIR": "/plugin/scope"},
            proc_env={"CLAUDE_CONFIG_DIR": "/pane/scope"},
            home=Path("/home/x"),
        )
        self.assertEqual(got, Path("/pane/scope"))

    def test_falls_back_to_the_plugin_environment(self):
        got = creds.resolve_config_dir(
            env={"CLAUDE_CONFIG_DIR": "/plugin/scope"}, proc_env={}, home=Path("/home/x")
        )
        self.assertEqual(got, Path("/plugin/scope"))

    def test_falls_back_to_dot_claude_in_home(self):
        got = creds.resolve_config_dir(env={}, proc_env=None, home=Path("/home/x"))
        self.assertEqual(got, Path("/home/x/.claude"))

    def test_expands_a_tilde_in_the_pane_environment(self):
        got = creds.resolve_config_dir(
            env={}, proc_env={"CLAUDE_CONFIG_DIR": "~/alt"}, home=Path("/home/x")
        )
        self.assertEqual(got, Path("/home/x/alt"))

    def test_ignores_a_blank_setting(self):
        got = creds.resolve_config_dir(
            env={"CLAUDE_CONFIG_DIR": "  "}, proc_env={"CLAUDE_CONFIG_DIR": ""}, home=Path("/home/x")
        )
        self.assertEqual(got, Path("/home/x/.claude"))


class ReadAccessToken(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def write(self, payload):
        (self.dir / ".credentials.json").write_text(json.dumps(payload), encoding="utf-8")

    def test_reads_the_oauth_access_token(self):
        self.write({"claudeAiOauth": {"accessToken": "sk-ant-oat01-abc"}})
        self.assertEqual(creds.read_access_token(self.dir), "sk-ant-oat01-abc")

    def test_missing_file_yields_none(self):
        self.assertIsNone(creds.read_access_token(self.dir))

    def test_missing_oauth_block_yields_none(self):
        self.write({"mcpOAuth": {}})
        self.assertIsNone(creds.read_access_token(self.dir))

    def test_blank_token_yields_none(self):
        self.write({"claudeAiOauth": {"accessToken": ""}})
        self.assertIsNone(creds.read_access_token(self.dir))

    def test_unparseable_file_yields_none(self):
        (self.dir / ".credentials.json").write_text("{ nope", encoding="utf-8")
        self.assertIsNone(creds.read_access_token(self.dir))
