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
    def test_ticks_until_the_server_goes_away(self):
        ticks = []
        alive = iter([True, True, False])
        daemon.run_loop(
            tick=lambda: ticks.append(1),
            interval_seconds=60,
            should_continue=lambda: next(alive, False),
            sleep=lambda _: None,
        )
        self.assertEqual(len(ticks), 2)

    def test_sleeps_the_configured_interval(self):
        slept = []
        alive = iter([True, False])
        daemon.run_loop(
            tick=lambda: None,
            interval_seconds=90,
            should_continue=lambda: next(alive, False),
            sleep=slept.append,
        )
        self.assertEqual(slept, [90])

    def test_a_failing_tick_does_not_end_the_loop(self):
        ticks = []
        alive = iter([True, True, False])

        def tick():
            ticks.append(1)
            raise RuntimeError("transient")

        logged = []
        daemon.run_loop(
            tick=tick,
            interval_seconds=1,
            should_continue=lambda: next(alive, False),
            sleep=lambda _: None,
            log=logged.append,
        )
        self.assertEqual(len(ticks), 2)
        self.assertTrue(logged)
