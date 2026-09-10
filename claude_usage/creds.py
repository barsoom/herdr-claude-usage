"""Resolve which Claude config dir a pane runs under, and read its OAuth access token."""

import json
from pathlib import Path

CREDENTIALS_FILE_NAME = ".credentials.json"
CONFIG_DIR_ENV = "CLAUDE_CONFIG_DIR"
DEFAULT_CONFIG_DIR_NAME = ".claude"


def _setting(env, home):
    """One CLAUDE_CONFIG_DIR reading. `~` expands against the injected home, not the real one."""
    if not env:
        return None
    raw = env.get(CONFIG_DIR_ENV)
    if not isinstance(raw, str):
        return None
    raw = raw.strip()
    if not raw:
        return None
    if raw == "~":
        return Path(home)
    if raw.startswith("~/"):
        return Path(home) / raw[2:]
    return Path(raw)


def resolve_config_dir(env=None, proc_env=None, home=None):
    """Pane's own CLAUDE_CONFIG_DIR wins, then the plugin's, then ~/.claude."""
    home = Path.home() if home is None else Path(home)
    for candidate in (_setting(proc_env, home), _setting(env, home)):
        if candidate is not None:
            return candidate
    return home / DEFAULT_CONFIG_DIR_NAME


def read_access_token(config_dir):
    path = Path(config_dir) / CREDENTIALS_FILE_NAME
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    oauth = raw.get("claudeAiOauth") if isinstance(raw, dict) else None
    if not isinstance(oauth, dict):
        return None
    token = oauth.get("accessToken")
    if not isinstance(token, str) or not token.strip():
        return None
    return token.strip()
