"""Plugin config: baked-in defaults overlaid with HERDR_PLUGIN_CONFIG_DIR/config.json."""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_FILE_NAME = "config.json"
SOURCE_ID = "barsoom.claude-usage"

# The usage endpoint is one per-account budget shared with Claude Code's own /usage view, so the
# poll loop has to leave headroom. A minute of polling drains it and keeps it drained.
DEFAULT_INTERVAL_SECONDS = 300
MIN_INTERVAL_SECONDS = 60
MAX_INTERVAL_SECONDS = 3600
DEFAULT_BACKOFF_MAX_SECONDS = 1800
MIN_BACKOFF_MAX_SECONDS = 60
MAX_BACKOFF_MAX_SECONDS = 21_600
# How long a rate-limited row may keep showing the last number it knew before going quiet.
DEFAULT_MAX_STALE_SECONDS = 1800
MIN_MAX_STALE_SECONDS = 0
MAX_MAX_STALE_SECONDS = 86_400
DEFAULT_LIMITS = ["5h", "1w", "Fable"]
DEFAULT_SEPARATOR = " · "
DEFAULT_TOKEN_NAME = "claude_usage"
STYLE_TEXT = "text"
STYLE_BARS = "bars"
STYLES = (STYLE_TEXT, STYLE_BARS)
DEFAULT_STYLE = STYLE_TEXT
DEFAULT_BAR_WIDTH = 10
MIN_BAR_WIDTH = 1
MAX_BAR_WIDTH = 40

# Herdr rejects a --ttl-ms outside 1..86400000.
MAX_TTL_MS = 86_400_000
# TTL deliberately outlives the interval: a dead daemon should clear the row, not freeze it.
TTL_INTERVAL_FACTOR = 2.5


@dataclass
class Config:
    interval_seconds: int = DEFAULT_INTERVAL_SECONDS
    limits: list = field(default_factory=lambda: list(DEFAULT_LIMITS))
    separator: str = DEFAULT_SEPARATOR
    token_name: str = DEFAULT_TOKEN_NAME
    style: str = DEFAULT_STYLE
    bar_width: int = DEFAULT_BAR_WIDTH
    backoff_max_seconds: int = DEFAULT_BACKOFF_MAX_SECONDS
    max_stale_seconds: int = DEFAULT_MAX_STALE_SECONDS

    @property
    def ttl_ms(self):
        ms = int(self.interval_seconds * TTL_INTERVAL_FACTOR * 1000)
        return max(1, min(ms, MAX_TTL_MS))

    @property
    def cache_ttl_ms(self):
        return self.interval_seconds * 1000

    @property
    def backoff_base_ms(self):
        """First hold-off after a failure. One wasted request per interval is already too many."""
        return self.interval_seconds * 1000

    @property
    def backoff_max_ms(self):
        return max(self.backoff_max_seconds * 1000, self.backoff_base_ms)

    @property
    def max_stale_ms(self):
        return self.max_stale_seconds * 1000


def _clamp(value, low, high):
    return max(low, min(value, high))


def load(config_dir, log=None):
    """Read config.json if present. A bad key falls back to its default rather than failing."""
    cfg = Config()
    if config_dir is None:
        return cfg
    path = Path(config_dir) / CONFIG_FILE_NAME
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return cfg
    except (OSError, ValueError) as err:
        if log:
            log(f"ignoring unreadable {path}: {err}")
        return cfg
    if not isinstance(raw, dict):
        return cfg

    interval = raw.get("interval_seconds")
    if isinstance(interval, int) and not isinstance(interval, bool):
        cfg.interval_seconds = _clamp(interval, MIN_INTERVAL_SECONDS, MAX_INTERVAL_SECONDS)

    limits = raw.get("limits")
    if isinstance(limits, list) and all(isinstance(x, str) for x in limits):
        cfg.limits = list(limits)

    separator = raw.get("separator")
    if isinstance(separator, str):
        cfg.separator = separator

    token_name = raw.get("token_name")
    if isinstance(token_name, str) and token_name.strip():
        cfg.token_name = token_name.strip()

    style = raw.get("style")
    if style in STYLES:
        cfg.style = style

    bar_width = raw.get("bar_width")
    if isinstance(bar_width, int) and not isinstance(bar_width, bool):
        cfg.bar_width = _clamp(bar_width, MIN_BAR_WIDTH, MAX_BAR_WIDTH)

    backoff = raw.get("backoff_max_seconds")
    if isinstance(backoff, int) and not isinstance(backoff, bool):
        cfg.backoff_max_seconds = _clamp(backoff, MIN_BACKOFF_MAX_SECONDS, MAX_BACKOFF_MAX_SECONDS)

    stale = raw.get("max_stale_seconds")
    if isinstance(stale, int) and not isinstance(stale, bool):
        cfg.max_stale_seconds = _clamp(stale, MIN_MAX_STALE_SECONDS, MAX_MAX_STALE_SECONDS)

    return cfg


def load_from_env(env=None, log=None):
    env = os.environ if env is None else env
    return load(env.get("HERDR_PLUGIN_CONFIG_DIR"), log=log)
