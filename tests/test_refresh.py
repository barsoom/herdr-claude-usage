import tempfile
import unittest
from pathlib import Path

from claude_usage import api, config, creds, refresh
from claude_usage.cache import UsageCache
from claude_usage.gate import RetryGate
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


class PaneCase(unittest.TestCase):
    """Setup and fakes shared by the style-specific passes. Holds no tests itself."""

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


class Pass(PaneCase):
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

        def get(self, key, ttl_ms=None):
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


class BarsStyle(PaneCase):
    def setUp(self):
        super().setUp()
        self.cfg = config.Config(style=config.STYLE_BARS, bar_width=8)

    def test_reports_the_bar_token_when_the_style_asks_for_bars(self):
        from claude_usage import limits, render

        runner = self.runner_with([agent("w1:p1")])
        self.assertEqual(self.run_refresh(runner), 1)
        report = self.reports(runner)[0]
        expected = render.render_bars(limits.extract(usage()), self.cfg.limits, 8)
        self.assertEqual(report[report.index("--token") + 1], f"claude_usage={expected}")


class StatefulCase(PaneCase):
    """Real cache and gate over a temp dir, on a clock the test moves. Holds no tests itself."""

    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.now = 1_000_000
        now_ms = lambda: self.now
        self.cache = UsageCache(Path(tmp.name) / "cache", ttl_ms=self.cfg.cache_ttl_ms, now_ms=now_ms)
        self.gate = RetryGate(
            Path(tmp.name) / "gate",
            base_delay_ms=self.cfg.backoff_base_ms,
            max_delay_ms=self.cfg.backoff_max_ms,
            now_ms=now_ms,
        )

    def run_refresh(self, runner, **kw):
        kw.setdefault("cache", self.cache)
        kw.setdefault("gate", self.gate)
        return super().run_refresh(runner, **kw)

    def rate_limited(self):
        return {"tok": api.UsageApiError("HTTP 429", status=429)}

    def seed(self, **kw):
        self.cache.put("/home/x/.claude", usage(**kw))

    def token_of(self, runner):
        report = self.reports(runner)[0]
        return report[report.index("--token") + 1]

    def working(self, *pane_ids):
        """Panes on the working cadence, so a test about fetching actually fetches."""
        return self.runner_with([agent(p, agent_status="working") for p in pane_ids or ("w1:p1",)])


class RateLimited(StatefulCase):
    """429 is the normal weather on this endpoint: the row must survive it, and back off."""

    def test_a_failed_fetch_keeps_showing_the_last_good_value(self):
        self.seed(session=1, weekly=2, fable=3)
        self.now += self.cfg.cache_ttl_ms + 1
        runner = self.working()
        self.assertEqual(self.run_refresh(runner, usages=self.rate_limited()), 1)
        self.assertEqual(self.token_of(runner), "claude_usage=5h 1% · 1w 2% · Fable 3%")

    def test_a_value_too_old_to_trust_is_left_to_expire(self):
        self.seed()
        self.now += self.cfg.max_stale_ms + 1
        runner = self.working()
        self.run_refresh(runner, usages=self.rate_limited())
        self.assertEqual(self.reports(runner), [])

    def test_a_failure_with_nothing_cached_leaves_the_row_to_expire(self):
        runner = self.working()
        self.run_refresh(runner, usages=self.rate_limited())
        self.assertEqual(self.reports(runner), [])

    def test_a_failure_holds_off_the_next_request(self):
        runner = self.working()
        self.run_refresh(runner, usages=self.rate_limited())
        self.now += self.cfg.backoff_base_ms - 1
        self.run_refresh(self.working(), usages=self.rate_limited())
        self.assertEqual(len(self.fetched), 1)

    def test_the_hold_off_expires(self):
        runner = self.working()
        self.run_refresh(runner, usages=self.rate_limited())
        self.now += self.cfg.backoff_base_ms + 1
        self.run_refresh(self.working(), usages=self.rate_limited())
        self.assertEqual(len(self.fetched), 2)

    def test_a_success_lifts_the_hold_off(self):
        self.run_refresh(self.working(), usages=self.rate_limited())
        self.now += self.cfg.backoff_base_ms + 1
        self.run_refresh(self.working())
        self.now += self.cfg.cache_ttl_ms + 1
        self.run_refresh(self.working())
        self.assertEqual(len(self.fetched), 3)

    def test_the_manual_action_ignores_the_hold_off(self):
        """User-initiated, so it is allowed to spend the one request the backoff was saving."""
        self.run_refresh(self.working(), usages=self.rate_limited())
        self.run_refresh(self.working(), force=True)
        self.assertEqual(len(self.fetched), 2)

    def test_a_held_off_scope_still_serves_its_cached_value(self):
        self.seed(session=4, weekly=5, fable=6)
        self.run_refresh(self.working(), usages=self.rate_limited())
        self.now += self.cfg.cache_ttl_ms + 1
        runner = self.working()
        self.run_refresh(runner, usages=self.rate_limited())
        self.assertEqual(len(self.fetched), 1)
        self.assertEqual(self.token_of(runner), "claude_usage=5h 4% · 1w 5% · Fable 6%")

    def test_the_backoff_delay_is_logged(self):
        self.run_refresh(self.working(), usages=self.rate_limited())
        self.assertTrue(any("429" in line and "retrying" in line for line in self.logged))


class Cadence(StatefulCase):
    """An idle pane is not spending limit, so its account does not need the working cadence."""

    def stale_by_one_interval(self):
        self.seed()
        self.now += self.cfg.cache_ttl_ms + 1

    def test_an_idle_pane_does_not_spend_a_request(self):
        self.stale_by_one_interval()
        runner = self.runner_with([agent("w1:p1", agent_status="idle")])
        self.assertEqual(self.run_refresh(runner), 1)
        self.assertEqual(self.fetched, [])
        self.assertTrue(self.token_of(runner))

    def test_a_working_pane_keeps_the_full_cadence(self):
        self.stale_by_one_interval()
        self.run_refresh(self.runner_with([agent("w1:p1", agent_status="working")]))
        self.assertEqual(self.fetched, ["tok"])

    def test_one_working_pane_refreshes_the_whole_account(self):
        self.stale_by_one_interval()
        agents = [agent("w1:p1", agent_status="idle"), agent("w1:p2", agent_status="working")]
        self.run_refresh(self.runner_with(agents))
        self.assertEqual(self.fetched, ["tok"])

    def test_a_row_carrying_no_status_keeps_the_full_cadence(self):
        """Herdr older than agent_status: fall back to the cadence this plugin always had."""
        self.stale_by_one_interval()
        row = agent("w1:p1")
        row.pop("agent_status")
        self.run_refresh(self.runner_with([row]))
        self.assertEqual(self.fetched, ["tok"])

    def test_an_idle_account_is_still_polled_eventually(self):
        self.seed()
        self.now += self.cfg.idle_ttl_ms + 1
        self.run_refresh(self.runner_with([agent("w1:p1", agent_status="idle")]))
        self.assertEqual(self.fetched, ["tok"])

    def test_an_idle_pane_with_nothing_cached_is_polled_at_once(self):
        self.run_refresh(self.runner_with([agent("w1:p1", agent_status="idle")]))
        self.assertEqual(self.fetched, ["tok"])

    def test_the_manual_action_ignores_the_idle_cadence(self):
        self.stale_by_one_interval()
        self.run_refresh(self.runner_with([agent("w1:p1", agent_status="idle")]), force=True)
        self.assertEqual(self.fetched, ["tok"])
