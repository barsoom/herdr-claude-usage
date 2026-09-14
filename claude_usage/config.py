"""Plugin config: baked-in defaults overlaid with HERDR_PLUGIN_CONFIG_DIR/config.json."""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_FILE_NAME = "config.json"
SOURCE_ID = "barsoom.claude-usage"

DEFAULT_INTERVAL_SECONDS = 60
MIN_INTERVAL_SECONDS = 15
MAX_INTERVAL_SECONDS = 3600
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

    @property
    def ttl_ms(self):
        ms = int(self.interval_seconds * TTL_INTERVAL_FACTOR * 1000)
        return max(1, min(ms, MAX_TTL_MS))

    @property
    def cache_ttl_ms(self):
        return self.interval_seconds * 1000


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

    return cfg


def load_from_env(env=None, log=None):
    env = os.environ if env is None else env
    return load(env.get("HERDR_PLUGIN_CONFIG_DIR"), log=log)
