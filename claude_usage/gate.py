"""Per-scope retry gate. Keeps a rate-limited account from being hammered back into its limit.

State lives on disk because the poll loop is not the only caller: the event hook and the action are
their own processes, and in-memory backoff would leak a request per invocation.
"""

import hashlib
import json
import time
from pathlib import Path


class RetryGate:
    def __init__(self, directory, base_delay_ms, max_delay_ms, now_ms=None):
        self.directory = Path(directory)
        self.base_delay_ms = max(1, int(base_delay_ms))
        self.max_delay_ms = max(self.base_delay_ms, int(max_delay_ms))
        self._now_ms = now_ms or (lambda: int(time.time() * 1000))

    def _path(self, key):
        digest = hashlib.sha1(str(key).encode("utf-8")).hexdigest()
        return self.directory / f"{digest}.json"

    def _read(self, key):
        try:
            raw = json.loads(self._path(key).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return raw if isinstance(raw, dict) else None

    def _number(self, state, field):
        value = state.get(field) if state else None
        return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None

    def blocked(self, key):
        """True while the last failure's delay is still running. Corrupt state reads as open."""
        until = self._number(self._read(key), "next_attempt_ms")
        return until is not None and self._now_ms() < until

    def penalize(self, key):
        """Double the delay, or start at the base. Returns the delay now in force."""
        previous = self._number(self._read(key), "delay_ms")
        delay = self.base_delay_ms if previous is None else previous * 2
        delay = max(self.base_delay_ms, min(int(delay), self.max_delay_ms))
        payload = json.dumps({"delay_ms": delay, "next_attempt_ms": self._now_ms() + delay})
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            path = self._path(key)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(payload, encoding="utf-8")
            tmp.replace(path)
        except OSError:
            pass
        return delay

    def clear(self, key):
        try:
            self._path(key).unlink()
        except OSError:
            pass
