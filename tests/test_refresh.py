import unittest
from pathlib import Path

from claude_usage import api, config, creds, refresh
from claude_usage.herdr import Herdr, HerdrError
from tests.support import FakeRunner, agent, envelope, process

SOURCE = refresh.SOURCE_ID


def usage(session=14, weekly=37, fable=36):
    rows = [
        {"kind": "session", "percent": session},
        {"kind": "weekly_all", "percent": weekly},
        {"kind": "weekly_scoped", "percent": fable, "scope": {"model": {"display_name": "Fable"}}},
    ]
    return {"limits": rows}


class Pass(unittest.TestCase):
    def setUp(self):
        self.cfg = config.load(None)
        self.fetched = []
        self.logged = []

    def run_refresh(self, runner, *, env=None, tokens=None, usages=None, **kw):
        tokens = {"/home/x/.claude": "tok"} if tokens is None else tokens
        usages = {"tok": usage()} if usages is None else usages

        def fetch(token, **_):
            self.fetched.append(token)
            got = usages.get(token)
            if isinstance(got, Exception):
                raise got
            return got

        return refresh.refresh(
            Herdr(runner=runner),
            config=self.cfg,
            env=env if env is not None else {},
            fetch=fetch,
            read_environ=kw.pop("read_environ", lambda pid, **_: None),
            read_token=kw.pop("read_token", lambda scope: tokens.get(str(scope.config_dir))),
            home=Path("/home/x"),
            now_ms=lambda: 1234,
            log=self.logged.append,
            **kw,
        )

    def runner_with(self, agents, processes=None):
        processes = processes or {}
        responses = {("herdr", "agent", "list"): (0, envelope({"agents": agents}), "")}

        def runner(argv):
            if argv[:3] == ["herdr", "pane", "process-info"]:
                pane = argv[argv.index("--pane") + 1]
                result = {"process_info": {"foreground_processes": processes.get(pane, [])}}
                return (0, envelope(result), "")
            for prefix, response in responses.items():
                if argv[: len(prefix)] == list(prefix):
                    return response
            return (0, envelope({"type": "ok"}), "")

        fake = FakeRunner()
        fake.responses = responses

        def recording(argv):
            fake.calls.append(list(argv))
            return runner(list(argv))

        recording.calls = fake.calls
        recording.calls_matching = fake.calls_matching
        return recording

    def reports(self, runner):
        return runner.calls_matching("herdr", "pane", "report-metadata")

    def test_reports_the_rendered_token_on_every_claude_pane(self):
        runner = self.runner_with([agent("w1:p1"), agent("w1:p2")])
        self.assertEqual(self.run_refresh(runner), 2)
        reports = self.reports(runner)
        self.assertEqual(len(reports), 2)
        self.assertIn("--token", reports[0])
        self.assertEqual(
            reports[0][reports[0].index("--token") + 1],
            "claude_usage=5h 14% · 1w 37% · Fable 36%",
        )
        self.assertEqual(reports[0][reports[0].index("--source") + 1], SOURCE)
        self.assertEqual(reports[0][reports[0].index("--ttl-ms") + 1], str(self.cfg.ttl_ms))
        self.assertEqual(reports[0][reports[0].index("--seq") + 1], "1234")

    def test_panes_sharing_a_config_dir_cost_one_fetch(self):
        runner = self.runner_with([agent("w1:p1"), agent("w1:p2"), agent("w2:p1")])
        self.run_refresh(runner)
        self.assertEqual(self.fetched, ["tok"])

    def test_skips_panes_running_another_agent(self):
        runner = self.runner_with([agent("w1:p1", kind="codex"), agent("w1:p2")])
        self.assertEqual(self.run_refresh(runner), 1)
        self.assertEqual(self.reports(runner)[0][3], "w1:p2")

    def test_no_claude_panes_makes_no_request_at_all(self):
        runner = self.runner_with([])
        self.assertEqual(self.run_refresh(runner), 0)
        self.assertEqual(self.fetched, [])
        self.assertEqual(self.reports(runner), [])

    def test_a_pane_with_its_own_config_dir_reports_that_account(self):
        runner = self.runner_with(
            [agent("w1:p1"), agent("w1:p2")],
            processes={"w1:p1": [process(11)], "w1:p2": [process(12)]},
        )
        environs = {
            11: {"CLAUDE_CONFIG_DIR": "/home/x/.claude-work"},
            12: {},
        }
        count = self.run_refresh(
            runner,
            read_environ=lambda pid, **_: environs.get(pid),
            tokens={"/home/x/.claude-work": "work-tok", "/home/x/.claude": "tok"},
            usages={"work-tok": usage(90, 91, 92), "tok": usage()},
        )
        self.assertEqual(count, 2)
        self.assertEqual(sorted(self.fetched), ["tok", "work-tok"])
        by_pane = {r[3]: r[r.index("--token") + 1] for r in self.reports(runner)}
        self.assertEqual(by_pane["w1:p1"], "claude_usage=5h 90% · 1w 91% · Fable 92%")
        self.assertEqual(by_pane["w1:p2"], "claude_usage=5h 14% · 1w 37% · Fable 36%")

    def test_hands_the_loader_the_panes_own_keychain_identity(self):
        """macOS reads the token by service name, so the scope must travel with the pane."""
        runner = self.runner_with([agent("w1:p1")], processes={"w1:p1": [process(11)]})
        seen = []
        self.run_refresh(
            runner,
            read_environ=lambda pid, **_: {"CLAUDE_CONFIG_DIR": "/home/x/.claude-work", "USER": "ada"},
            read_token=lambda scope: seen.append(scope) or None,
        )
        self.assertEqual(seen[0].config_dir, Path("/home/x/.claude-work"))
        self.assertEqual(seen[0].keychain_account, "ada")
        self.assertEqual(
            seen[0].keychain_service,
            "Claude Code-credentials-" + creds.scope_digest("/home/x/.claude-work"),
        )

    def test_ignores_foreground_processes_that_are_not_claude(self):
        runner = self.runner_with(
            [agent("w1:p1")], processes={"w1:p1": [process(50, name="node", argv=["node", "x.js"])]}
        )
        seen = []
        self.run_refresh(runner, read_environ=lambda pid, **_: seen.append(pid) or {})
        self.assertEqual(seen, [])

    def test_missing_credentials_clear_the_token_instead_of_lying(self):
        runner = self.runner_with([agent("w1:p1")])
        self.assertEqual(self.run_refresh(runner, tokens={}), 0)
        report = self.reports(runner)[0]
        self.assertIn("--clear-token", report)
        self.assertEqual(report[report.index("--clear-token") + 1], "claude_usage")
        self.assertNotIn("--ttl-ms", report)
        self.assertEqual(self.fetched, [])

    def test_an_api_failure_leaves_the_existing_token_to_expire(self):
        runner = self.runner_with([agent("w1:p1")])
        self.run_refresh(runner, usages={"tok": api.UsageApiError("401", status=401)})
        self.assertEqual(self.reports(runner), [])
        self.assertTrue(any("401" in line for line in self.logged))

    def test_an_account_with_no_reportable_windows_clears_the_token(self):
        runner = self.runner_with([agent("w1:p1")])
        self.run_refresh(runner, usages={"tok": {"limits": []}})
        self.assertIn("--clear-token", self.reports(runner)[0])

    def test_one_unreportable_pane_does_not_stop_the_others(self):
        agents = [agent("w1:p1"), agent("w1:p2")]
        base = self.runner_with(agents)

        def runner(argv):
            if argv[:4] == ["herdr", "pane", "report-metadata", "w1:p1"]:
                base.calls.append(list(argv))
                return (1, "", "pane_not_found")
            return base(argv)

        runner.calls = base.calls
        runner.calls_matching = base.calls_matching
        self.assertEqual(self.run_refresh(runner), 1)
        self.assertEqual(len(self.reports(runner)), 2)

    def test_a_failing_agent_list_is_reported_not_raised(self):
        runner = FakeRunner({("herdr", "agent", "list"): (1, "", "server_unavailable")})
        with self.assertRaises(HerdrError):
            Herdr(runner=runner).agent_list()
        self.assertEqual(refresh.refresh_quietly(Herdr(runner=runner), config=self.cfg, env={}, log=self.logged.append), 0)
        self.assertTrue(self.logged)


