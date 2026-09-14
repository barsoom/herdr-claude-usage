"""Stderr lines. The daemon's stderr is a log file that outlives any one run, so lines carry a time."""

import sys
import time

DEFAULT_SOURCE = "claude-usage"
STAMP_FORMAT = "%Y-%m-%d %H:%M:%S"


def stamp(now=None, format=STAMP_FORMAT):
    return time.strftime(format, time.localtime((now or time.time)()))


def stderr(message, source=DEFAULT_SOURCE, now=None, stream=None):
    print(f"{stamp(now)} {source}: {message}", file=stream or sys.stderr)
