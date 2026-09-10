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


class KeychainNaming(unittest.TestCase):
    """Mirrors Claude Code's own securestorage service name, or macOS finds nothing."""

    def scope(self, env=None, proc_env=None):
        return creds.resolve_scope(env=env or {}, proc_env=proc_env, home=Path("/Users/x"), user="x")

    def test_default_scope_uses_the_bare_service_name(self):
        self.assertEqual(self.scope().keychain_service, "Claude Code-credentials")

    def test_an_explicit_config_dir_appends_a_hash_of_the_raw_setting(self):
        service = self.scope(env={"CLAUDE_CONFIG_DIR": "/Users/x/.claude-work"}).keychain_service
        self.assertEqual(service, "Claude Code-credentials-" + creds.scope_digest("/Users/x/.claude-work"))

    def test_the_hash_covers_the_raw_setting_not_the_expanded_path(self):
        """Claude Code hashes what is in the environment; node never expands `~`."""
        service = self.scope(env={"CLAUDE_CONFIG_DIR": "~/alt"}).keychain_service
        self.assertEqual(service, "Claude Code-credentials-" + creds.scope_digest("~/alt"))

    def test_an_explicit_config_dir_equal_to_the_default_still_hashes(self):
        """Presence of the variable decides, not its value."""
        self.assertNotEqual(
            self.scope(env={"CLAUDE_CONFIG_DIR": "/Users/x/.claude"}).keychain_service,
            "Claude Code-credentials",
        )

    def test_securestorage_override_wins_over_the_config_dir(self):
        service = self.scope(
            env={"CLAUDE_CONFIG_DIR": "/a", "CLAUDE_SECURESTORAGE_CONFIG_DIR": "/b"}
        ).keychain_service
        self.assertEqual(service, "Claude Code-credentials-" + creds.scope_digest("/b"))

    def test_a_blank_securestorage_override_means_the_default_scope(self):
        service = self.scope(
            env={"CLAUDE_CONFIG_DIR": "/a", "CLAUDE_SECURESTORAGE_CONFIG_DIR": ""}
        ).keychain_service
        self.assertEqual(service, "Claude Code-credentials")

    def test_the_panes_own_setting_wins(self):
        scope = self.scope(
            env={"CLAUDE_CONFIG_DIR": "/plugin"}, proc_env={"CLAUDE_CONFIG_DIR": "/pane"}
        )
        self.assertEqual(scope.config_dir, Path("/pane"))
        self.assertEqual(scope.keychain_service, "Claude Code-credentials-" + creds.scope_digest("/pane"))

    def test_account_comes_from_user(self):
        self.assertEqual(self.scope(env={"USER": "ada"}).keychain_account, "ada")

    def test_an_unusable_username_falls_back_the_way_claude_code_does(self):
        scope = creds.resolve_scope(env={"USER": "ada lovelace"}, home=Path("/Users/x"), user="x")
        self.assertEqual(scope.keychain_account, creds.FALLBACK_ACCOUNT)


class ReadKeychainToken(unittest.TestCase):
    def runner(self, response):
        self.calls = []

        def run(argv):
            self.calls.append(argv)
            return response

        return run

    def test_parses_the_credentials_blob_security_prints(self):
        blob = json.dumps({"claudeAiOauth": {"accessToken": "sk-ant-oat01-kc"}})
        got = creds.read_keychain_token("Claude Code-credentials", "ada", runner=self.runner((0, blob, "")))
        self.assertEqual(got, "sk-ant-oat01-kc")
        self.assertEqual(
            self.calls[0],
            ["security", "find-generic-password", "-a", "ada", "-w", "-s", "Claude Code-credentials"],
        )

    def test_a_missing_item_yields_none(self):
        self.assertIsNone(creds.read_keychain_token("svc", "ada", runner=self.runner((44, "", "not found"))))

    def test_unparseable_output_yields_none(self):
        self.assertIsNone(creds.read_keychain_token("svc", "ada", runner=self.runner((0, "nope", ""))))

    def test_a_missing_security_binary_yields_none(self):
        def run(argv):
            raise FileNotFoundError("security")

        self.assertIsNone(creds.read_keychain_token("svc", "ada", runner=run))


class LoadToken(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.scope = creds.Scope(
            config_dir=self.dir, keychain_service="Claude Code-credentials", keychain_account="ada"
        )

    def write_file_token(self, token):
        (self.dir / ".credentials.json").write_text(
            json.dumps({"claudeAiOauth": {"accessToken": token}}), encoding="utf-8"
        )

    def test_the_credentials_file_wins_when_it_exists(self):
        self.write_file_token("from-file")
        got = creds.load_token(self.scope, platform="darwin", keychain_reader=lambda s, a: "from-keychain")
        self.assertEqual(got, "from-file")

    def test_macos_falls_back_to_the_keychain(self):
        asked = []
        got = creds.load_token(
            self.scope,
            platform="darwin",
            keychain_reader=lambda s, a: asked.append((s, a)) or "from-keychain",
        )
        self.assertEqual(got, "from-keychain")
        self.assertEqual(asked, [("Claude Code-credentials", "ada")])

    def test_linux_does_not_consult_a_keychain(self):
        got = creds.load_token(self.scope, platform="linux", keychain_reader=lambda s, a: "from-keychain")
        self.assertIsNone(got)

    def test_nothing_anywhere_yields_none(self):
        self.assertIsNone(creds.load_token(self.scope, platform="darwin", keychain_reader=lambda s, a: None))


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