class Caching(unittest.TestCase):
    class Cache:
        def __init__(self, seeded=None):
            self.store = dict(seeded or {})
            self.puts = []

        def get(self, key):
            return self.store.get(key)

        def put(self, key, value):
            self.puts.append(key)
            self.store[key] = value

    def setUp(self):
        self.cfg = config.load(None)
        self.fetched = []

    def run_refresh(self, cache, force=False):
        runner = FakeRunner(
            {("herdr", "agent", "list"): (0, envelope({"agents": [agent("w1:p1")]}), "")}
        )

        def fetch(token, **_):
            self.fetched.append(token)
            return usage()

        refresh.refresh(
            Herdr(runner=runner),
            config=self.cfg,
            env={},
            cache=cache,
            fetch=fetch,
            read_environ=lambda pid, **_: None,
            read_token=lambda scope: "tok",
            home=Path("/home/x"),
            now_ms=lambda: 1,
            force=force,
            log=lambda _: None,
        )
        return runner

    def test_a_cached_response_skips_the_request(self):
        self.run_refresh(self.Cache({"/home/x/.claude": usage()}))
        self.assertEqual(self.fetched, [])

    def test_a_fresh_response_is_written_back(self):
        cache = self.Cache()
        self.run_refresh(cache)
        self.assertEqual(cache.puts, ["/home/x/.claude"])

    def test_force_bypasses_the_cache(self):
        self.run_refresh(self.Cache({"/home/x/.claude": usage()}), force=True)
        self.assertEqual(self.fetched, ["tok"])
