"""Short-lived on-disk usage cache, so the event hook and action reuse the daemon's fetch."""

import hashlib
import json
import time
from pathlib import Path


class UsageCache:
    def __init__(self, directory, ttl_ms, now_ms=None):
        self.directory = Path(directory)
        self.ttl_ms = ttl_ms
        self._now_ms = now_ms or (lambda: int(time.time() * 1000))

    def _path(self, key):
        digest = hashlib.sha1(str(key).encode("utf-8")).hexdigest()
        return self.directory / f"{digest}.json"

    def peek(self, key):
        """(usage, age_ms) whatever the age, or None. Lets a caller serve a stale value knowingly."""
        try:
            raw = json.loads(self._path(key).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        fetched = raw.get("fetched_ms") if isinstance(raw, dict) else None
        if not isinstance(fetched, (int, float)) or isinstance(fetched, bool):
            return None
        usage = raw.get("usage") if isinstance(raw, dict) else None
        if not isinstance(usage, dict):
            return None
        return (usage, self._now_ms() - fetched)

    def get(self, key, ttl_ms=None):
        """Fresh value only. `ttl_ms` overrides the built-in one, for a slower idle cadence."""
        entry = self.peek(key)
        if entry is None:
            return None
        usage, age_ms = entry
        limit = self.ttl_ms if ttl_ms is None else ttl_ms
        return None if age_ms > limit else usage

    def put(self, key, usage):
        payload = json.dumps({"fetched_ms": self._now_ms(), "usage": usage})
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            path = self._path(key)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(payload, encoding="utf-8")
            tmp.replace(path)
        except OSError:
            pass
