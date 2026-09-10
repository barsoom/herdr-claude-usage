"""Read another process's environment, to learn which Claude account a pane runs under."""

import re
import subprocess
import sys
from pathlib import Path

PROC_ROOT = "/proc"
PS_TIMEOUT_S = 5.0

# A ps line is `command args KEY=VAL KEY=VAL ...` with no quoting, so a value ends where the next
# assignment begins. A value containing spaces therefore truncates — which costs us the row, not
# correctness: a truncated path holds no credentials, so the row clears instead of showing someone
# else's numbers.
_ASSIGNMENT = re.compile(r"(?:^|\s)([A-Za-z_][A-Za-z0-9_]*)=")


def _run(argv, timeout=PS_TIMEOUT_S):
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    return (proc.returncode, proc.stdout, proc.stderr)


def read_proc_environ(pid, root=PROC_ROOT):
    try:
        raw = (Path(root) / str(pid) / "environ").read_bytes()
    except OSError:
        return None
    env = {}
    for entry in raw.split(b"\0"):
        if not entry:
            continue
        name, sep, value = entry.partition(b"=")
        if not sep:
            continue
        env[name.decode("utf-8", "replace")] = value.decode("utf-8", "replace")
    return env


def parse_ps_environ(line):
    matches = list(_ASSIGNMENT.finditer(line))
    if not matches:
        return None
    env = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(line)
        env[match.group(1)] = line[match.end() : end]
    return env


def read_ps_environ(pid, runner=None):
    runner = runner or _run
    try:
        code, stdout, _ = runner(["ps", "-E", "-ww", "-o", "command=", "-p", str(pid)])
    except (OSError, subprocess.SubprocessError):
        return None
    if code != 0:
        return None
    return parse_ps_environ(stdout.strip())


def read_environ(pid, platform=None, proc_reader=read_proc_environ, ps_reader=read_ps_environ):
    platform = sys.platform if platform is None else platform
    if platform.startswith("linux"):
        return proc_reader(pid)
    if platform.startswith("darwin"):
        return ps_reader(pid)
    return None
