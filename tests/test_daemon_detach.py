"""The startup hook must let go of Herdr's stdout/stderr pipes.

Herdr captures a plugin command's output and waits for EOF to record completion. A detached loop that
keeps the inherited write ends open never delivers that EOF, and Herdr hangs on startup. This is a
real subprocess on purpose: the bug lives in file descriptors, which fakes cannot express.
"""

import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PIPE_CLOSE_TIMEOUT_S = 15


def alive(pid):
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


@unittest.skipUnless(hasattr(os, "fork"), "the daemon detaches by forking")
class StartupHookReleasesItsPipes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        # A socket path that exists, so the loop does not exit before we can look at it.
        (self.state / "fake.sock").touch()
        (self.state / "config.json").write_text('{"interval_seconds": 15}', encoding="utf-8")
        self.addCleanup(self.stop_daemon)

    def stop_daemon(self):
        """Reads the pidfile itself: relying on a test body to record the pid leaks daemons."""
        pid = self.read_pid(timeout_s=2)
        if pid and alive(pid):
            os.kill(pid, signal.SIGTERM)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and alive(pid):
                time.sleep(0.05)

    def spawn(self):
        env = dict(os.environ)
        env.update(
            {
                "HERDR_PLUGIN_STATE_DIR": str(self.state),
                "HERDR_PLUGIN_CONFIG_DIR": str(self.state),
                "HERDR_SOCKET_PATH": str(self.state / "fake.sock"),
                # Stands in for the herdr CLI: every call fails, which the loop must survive.
                "HERDR_BIN_PATH": "/bin/false",
            }
        )
        return subprocess.Popen(
            [sys.executable, "-m", "claude_usage.daemon"],
            cwd=str(REPO_ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def read_pid(self, timeout_s=10):
        pidfile = self.state / "daemon.pid"
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            try:
                return int(pidfile.read_text(encoding="utf-8").strip())
            except (OSError, ValueError):
                time.sleep(0.05)
        return None

    def test_the_hook_exits_and_its_pipes_reach_eof(self):
        proc = self.spawn()
        try:
            stdout, stderr = proc.communicate(timeout=PIPE_CLOSE_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            proc.kill()
            self.fail("startup hook never closed its pipes; Herdr would hang on start")
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(stdout, "")
        # The one thing worth saying on the captured pipe: where the loop's own log went.
        self.assertIn(str(self.state / "daemon.log"), stderr)

    def test_the_loop_outlives_the_hook(self):
        proc = self.spawn()
        proc.communicate(timeout=PIPE_CLOSE_TIMEOUT_S)
        pid = self.read_pid()
        self.assertIsNotNone(pid, "no pidfile was written")
        self.assertNotEqual(pid, proc.pid)
        self.assertTrue(alive(pid), "the detached loop died with its parent")

    def test_diagnostics_land_in_the_state_directory_instead_of_being_lost(self):
        proc = self.spawn()
        proc.communicate(timeout=PIPE_CLOSE_TIMEOUT_S)
        self.read_pid()
        log = self.state / "daemon.log"
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if log.exists() and log.read_text(encoding="utf-8").strip():
                break
            time.sleep(0.05)
        self.assertTrue(log.exists(), "detaching the pipes must not silence the loop")
        self.assertIn("claude-usage", log.read_text(encoding="utf-8"))
