import json
import tempfile
import unittest
from pathlib import Path

from claude_usage import config


class Load(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def write(self, payload):
        (self.dir / "config.json").write_text(json.dumps(payload), encoding="utf-8")

    def test_defaults_when_no_file_exists(self):
        cfg = config.load(self.dir)
        self.assertEqual(cfg.interval_seconds, 60)
        self.assertEqual(cfg.limits, ["5h", "1w", "Fable"])
        self.assertEqual(cfg.token_name, "claude_usage")

    def test_defaults_when_config_dir_is_none(self):
        self.assertEqual(config.load(None).interval_seconds, 60)

    def test_overlays_provided_keys_only(self):
        self.write({"interval_seconds": 120})
        cfg = config.load(self.dir)
        self.assertEqual(cfg.interval_seconds, 120)
        self.assertEqual(cfg.limits, ["5h", "1w", "Fable"])

    def test_clamps_interval_to_bounds(self):
        self.write({"interval_seconds": 1})
        self.assertEqual(config.load(self.dir).interval_seconds, config.MIN_INTERVAL_SECONDS)
        self.write({"interval_seconds": 99999})
        self.assertEqual(config.load(self.dir).interval_seconds, config.MAX_INTERVAL_SECONDS)

    def test_ignores_wrongly_typed_values(self):
        self.write({"interval_seconds": "soon", "limits": "5h", "separator": 3})
        cfg = config.load(self.dir)
        self.assertEqual(cfg.interval_seconds, 60)
        self.assertEqual(cfg.limits, ["5h", "1w", "Fable"])
        self.assertEqual(cfg.separator, " · ")

    def test_ignores_unparseable_file(self):
        (self.dir / "config.json").write_text("{ not json", encoding="utf-8")
        self.assertEqual(config.load(self.dir).interval_seconds, 60)

    def test_ttl_outlives_the_poll_interval_so_a_dead_daemon_clears_the_row(self):
        cfg = config.load(self.dir)
        self.assertGreater(cfg.ttl_ms, cfg.interval_seconds * 1000)
        self.assertLessEqual(cfg.ttl_ms, config.MAX_TTL_MS)

    def test_ttl_stays_within_herdrs_accepted_range_at_max_interval(self):
        self.write({"interval_seconds": config.MAX_INTERVAL_SECONDS})
        cfg = config.load(self.dir)
        self.assertLessEqual(cfg.ttl_ms, config.MAX_TTL_MS)
        self.assertGreaterEqual(cfg.ttl_ms, 1)

    def test_limits_entries_must_be_strings(self):
        self.write({"limits": ["5h", 7]})
        self.assertEqual(config.load(self.dir).limits, ["5h", "1w", "Fable"])


class Style(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def write(self, payload):
        (self.dir / "config.json").write_text(json.dumps(payload), encoding="utf-8")

    def test_defaults_to_text_style(self):
        cfg = config.load(self.dir)
        self.assertEqual(cfg.style, config.STYLE_TEXT)
        self.assertEqual(cfg.bar_width, config.DEFAULT_BAR_WIDTH)

    def test_accepts_the_bars_style(self):
        self.write({"style": "bars"})
        self.assertEqual(config.load(self.dir).style, config.STYLE_BARS)

    def test_unknown_style_falls_back_to_text(self):
        self.write({"style": "sparkline"})
        self.assertEqual(config.load(self.dir).style, config.STYLE_TEXT)

    def test_wrongly_typed_style_falls_back_to_text(self):
        self.write({"style": 2})
        self.assertEqual(config.load(self.dir).style, config.STYLE_TEXT)

    def test_overrides_bar_width(self):
        self.write({"bar_width": 16})
        self.assertEqual(config.load(self.dir).bar_width, 16)

    def test_clamps_bar_width_to_bounds(self):
        self.write({"bar_width": 0})
        self.assertEqual(config.load(self.dir).bar_width, config.MIN_BAR_WIDTH)
        self.write({"bar_width": 999})
        self.assertEqual(config.load(self.dir).bar_width, config.MAX_BAR_WIDTH)

    def test_wrongly_typed_bar_width_falls_back_to_default(self):
        self.write({"bar_width": True})
        self.assertEqual(config.load(self.dir).bar_width, config.DEFAULT_BAR_WIDTH)
        self.write({"bar_width": "wide"})
        self.assertEqual(config.load(self.dir).bar_width, config.DEFAULT_BAR_WIDTH)
