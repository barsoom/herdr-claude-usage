# herdr-claude-usage

Herdr plugin. Puts Claude limit usage on `claude` agent rows in the Herdr sidebar, per account.

```
● local  boardingschool  main
  Boarding school implementation
  claude   5h 19% · 1w 37% · Fable 36%
```

Percent **used**, not left. Each pane reports the account it actually runs under: the plugin reads
`CLAUDE_CONFIG_DIR` out of that pane's own `claude` process, so two panes on two accounts show two
different numbers. Unset falls back to `~/.claude`.

Data comes from `GET https://api.anthropic.com/api/oauth/usage` — the same endpoint Claude Code's own
`/usage` view reads — authenticated with the `claudeAiOauth.accessToken` already in that config dir's
`.credentials.json`. Nothing is written to your Claude config, and no credential leaves your machine
except to `api.anthropic.com`.

## Requirements

- Herdr 0.9.0+
- `python3` on `PATH` (stdlib only, no pip install; developed and tested against 3.10)
- Linux. Two things are Linux-shaped: per-pane account detection reads `/proc/<pid>/environ`, and the
  token is read from `.credentials.json`, which is where Claude Code keeps it on Linux. On macOS it
  lives in the Keychain instead, so the manifest declares `platforms = ["linux"]` rather than
  shipping a macOS claim that would render empty rows.

## Install

```bash
herdr plugin link /path/to/herdr-claude-usage
```

Then add the token to your sidebar rows in `~/.config/herdr/config.toml`:

```toml
[ui.sidebar.agents.rows_by_agent]
claude = [["state_icon", "machine", "workspace", "tab"], ["terminal_title_stripped"], ["agent", "$claude_usage"]]
```

```bash
herdr server reload-config
```

The poll loop starts from the plugin's `[[startup]]` hook, which fires when a Herdr server starts or
takes over — not when a plugin is linked. To fill the rows in the session you already have open:

```bash
herdr plugin action invoke barsoom.claude-usage.refresh
```

Optional keybinding, in `config.toml`:

```toml
[[keys.command]]
key = "prefix+u"
type = "plugin_action"
command = "barsoom.claude-usage.refresh"
description = "refresh Claude usage"
```

## How it stays fresh

| surface | what it does |
| --- | --- |
| `[[startup]]` | Detached poll loop, every `interval_seconds`. SIGTERMs its predecessor, so a live handoff swaps the loop instead of duplicating it, and it exits once `HERDR_SOCKET_PATH` disappears. |
| `[[events]] pane.agent_detected` | Fills a newly started agent's row without waiting out an interval. Served from the cache the loop already populated. |
| `[[actions]] refresh` | Manual, cache-bypassing pass. Bindable to a key. |

Reported tokens carry a TTL of 2.5× the poll interval. That is deliberate: if the loop dies, the row
**disappears** rather than showing numbers that quietly went stale.

## Config

`$(herdr plugin config-dir barsoom.claude-usage)/config.json`. Every key is optional.

```json
{
  "interval_seconds": 60,
  "limits": ["5h", "1w", "Fable"],
  "separator": " · ",
  "token_name": "claude_usage"
}
```

- `interval_seconds` — poll interval, clamped to 15..3600.
- `limits` — whitelist *and* display order. `5h` is the session window, `1w` the all-model weekly
  window; any other entry matches a model-scoped weekly window by its display name, so plans with
  per-model caps can ask for `"Opus"` or `"Sonnet"`. Windows your account does not have are dropped
  from the string.
- `token_name` — rename if you want a different `$token` in your row config.

Herdr caps a token value at 80 characters. The renderer drops whole trailing segments to fit rather
than truncating mid-word.

## When a row is empty

- **No credentials in that config dir** — the token is cleared on purpose. An empty row beats a stale
  number.
- **API or network failure** — the previous value is left alone and expires on its own TTL.
- **Anything else** — the plugin logs to stderr and Herdr keeps it:

```bash
herdr plugin log list --plugin barsoom.claude-usage
herdr pane get <pane_id>   # `tokens` shows what the sidebar is reading
```

## Development

```bash
python3 -m unittest discover -s tests -t .
```

93 tests, no network and no live Herdr server: every outward effect — the `herdr` CLI, the HTTP
opener, `/proc`, the clock — is injected.

```
herdr-plugin.toml
claude_usage/
  config.py    defaults + config.json overlay
  creds.py     config-dir resolution, access token
  procenv.py   /proc/<pid>/environ
  api.py       the usage endpoint
  limits.py    usage JSON -> {label: percent}
  render.py    {label: percent} -> token value
  herdr.py     herdr CLI wrapper
  refresh.py   one pass over every claude pane
  daemon.py    poll loop, pidfile takeover, orphan guard
```

Design notes: `docs/superpowers/specs/2026-09-10-herdr-claude-usage-design.md`.
