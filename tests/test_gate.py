import tempfile
import unittest
from pathlib import Path

from claude_usage.gate import RetryGate


class Gate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "gate"
        self.addCleanup(self.tmp.cleanup)
        self.now = 1_000_000

    def gate(self, base_ms=60_000, max_ms=600_000):
        return RetryGate(self.dir, base_delay_ms=base_ms, max_delay_ms=max_ms, now_ms=lambda: self.now)

    def test_an_untouched_key_is_open(self):
        self.assertFalse(self.gate().blocked("k"))

    def test_a_penalty_closes_the_gate_for_the_base_delay(self):
        g = self.gate()
        self.assertEqual(g.penalize("k"), 60_000)
        self.assertTrue(g.blocked("k"))

    def test_the_gate_reopens_once_the_delay_elapses(self):
        self.gate().penalize("k")
        self.now += 60_000
        self.assertFalse(self.gate().blocked("k"))

    def test_repeated_penalties_double_the_delay(self):
        g = self.gate()
        g.penalize("k")
        self.assertEqual(g.penalize("k"), 120_000)
        self.assertEqual(g.penalize("k"), 240_000)

    def test_the_delay_stops_at_the_ceiling(self):
        g = self.gate()
        for _ in range(10):
            delay = g.penalize("k")
        self.assertEqual(delay, 600_000)

    def test_a_success_clears_the_penalty(self):
        g = self.gate()
        g.penalize("k")
        g.clear("k")
        self.assertFalse(g.blocked("k"))
        self.assertEqual(g.penalize("k"), 60_000)

    def test_the_penalty_outlives_the_process_that_earned_it(self):
        """The event hook and the action are their own processes; in-memory backoff would leak."""
        self.gate().penalize("k")
        self.assertTrue(self.gate().blocked("k"))

    def test_keys_back_off_independently(self):
        g = self.gate()
        g.penalize("a")
        self.assertFalse(g.blocked("b"))

    def test_corrupt_state_is_treated_as_open(self):
        g = self.gate()
        g.penalize("k")
        next(self.dir.iterdir()).write_text("{ broken", encoding="utf-8")
        self.assertFalse(self.gate().blocked("k"))

    def test_clearing_a_key_that_never_failed_is_harmless(self):
        self.gate().clear("k")

    def test_an_unwritable_directory_is_survivable(self):
        g = RetryGate(
            Path("/proc/nonexistent/gate"),
            base_delay_ms=1000,
            max_delay_ms=2000,
            now_ms=lambda: self.now,
        )
        self.assertEqual(g.penalize("k"), 1000)
        self.assertFalse(g.blocked("k"))
