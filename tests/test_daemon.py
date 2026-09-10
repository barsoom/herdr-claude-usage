import tempfile
import unittest
from pathlib import Path

from claude_usage import daemon


class Pidfile(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "daemon.pid"
        self.addCleanup(self.tmp.cleanup)

    def test_round_trips_a_pid(self):
        daemon.write_pidfile(self.path, 4242)
        self.assertEqual(daemon.read_pidfile(self.path), 4242)

    def test_missing_file_yields_none(self):
        self.assertIsNone(daemon.read_pidfile(self.path))

    def test_garbage_yields_none(self):
        self.path.write_text("not a pid", encoding="utf-8")
        self.assertIsNone(daemon.read_pidfile(self.path))


class Takeover(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "daemon.pid"
        self.addCleanup(self.tmp.cleanup)
        self.terminated = []
        self.slept = []

    def takeover(self, alive):
        return daemon.takeover(
            self.path,
            self_pid=999,
            alive=alive,
            terminate=self.terminated.append,
            sleep=self.slept.append,
            timeout_s=0.3,
        )

    def test_terminates_a_live_predecessor(self):
        daemon.write_pidfile(self.path, 100)
        states = iter([True, False])
        self.assertEqual(self.takeover(lambda pid: next(states, False)), 100)
        self.assertEqual(self.terminated, [100])

    def test_leaves_a_dead_predecessor_alone(self):
        daemon.write_pidfile(self.path, 100)
        self.assertIsNone(self.takeover(lambda pid: False))
        self.assertEqual(self.terminated, [])

    def test_never_signals_itself(self):
        daemon.write_pidfile(self.path, 999)
        self.assertIsNone(self.takeover(lambda pid: True))
        self.assertEqual(self.terminated, [])

    def test_gives_up_after_the_timeout(self):
        daemon.write_pidfile(self.path, 100)
        self.assertEqual(self.takeover(lambda pid: True), 100)
        self.assertTrue(self.slept)

    def test_no_pidfile_is_not_a_takeover(self):
        self.assertIsNone(self.takeover(lambda pid: True))


class ServerAlive(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_true_while_the_socket_exists(self):
        sock = Path(self.tmp.name) / "herdr.sock"
        sock.touch()
        self.assertTrue(daemon.server_alive({"HERDR_SOCKET_PATH": str(sock)}))

    def test_false_once_the_socket_is_gone(self):
        self.assertFalse(daemon.server_alive({"HERDR_SOCKET_PATH": str(Path(self.tmp.name) / "gone")}))

    def test_true_when_no_socket_path_was_injected(self):
        self.assertTrue(daemon.server_alive({}))


class RunLoop(unittest.TestCase):
    def run_loop(self, *, interval, slice_seconds, stop_after_sleeps, tick=None, log=None):
        """Driven off sleep count, so a test says how far into the interval the server dies."""
        self.slept = []
        self.ticks = []

        daemon.run_loop(
            tick=tick or (lambda: self.ticks.append(1)),
            interval_seconds=interval,
            should_continue=lambda: len(self.slept) < stop_after_sleeps,
            sleep=self.slept.append,
            slice_seconds=slice_seconds,
            log=log,
        )

    def test_ticks_once_per_interval(self):
        self.run_loop(interval=10, slice_seconds=10, stop_after_sleeps=2)
        self.assertEqual(len(self.ticks), 2)

    def test_does_not_tick_at_all_once_the_server_is_gone(self):
        self.run_loop(interval=10, slice_seconds=10, stop_after_sleeps=0)
        self.assertEqual(self.ticks, [])

    def test_sleeps_the_configured_interval_in_slices(self):
        self.run_loop(interval=90, slice_seconds=5, stop_after_sleeps=18)
        self.assertEqual(sum(self.slept), 90)
        self.assertEqual(max(self.slept), 5)

    def test_a_long_interval_cannot_delay_the_orphan_guard(self):
        """An hourly poll must not keep a dead server's loop alive for an hour."""
        self.run_loop(interval=3600, slice_seconds=5, stop_after_sleeps=1)
        self.assertEqual(self.slept, [5])
        self.assertEqual(len(self.ticks), 1)

    def test_a_failing_tick_does_not_end_the_loop(self):
        def tick():
            self.ticks.append(1)
            raise RuntimeError("transient")

        logged = []
        self.run_loop(interval=1, slice_seconds=1, stop_after_sleeps=2, tick=tick, log=logged.append)
        self.assertEqual(len(self.ticks), 2)
        self.assertTrue(logged)
