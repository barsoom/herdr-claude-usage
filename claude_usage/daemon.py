"""Poll loop. Plugins get no timer surface, so the startup hook leaves this behind."""

import os
import signal
import sys
import time
from pathlib import Path

from . import config, log
from .herdr import Herdr, default_bin_path
from .refresh import build_cache, build_gate, refresh_quietly, state_dir

PIDFILE_NAME = "daemon.pid"
LOGFILE_NAME = "daemon.log"
MAX_LOG_BYTES = 1 << 20
# Upper bound on how long an orphaned loop can outlive its server, whatever the poll interval.
SLEEP_SLICE_S = 5.0
TAKEOVER_TIMEOUT_S = 2.0
TAKEOVER_POLL_S = 0.1


def _stderr(message):
    log.stderr(message, source="claude-usage daemon")


def read_pidfile(path):
    try:
        return int(Path(path).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def write_pidfile(path, pid):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(pid), encoding="utf-8")


def process_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def takeover(pidfile, self_pid, alive=process_alive, terminate=None, sleep=time.sleep, timeout_s=TAKEOVER_TIMEOUT_S):
    """Replace the previous loop. This is what makes a live handoff swap rather than duplicate."""
    terminate = terminate or (lambda pid: os.kill(pid, signal.SIGTERM))
    pid = read_pidfile(pidfile)
    if pid is None or pid == self_pid or not alive(pid):
        return None
    try:
        terminate(pid)
    except OSError:
        return None
    waited = 0.0
    while waited < timeout_s:
        sleep(TAKEOVER_POLL_S)
        waited += TAKEOVER_POLL_S
        if not alive(pid):
            break
    return pid


def server_alive(env=None):
    """No socket, no server. Keeps the loop from outliving the Herdr it was started by."""
    env = os.environ if env is None else env
    socket_path = env.get("HERDR_SOCKET_PATH")
    if not socket_path:
        return True
    return Path(socket_path).exists()


def _nap(interval_seconds, should_continue, sleep, slice_seconds):
    """Sleep the interval in slices, so a long interval cannot delay the orphan guard."""
    remaining = interval_seconds
    while remaining > 0:
        nap = min(slice_seconds, remaining)
        sleep(nap)
        remaining -= nap
        if not should_continue():
            return False
    return True


def run_loop(
    tick,
    interval_seconds,
    should_continue,
    sleep=time.sleep,
    log=None,
    slice_seconds=SLEEP_SLICE_S,
):
    log = log or _stderr
    while should_continue():
        try:
            tick()
        except Exception as err:  # a transient failure must not end the loop
            log(f"tick failed: {err}")
        if not _nap(interval_seconds, should_continue, sleep, slice_seconds):
            return


def _detach_streams(log_path):
    """Let go of Herdr's capture pipes, or Herdr waits forever for an EOF that never comes.

    Herdr records a plugin command's completion once its output closes. A loop that keeps the
    inherited stdout/stderr write ends open hangs Herdr on start, so both go to a log file in the
    state dir instead — losing the diagnostics entirely would be the worse trade.
    """
    devnull = os.open(os.devnull, os.O_RDONLY)
    os.dup2(devnull, 0)
    os.close(devnull)
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        if log_path.exists() and log_path.stat().st_size > MAX_LOG_BYTES:
            log_path.unlink()
        target = os.open(str(log_path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    except OSError:
        target = os.open(os.devnull, os.O_WRONLY)
    os.dup2(target, 1)
    os.dup2(target, 2)
    os.close(target)


def _daemonize(log_path):
    """Double fork so the startup hook completes instead of hanging on us."""
    if os.fork() > 0:
        os._exit(0)
    os.setsid()
    if os.fork() > 0:
        os._exit(0)
    _detach_streams(log_path)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    env = os.environ
    cfg = config.load_from_env(env, log=_stderr)
    state = state_dir(env)
    if "--foreground" not in argv:
        # Said on the pipe Herdr still captures, so `plugin log list` points at the real log.
        _stderr(f"detaching; logging to {state / LOGFILE_NAME}")
        _daemonize(state / LOGFILE_NAME)

    pidfile = state / PIDFILE_NAME
    self_pid = os.getpid()
    replaced = takeover(pidfile, self_pid=self_pid)
    if replaced:
        _stderr(f"replaced previous daemon {replaced}")
    write_pidfile(pidfile, self_pid)

    def stop(signum, frame):
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    herdr = Herdr(bin_path=default_bin_path(env))
    cache = build_cache(cfg, env)
    gate = build_gate(cfg, env)
    try:
        run_loop(
            tick=lambda: refresh_quietly(herdr, config=cfg, env=env, cache=cache, gate=gate),
            interval_seconds=cfg.interval_seconds,
            should_continue=lambda: server_alive(env),
        )
    finally:
        if read_pidfile(pidfile) == self_pid:
            try:
                pidfile.unlink()
            except OSError:
                pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
