"""Read another process's environment. Linux /proc only; everything else gets None."""

from pathlib import Path

PROC_ROOT = "/proc"


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
