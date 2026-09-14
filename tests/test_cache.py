import tempfile
import unittest
from pathlib import Path

from claude_usage.cache import UsageCache


class Cache(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "cache"
        self.addCleanup(self.tmp.cleanup)
        self.now = 1_000_000

    def cache(self, ttl_ms=60000):
        return UsageCache(self.dir, ttl_ms=ttl_ms, now_ms=lambda: self.now)

    def test_returns_a_fresh_entry(self):
        c = self.cache()
        c.put("/home/x/.claude", {"limits": [1]})
        self.assertEqual(self.cache().get("/home/x/.claude"), {"limits": [1]})

    def test_expires_a_stale_entry(self):
        self.cache().put("k", {"a": 1})
        self.now += 60001
        self.assertIsNone(self.cache().get("k"))

    def test_unknown_key_yields_none(self):
        self.assertIsNone(self.cache().get("never-written"))

    def test_keys_do_not_collide_across_config_dirs(self):
        c = self.cache()
        c.put("/a", {"which": "a"})
        c.put("/b", {"which": "b"})
        self.assertEqual(c.get("/a"), {"which": "a"})
        self.assertEqual(c.get("/b"), {"which": "b"})

    def test_path_separators_do_not_escape_the_cache_directory(self):
        c = self.cache()
        c.put("/../../etc", {"x": 1})
        written = list(self.dir.iterdir())
        self.assertEqual(len(written), 1)
        self.assertEqual(written[0].parent, self.dir)

    def test_corrupt_entry_is_treated_as_a_miss(self):
        c = self.cache()
        c.put("k", {"a": 1})
        next(self.dir.iterdir()).write_text("{ broken", encoding="utf-8")
        self.assertIsNone(self.cache().get("k"))

    def test_unwritable_cache_directory_is_survivable(self):
        c = UsageCache(Path("/proc/nonexistent/cache"), ttl_ms=1000, now_ms=lambda: self.now)
        c.put("k", {"a": 1})
        self.assertIsNone(c.get("k"))

    def test_peek_returns_an_expired_entry_with_its_age(self):
        self.cache().put("k", {"a": 1})
        self.now += 90_000
        self.assertEqual(self.cache().peek("k"), ({"a": 1}, 90_000))

    def test_peek_of_an_unknown_key_yields_none(self):
        self.assertIsNone(self.cache().peek("never-written"))

    def test_peek_of_a_corrupt_entry_yields_none(self):
        self.cache().put("k", {"a": 1})
        next(self.dir.iterdir()).write_text("{ broken", encoding="utf-8")
        self.assertIsNone(self.cache().peek("k"))

    def test_get_honours_a_tighter_ttl_than_the_cache_was_built_with(self):
        self.cache().put("k", {"a": 1})
        self.now += 30_000
        self.assertEqual(self.cache().get("k"), {"a": 1})
        self.assertIsNone(self.cache().get("k", ttl_ms=20_000))
