import tempfile
import unittest
from pathlib import Path

from claude_usage import procenv


class ReadProcEnviron(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def write(self, pid, raw):
        d = self.root / str(pid)
        d.mkdir()
        (d / "environ").write_bytes(raw)

    def test_parses_nul_separated_pairs(self):
        self.write(42, b"HOME=/home/x\x00CLAUDE_CONFIG_DIR=/w\x00")
        got = procenv.read_proc_environ(42, root=self.root)
        self.assertEqual(got["CLAUDE_CONFIG_DIR"], "/w")

    def test_tolerates_a_missing_trailing_nul(self):
        self.write(43, b"A=1\x00B=2")
        self.assertEqual(procenv.read_proc_environ(43, root=self.root), {"A": "1", "B": "2"})

    def test_keeps_equals_signs_inside_values(self):
        self.write(44, b"X=a=b\x00")
        self.assertEqual(procenv.read_proc_environ(44, root=self.root)["X"], "a=b")

    def test_skips_entries_without_an_equals_sign(self):
        self.write(45, b"junk\x00A=1\x00")
        self.assertEqual(procenv.read_proc_environ(45, root=self.root), {"A": "1"})

    def test_unreadable_pid_yields_none(self):
        self.assertIsNone(procenv.read_proc_environ(999999, root=self.root))


class ReadPsEnviron(unittest.TestCase):
    """macOS has no /proc. `ps -E` is best effort: worst case is an empty row, never a wrong one."""

    def runner(self, response):
        self.calls = []

        def run(argv):
            self.calls.append(argv)
            return response

        return run

    def test_extracts_the_config_dir_from_a_ps_line(self):
        line = "/usr/local/bin/claude HOME=/Users/x CLAUDE_CONFIG_DIR=/Users/x/.claude-work PATH=/usr/bin"
        got = procenv.read_ps_environ(9, runner=self.runner((0, line + "\n", "")))
        self.assertEqual(got["CLAUDE_CONFIG_DIR"], "/Users/x/.claude-work")
        self.assertEqual(self.calls[0], ["ps", "-E", "-ww", "-o", "command=", "-p", "9"])

    def test_keeps_equals_signs_inside_a_value(self):
        got = procenv.read_ps_environ(9, runner=self.runner((0, "claude A=x=y B=2", "")))
        self.assertEqual(got["A"], "x=y")

    def test_stops_a_value_at_the_next_assignment(self):
        """A path containing spaces truncates. That yields no credentials, not wrong ones."""
        got = procenv.read_ps_environ(9, runner=self.runner((0, "claude A=/two words B=2", "")))
        self.assertEqual(got["A"], "/two words")

    def test_a_failed_ps_yields_none(self):
        self.assertIsNone(procenv.read_ps_environ(9, runner=self.runner((1, "", "no such process"))))

    def test_output_without_any_assignment_yields_none(self):
        self.assertIsNone(procenv.read_ps_environ(9, runner=self.runner((0, "claude --resume", ""))))

    def test_a_missing_ps_binary_yields_none(self):
        def run(argv):
            raise FileNotFoundError("ps")

        self.assertIsNone(procenv.read_ps_environ(9, runner=run))


class ReadEnviron(unittest.TestCase):
    def test_linux_reads_proc(self):
        called = []
        procenv.read_environ(5, platform="linux", proc_reader=lambda pid: called.append(pid) or {"A": "1"})
        self.assertEqual(called, [5])

    def test_macos_shells_out_to_ps(self):
        called = []
        procenv.read_environ(5, platform="darwin", ps_reader=lambda pid: called.append(pid) or {"A": "1"})
        self.assertEqual(called, [5])

    def test_an_unsupported_platform_reads_nothing(self):
        self.assertIsNone(procenv.read_environ(5, platform="win32"))
