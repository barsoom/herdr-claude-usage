import io
import re
import unittest
from contextlib import redirect_stderr

from claude_usage import daemon, log, refresh

STAMPED = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} ")


class Stamp(unittest.TestCase):
    """The daemon's stderr is a log file that outlives any one run, so a bare line is useless."""

    def test_every_line_opens_with_a_wall_clock_timestamp(self):
        out = io.StringIO()
        log.stderr("HTTP 429", stream=out)
        self.assertRegex(out.getvalue(), STAMPED)

    def test_the_source_and_message_survive_the_stamp(self):
        out = io.StringIO()
        log.stderr("HTTP 429", stream=out)
        self.assertTrue(out.getvalue().rstrip().endswith("claude-usage: HTTP 429"))

    def test_the_stamp_follows_the_clock(self):
        out = io.StringIO()
        log.stderr("a", now=lambda: 0, stream=out)
        log.stderr("b", now=lambda: 86_400, stream=out)
        first, second = [line.split()[0] for line in out.getvalue().splitlines()]
        self.assertNotEqual(first, second)

    def test_the_daemon_stamps_and_labels_its_own_lines(self):
        out = io.StringIO()
        with redirect_stderr(out):
            daemon._stderr("replaced previous daemon 7")
        self.assertRegex(out.getvalue(), STAMPED)
        self.assertIn("claude-usage daemon: replaced previous daemon 7", out.getvalue())

    def test_a_refresh_line_is_stamped_too(self):
        out = io.StringIO()
        with redirect_stderr(out):
            refresh._stderr("/home/x/.claude: HTTP 429")
        self.assertRegex(out.getvalue(), STAMPED)
        self.assertIn("claude-usage: /home/x/.claude: HTTP 429", out.getvalue())
