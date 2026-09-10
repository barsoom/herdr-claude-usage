"""One refresh pass: every claude pane gets its own account's usage as a sidebar token."""

import os
import sys
import time
from pathlib import Path

from . import api, config, creds, limits, procenv, render
from .cache import UsageCache
from .herdr import Herdr, HerdrError, default_bin_path

CLAUDE_AGENT = "claude"
SOURCE_ID = config.SOURCE_ID
CACHE_DIR_NAME = "cache"


def _stderr(message):
    print(f"claude-usage: {message}", file=sys.stderr)


def claude_pane_ids(herdr):
    ids = []
    for row in herdr.agent_list():
        if not isinstance(row, dict) or row.get("agent") != CLAUDE_AGENT:
            continue
        pane_id = row.get("pane_id")
        if isinstance(pane_id, str) and pane_id:
            ids.append(pane_id)
    return ids


def _is_claude(process):
    if process.get("name") == CLAUDE_AGENT:
        return True
    argv = process.get("argv") or []
    return bool(argv) and isinstance(argv[0], str) and os.path.basename(argv[0]) == CLAUDE_AGENT


def pane_claude_pid(herdr, pane_id):
    for process in herdr.pane_process_info(pane_id):
        if isinstance(process, dict) and _is_claude(process):
            pid = process.get("pid")
            if isinstance(pid, int):
                return pid
    return None


def pane_config_dir(herdr, pane_id, env, read_environ, home=None):
    """The pane's own CLAUDE_CONFIG_DIR when we can see it, else the plugin's, else ~/.claude."""
    proc_env = None
    try:
        pid = pane_claude_pid(herdr, pane_id)
    except HerdrError:
        pid = None
    if pid is not None:
        proc_env = read_environ(pid)
    return creds.resolve_config_dir(env=env, proc_env=proc_env, home=home)


def refresh(
    herdr,
    config,
    env=None,
    cache=None,
    fetch=api.fetch_usage,
    read_environ=procenv.read_proc_environ,
    read_token=creds.read_access_token,
    home=None,
    now_ms=None,
    force=False,
    log=None,
):
    """Returns how many panes now carry a usage token. Never raises for a single bad pane."""
    env = os.environ if env is None else env
    log = log or _stderr
    now_ms = now_ms or (lambda: int(time.time() * 1000))
    seq = now_ms()

    panes_by_dir = {}
    for pane_id in claude_pane_ids(herdr):
        directory = pane_config_dir(herdr, pane_id, env, read_environ, home=home)
        panes_by_dir.setdefault(str(directory), []).append(pane_id)

    reported = 0
    for directory, pane_ids in panes_by_dir.items():
        value = _token_value(
            directory, config, cache, fetch, read_token, force=force, log=log
        )
        for pane_id in pane_ids:
            try:
                if value:
                    herdr.report_metadata(
                        pane_id,
                        source=SOURCE_ID,
                        tokens={config.token_name: value},
                        seq=seq,
                        ttl_ms=config.ttl_ms,
                    )
                    reported += 1
                elif value is not None:
                    herdr.report_metadata(
                        pane_id, source=SOURCE_ID, clear_tokens=[config.token_name], seq=seq
                    )
            except HerdrError as err:
                log(f"{pane_id}: {err}")
    return reported


def _token_value(directory, config, cache, fetch, read_token, force, log):
    """A string to display, "" to clear the row, or None to leave whatever is there to expire."""
    token = read_token(Path(directory))
    if not token:
        log(f"{directory}: no Claude credentials, clearing the row")
        return ""
    usage = None if force else (cache.get(directory) if cache else None)
    if usage is None:
        try:
            usage = fetch(token)
        except api.UsageApiError as err:
            log(f"{directory}: {err}")
            return None
        if cache:
            cache.put(directory, usage)
    return render.render(limits.extract(usage), config.limits, separator=config.separator)


def refresh_quietly(herdr, config, env=None, log=None, **kwargs):
    """Same pass, but a dead or unreachable server is logged rather than raised."""
    log = log or _stderr
    try:
        return refresh(herdr, config=config, env=env, log=log, **kwargs)
    except HerdrError as err:
        log(str(err))
        return 0


def state_dir(env=None):
    env = os.environ if env is None else env
    raw = env.get("HERDR_PLUGIN_STATE_DIR") or env.get("HERDR_PLUGIN_ROOT") or "."
    return Path(raw)


def build_cache(cfg, env=None, now_ms=None):
    return UsageCache(state_dir(env) / CACHE_DIR_NAME, ttl_ms=cfg.cache_ttl_ms, now_ms=now_ms)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    force = "--force" in argv
    env = os.environ
    cfg = config.load_from_env(env, log=_stderr)
    herdr = Herdr(bin_path=default_bin_path(env))
    refresh_quietly(herdr, config=cfg, env=env, cache=build_cache(cfg, env), force=force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
