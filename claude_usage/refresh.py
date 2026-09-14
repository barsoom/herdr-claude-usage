"""One refresh pass: every claude pane gets its own account's usage as a sidebar token."""

import os
import sys
import time
from pathlib import Path

from . import api, config, creds, limits, log, procenv, render
from .cache import UsageCache
from .gate import RetryGate
from .herdr import Herdr, HerdrError, default_bin_path

CLAUDE_AGENT = "claude"
# Only a working pane is spending limit. An unrecognised status reads as idle: the slow cadence and
# the manual action are a safer place to land than polling every account on the machine at full rate.
WORKING_STATUS = "working"
SOURCE_ID = config.SOURCE_ID
CACHE_DIR_NAME = "cache"
GATE_DIR_NAME = "gate"


def _stderr(message):
    log.stderr(message)


def claude_panes(herdr):
    """(pane_id, working) per claude pane. A row with no status at all predates agent_status."""
    panes = []
    for row in herdr.agent_list():
        if not isinstance(row, dict) or row.get("agent") != CLAUDE_AGENT:
            continue
        pane_id = row.get("pane_id")
        if not isinstance(pane_id, str) or not pane_id:
            continue
        status = row.get("agent_status")
        panes.append((pane_id, status is None or status == WORKING_STATUS))
    return panes


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


def pane_scope(herdr, pane_id, env, read_environ, home=None, user=None):
    """The pane's own Claude account when we can see it, else the plugin's, else ~/.claude."""
    proc_env = None
    try:
        pid = pane_claude_pid(herdr, pane_id)
    except HerdrError:
        pid = None
    if pid is not None:
        proc_env = read_environ(pid)
    return creds.resolve_scope(env=env, proc_env=proc_env, home=home, user=user)


def refresh(
    herdr,
    config,
    env=None,
    cache=None,
    fetch=api.fetch_usage,
    read_environ=procenv.read_environ,
    read_token=creds.load_token,
    home=None,
    now_ms=None,
    force=False,
    log=None,
    gate=None,
):
    """Returns how many panes now carry a usage token. Never raises for a single bad pane."""
    env = os.environ if env is None else env
    log = log or _stderr
    now_ms = now_ms or (lambda: int(time.time() * 1000))
    seq = now_ms()

    by_scope = {}
    for pane_id, working in claude_panes(herdr):
        scope = pane_scope(herdr, pane_id, env, read_environ, home=home)
        entry = by_scope.setdefault(scope.key, [scope, [], False])
        entry[1].append(pane_id)
        entry[2] = entry[2] or working

    reported = 0
    for scope, pane_ids, working in by_scope.values():
        max_age_ms = config.cache_ttl_ms if working else config.idle_ttl_ms
        value = _token_value(
            scope, config, cache, fetch, read_token, force=force, log=log, gate=gate, max_age_ms=max_age_ms
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


def _token_value(scope, config, cache, fetch, read_token, force, log, gate=None, max_age_ms=None):
    """A string to display, "" to clear the row, or None to leave whatever is there to expire."""
    token = read_token(scope)
    if not token:
        log(f"{scope.key}: no Claude credentials, clearing the row")
        return ""
    usage = None if force else (cache.get(scope.key, ttl_ms=max_age_ms) if cache else None)
    if usage is None:
        held_off = gate is not None and not force and gate.blocked(scope.key)
        if held_off:
            # Silent: a logged line per tick would be the same noise the backoff exists to stop.
            return _stale_value(scope, config, cache)
        try:
            usage = fetch(token)
        except api.UsageApiError as err:
            delay_ms = gate.penalize(scope.key) if gate is not None else 0
            log(f"{scope.key}: {err}; retrying in {delay_ms // 1000}s")
            return _stale_value(scope, config, cache)
        if gate is not None:
            gate.clear(scope.key)
        if cache:
            cache.put(scope.key, usage)
    return render.render(limits.extract(usage), config.limits, config)


def _stale_value(scope, config, cache):
    """Last known numbers while the account is rate limited. Past the cap, the row goes quiet.

    Not renewing beats clearing: the token's own TTL then retires the row on its own schedule.
    """
    entry = cache.peek(scope.key) if cache is not None else None
    if entry is None:
        return None
    usage, age_ms = entry
    if age_ms > config.max_stale_ms:
        return None
    return render.render(limits.extract(usage), config.limits, config)


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


def build_gate(cfg, env=None, now_ms=None):
    return RetryGate(
        state_dir(env) / GATE_DIR_NAME,
        base_delay_ms=cfg.backoff_base_ms,
        max_delay_ms=cfg.backoff_max_ms,
        now_ms=now_ms,
    )


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    force = "--force" in argv
    env = os.environ
    cfg = config.load_from_env(env, log=_stderr)
    herdr = Herdr(bin_path=default_bin_path(env))
    refresh_quietly(
        herdr,
        config=cfg,
        env=env,
        cache=build_cache(cfg, env),
        gate=build_gate(cfg, env),
        force=force,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
