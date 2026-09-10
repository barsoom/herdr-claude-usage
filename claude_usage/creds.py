"""Which Claude account a pane runs under, and how to read that account's OAuth token.

Linux keeps the token in `<config dir>/.credentials.json`. macOS keeps it in the login keychain,
under a service name derived from the config dir — so the scope has to be resolved before the token
can be read at all.
"""

import getpass
import hashlib
import json
import re
import subprocess
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

CREDENTIALS_FILE_NAME = ".credentials.json"
CONFIG_DIR_ENV = "CLAUDE_CONFIG_DIR"
SECURESTORAGE_ENV = "CLAUDE_SECURESTORAGE_CONFIG_DIR"
DEFAULT_CONFIG_DIR_NAME = ".claude"

KEYCHAIN_SERVICE_BASE = "Claude Code-credentials"
DIGEST_LENGTH = 8
FALLBACK_ACCOUNT = "claude-code-user"
_USABLE_ACCOUNT = re.compile(r"^[a-zA-Z0-9._-]+$")
SECURITY_TIMEOUT_S = 10.0


@dataclass(frozen=True)
class Scope:
    """One Claude account, as seen from one pane."""

    config_dir: Path
    keychain_service: str
    keychain_account: str

    @property
    def key(self):
        return str(self.config_dir)


def _run(argv, timeout=SECURITY_TIMEOUT_S):
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    return (proc.returncode, proc.stdout, proc.stderr)


def _setting(env, home, name=CONFIG_DIR_ENV):
    """One env reading. `~` expands against the injected home, not the real one."""
    if not env:
        return None
    raw = env.get(name)
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


def _raw(env, name):
    if not env:
        return None
    raw = env.get(name)
    return raw.strip() if isinstance(raw, str) else None


def resolve_config_dir(env=None, proc_env=None, home=None):
    """Pane's own CLAUDE_CONFIG_DIR wins, then the plugin's, then ~/.claude."""
    home = Path.home() if home is None else Path(home)
    for candidate in (_setting(proc_env, home), _setting(env, home)):
        if candidate is not None:
            return candidate
    return home / DEFAULT_CONFIG_DIR_NAME


def scope_digest(raw_setting):
    normalized = unicodedata.normalize("NFC", raw_setting)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:DIGEST_LENGTH]


def keychain_service(env=None, proc_env=None, home=None):
    """Reproduce Claude Code's securestorage service name, or macOS finds nothing.

    Presence of the variable decides whether the name carries a digest, not its value: an explicit
    CLAUDE_CONFIG_DIR equal to the default still gets one. The digest covers the raw setting, since
    node never expands `~`.
    """
    for source in (proc_env, env):
        if source is None or SECURESTORAGE_ENV not in source:
            continue
        secure = source.get(SECURESTORAGE_ENV)
        secure = secure.strip() if isinstance(secure, str) else ""
        if not secure:
            return KEYCHAIN_SERVICE_BASE
        return f"{KEYCHAIN_SERVICE_BASE}-{scope_digest(secure)}"

    for source in (proc_env, env):
        raw = _raw(source, CONFIG_DIR_ENV)
        if raw:
            return f"{KEYCHAIN_SERVICE_BASE}-{scope_digest(raw)}"
    return KEYCHAIN_SERVICE_BASE


def keychain_account(env=None, proc_env=None, user=None):
    for source in (proc_env, env):
        name = _raw(source, "USER")
        if name:
            return name if _USABLE_ACCOUNT.match(name) else FALLBACK_ACCOUNT
    if user is None:
        try:
            user = getpass.getuser()
        except Exception:
            return FALLBACK_ACCOUNT
    return user if _USABLE_ACCOUNT.match(user) else FALLBACK_ACCOUNT


def resolve_scope(env=None, proc_env=None, home=None, user=None):
    home = Path.home() if home is None else Path(home)
    return Scope(
        config_dir=resolve_config_dir(env=env, proc_env=proc_env, home=home),
        keychain_service=keychain_service(env=env, proc_env=proc_env, home=home),
        keychain_account=keychain_account(env=env, proc_env=proc_env, user=user),
    )


def _token_from_blob(text):
    try:
        raw = json.loads(text)
    except (TypeError, ValueError):
        return None
    oauth = raw.get("claudeAiOauth") if isinstance(raw, dict) else None
    if not isinstance(oauth, dict):
        return None
    token = oauth.get("accessToken")
    if not isinstance(token, str) or not token.strip():
        return None
    return token.strip()


def read_access_token(config_dir):
    """The Linux path, and the macOS path whenever keychain storage is turned off."""
    try:
        text = (Path(config_dir) / CREDENTIALS_FILE_NAME).read_text(encoding="utf-8")
    except OSError:
        return None
    return _token_from_blob(text)


def read_keychain_token(service, account, runner=None):
    """`security` prints the same credentials blob the file would hold."""
    runner = runner or _run
    argv = ["security", "find-generic-password", "-a", account, "-w", "-s", service]
    try:
        code, stdout, _ = runner(argv)
    except (OSError, subprocess.SubprocessError):
        return None
    if code != 0:
        return None
    return _token_from_blob(stdout)


def load_token(scope, platform=None, file_reader=read_access_token, keychain_reader=None):
    platform = sys.platform if platform is None else platform
    token = file_reader(scope.config_dir)
    if token or not platform.startswith("darwin"):
        return token
    keychain_reader = keychain_reader or read_keychain_token
    return keychain_reader(scope.keychain_service, scope.keychain_account)
