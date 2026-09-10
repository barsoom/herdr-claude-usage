"""Poll loop. Plugins get no timer surface, so the startup hook leaves this behind."""

import os
import signal
import sys
import time
from pathlib import Path

from . import config
from .herdr import Herdr, default_bin_path
from .refresh import build_cache, refresh_quietly, state_dir

PIDFILE_NAME = "daemon.pid"
TAKEOVER_TIMEOUT_S = 2.0
TAKEOVER_POLL_S = 0.1


def _stderr(message):
    print(f"claude-usage daemon: {message}", file=sys.stderr)


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


def run_loop(tick, interval_seconds, should_continue, sleep=time.sleep, log=None):
    log = log or _stderr
    while should_continue():
        try:
            tick()
        except Exception as err:  # a transient failure must not end the loop
            log(f"tick failed: {err}")
        sleep(interval_seconds)


def _daemonize():
    """Double fork so the startup hook completes instead of hanging on us."""
    if os.fork() > 0:
        os._exit(0)
    os.setsid()
    if os.fork() > 0:
        os._exit(0)
    devnull = os.open(os.devnull, os.O_RDWR)
    os.dup2(devnull, 0)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    env = os.environ
    cfg = config.load_from_env(env, log=_stderr)
    if "--foreground" not in argv:
        _daemonize()

    pidfile = state_dir(env) / PIDFILE_NAME
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
    try:
        run_loop(
            tick=lambda: refresh_quietly(herdr, config=cfg, env=env, cache=cache),
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
