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
