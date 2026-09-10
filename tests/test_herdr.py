import json
import unittest

from claude_usage.herdr import Herdr, HerdrError
from tests.support import FakeRunner, agent, envelope, process


class AgentList(unittest.TestCase):
    def test_returns_the_agent_rows(self):
        runner = FakeRunner({("herdr", "agent", "list"): (0, envelope({"agents": [agent("w1:p1")]}), "")})
        self.assertEqual(Herdr(runner=runner).agent_list()[0]["pane_id"], "w1:p1")

    def test_uses_the_configured_binary_path(self):
        runner = FakeRunner({("/opt/herdr", "agent", "list"): (0, envelope({"agents": []}), "")})
        Herdr(bin_path="/opt/herdr", runner=runner).agent_list()
        self.assertEqual(runner.calls[0][0], "/opt/herdr")

    def test_missing_agents_key_yields_an_empty_list(self):
        runner = FakeRunner({("herdr", "agent", "list"): (0, envelope({}), "")})
        self.assertEqual(Herdr(runner=runner).agent_list(), [])

    def test_nonzero_exit_raises(self):
        runner = FakeRunner({("herdr", "agent", "list"): (1, "", "boom")})
        with self.assertRaises(HerdrError):
            Herdr(runner=runner).agent_list()

    def test_error_envelope_raises(self):
        payload = json.dumps({"id": "x", "error": {"code": "pane_not_found", "message": "nope"}})
        runner = FakeRunner({("herdr", "agent", "list"): (0, payload, "")})
        with self.assertRaises(HerdrError) as ctx:
            Herdr(runner=runner).agent_list()
        self.assertIn("pane_not_found", str(ctx.exception))

    def test_unparseable_output_raises(self):
        runner = FakeRunner({("herdr", "agent", "list"): (0, "not json", "")})
        with self.assertRaises(HerdrError):
            Herdr(runner=runner).agent_list()


class PaneProcessInfo(unittest.TestCase):
    def test_returns_foreground_processes(self):
        result = {"process_info": {"foreground_processes": [process(7)]}}
        runner = FakeRunner({("herdr", "pane", "process-info"): (0, envelope(result), "")})
        got = Herdr(runner=runner).pane_process_info("w1:p1")
        self.assertEqual(got[0]["pid"], 7)
        self.assertEqual(runner.calls[0][-2:], ["--pane", "w1:p1"])

    def test_absent_process_info_yields_an_empty_list(self):
        runner = FakeRunner({("herdr", "pane", "process-info"): (0, envelope({}), "")})
        self.assertEqual(Herdr(runner=runner).pane_process_info("w1:p1"), [])


class ReportMetadata(unittest.TestCase):
    def test_builds_the_token_report_argv(self):
        runner = FakeRunner()
        Herdr(runner=runner).report_metadata(
            "w1:p1", source="barsoom.claude-usage", tokens={"claude_usage": "5h 14%"}, seq=99, ttl_ms=150000
        )
        self.assertEqual(
            runner.calls[0],
            [
                "herdr", "pane", "report-metadata", "w1:p1",
                "--source", "barsoom.claude-usage",
                "--token", "claude_usage=5h 14%",
                "--seq", "99",
                "--ttl-ms", "150000",
            ],
        )

    def test_builds_the_clear_argv_without_a_ttl(self):
        runner = FakeRunner()
        Herdr(runner=runner).report_metadata(
            "w1:p1", source="s", clear_tokens=["claude_usage"], seq=5
        )
        self.assertEqual(
            runner.calls[0],
            ["herdr", "pane", "report-metadata", "w1:p1", "--source", "s", "--clear-token", "claude_usage", "--seq", "5"],
        )

    def test_succeeds_on_the_empty_output_the_cli_actually_prints(self):
        runner = FakeRunner({("herdr", "pane", "report-metadata"): (0, "", "")})
        Herdr(runner=runner).report_metadata("w1:p1", source="s", tokens={"t": "v"}, ttl_ms=1000)
        self.assertEqual(len(runner.calls), 1)

    def test_a_rejected_report_still_raises(self):
        runner = FakeRunner({("herdr", "pane", "report-metadata"): (1, "", "invalid_pane_id")})
        with self.assertRaises(HerdrError):
            Herdr(runner=runner).report_metadata("nope", source="s", tokens={"t": "v"})

    def test_reporting_nothing_makes_no_call(self):
        runner = FakeRunner()
        Herdr(runner=runner).report_metadata("w1:p1", source="s")
        self.assertEqual(runner.calls, [])
