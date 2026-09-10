"""The Claude usage endpoint. Same one Claude Code's own /usage view reads."""

import json
import urllib.error
import urllib.request

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
OAUTH_BETA = "oauth-2025-04-20"
DEFAULT_TIMEOUT = 10.0


class UsageApiError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


def fetch_usage(token, opener=None, timeout=DEFAULT_TIMEOUT, url=USAGE_URL):
    opener = urllib.request.urlopen if opener is None else opener
    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "anthropic-beta": OAUTH_BETA,
        },
    )
    try:
        with opener(request, timeout=timeout) as response:
            body = response.read()
    except urllib.error.HTTPError as err:
        raise UsageApiError(f"HTTP {err.code} from {url}", status=err.code) from err
    except OSError as err:
        raise UsageApiError(f"{url} unreachable: {err}") from err
    try:
        payload = json.loads(body.decode("utf-8", "replace"))
    except ValueError as err:
        raise UsageApiError(f"unparseable response from {url}: {err}") from err
    if not isinstance(payload, dict):
        raise UsageApiError(f"unexpected response shape from {url}")
    return payload
