"""Thin wrapper over the herdr CLI. HERDR_BIN_PATH keeps it portable across transports."""

import json
import os
import subprocess


DEFAULT_BIN = "herdr"


class HerdrError(Exception):
    pass


def _subprocess_runner(argv):
    proc = subprocess.run(argv, capture_output=True, text=True)
    return (proc.returncode, proc.stdout, proc.stderr)


def default_bin_path(env=None):
    env = os.environ if env is None else env
    return env.get("HERDR_BIN_PATH") or DEFAULT_BIN


class Herdr:
    def __init__(self, bin_path=None, runner=None):
        # Entry points resolve HERDR_BIN_PATH; the class itself stays free of ambient env.
        self.bin_path = bin_path or DEFAULT_BIN
        self._runner = runner or _subprocess_runner

    def _call(self, *args, expect_json=True):
        argv = [self.bin_path, *args]
        code, stdout, stderr = self._runner(argv)
        if code != 0:
            raise HerdrError(f"{' '.join(args)} exited {code}: {(stderr or stdout).strip()}")
        if not expect_json and not stdout.strip():
            # Mutating pane commands succeed silently.
            return {}
        try:
            payload = json.loads(stdout)
        except ValueError as err:
            raise HerdrError(f"{' '.join(args)} returned unparseable output: {err}") from err
        error = payload.get("error") if isinstance(payload, dict) else None
        if error:
            raise HerdrError(f"{' '.join(args)} failed: {error.get('code')}: {error.get('message')}")
        result = payload.get("result") if isinstance(payload, dict) else None
        return result if isinstance(result, dict) else {}

    def agent_list(self):
        agents = self._call("agent", "list").get("agents")
        return agents if isinstance(agents, list) else []

    def pane_process_info(self, pane_id):
        info = self._call("pane", "process-info", "--pane", pane_id).get("process_info") or {}
        processes = info.get("foreground_processes") if isinstance(info, dict) else None
        return processes if isinstance(processes, list) else []

    def report_metadata(self, pane_id, source, tokens=None, clear_tokens=None, seq=None, ttl_ms=None):
        args = ["pane", "report-metadata", pane_id, "--source", source]
        for name, value in (tokens or {}).items():
            args += ["--token", f"{name}={value}"]
        for name in clear_tokens or []:
            args += ["--clear-token", name]
        if not tokens and not clear_tokens:
            return
        if seq is not None:
            args += ["--seq", str(seq)]
        if ttl_ms is not None:
            args += ["--ttl-ms", str(ttl_ms)]
        self._call(*args, expect_json=False)
