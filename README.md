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
`/usage` view reads — authenticated with the `claudeAiOauth.accessToken` Claude Code already stored:
`<config dir>/.credentials.json` on Linux, the login keychain on macOS. Nothing is written to your
Claude config, and no credential leaves your machine except to `api.anthropic.com`.

## Requirements

- Herdr 0.9.0+
- `python3` on `PATH` (stdlib only, no pip install; developed and tested against 3.10)
- Linux or macOS

### macOS

Claude Code keeps the OAuth token in the login keychain, not in `.credentials.json`, so the plugin
reads it with `security find-generic-password` under the same service name Claude Code itself derives:
`Claude Code-credentials` for the default scope, plus `-<sha256(setting)[:8]>` when `CLAUDE_CONFIG_DIR`
(or `CLAUDE_SECURESTORAGE_CONFIG_DIR`) is set. Presence of the variable decides whether the digest is
appended, not its value, and the digest covers the raw setting rather than an expanded path — that is
what Claude Code does, and a mismatch means `security` finds nothing.

The keychain item's ACL must allow `/usr/bin/security`. Claude Code reads it the same way, so if
`/usr/login` works there it works here; if macOS prompts, allow it once.

Per-pane account detection has no `/proc` to read, so it falls back to `ps -E`. That output is
unquoted, so a `CLAUDE_CONFIG_DIR` containing spaces truncates and that pane's row clears rather than
showing another account's numbers. Unset, or unreadable, falls back to the plugin's own scope.

## Install from GitHub

```bash
herdr plugin install <owner>/herdr-claude-usage
```

Herdr clones the repo with `git`, shows a preview of the manifest and every command it will run, then
registers it under Herdr-managed plugin data. Pin a revision with `--ref <tag-or-sha>`, or skip the
prompt with `--yes` in a script. There are no `[[build]]` commands to run — the plugin is stdlib
python with no dependencies.

The repo must be public, and `herdr-plugin.toml` must sit at the repo root (it does) or in a
subdirectory you name as `<owner>/<repo>/<subdir>`.

Installing over a locally linked copy is refused, so unlink first if you linked one:

```bash
herdr plugin unlink barsoom.claude-usage
```

There is no `plugin update`; reinstall to refresh a managed checkout.

## Install locally, for development

```bash
herdr plugin link /path/to/herdr-claude-usage
```

`link` registers the working tree in place and runs no build commands, so edits take effect on the
next invocation. `herdr plugin unlink barsoom.claude-usage` unregisters it and leaves the files alone.

## Wire up the sidebar

Then add the token to your sidebar rows in `~/.config/herdr/config.toml`:

```toml
[ui.sidebar.agents.rows_by_agent]
claude = [["state_icon", "machine", "workspace", "tab"], ["terminal_title_stripped"], ["agent", "$claude_usage"]]
```

```bash
herdr server reload-config
```

Rows only appear on panes Herdr detects as `claude`.

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

## Rate limits

`GET /api/oauth/usage` is one per-account budget, and Claude Code's own `/usage` view spends from the
same one. Poll it hard enough and both break: the plugin's row blanks on `HTTP 429`, and `/usage`
starts reporting its per-model breakdown as unavailable. The defaults exist to stay well clear of
that — a 5 minute interval, and three things the plugin does when a request fails anyway:

| | |
| --- | --- |
| backs off | The scope waits one interval, then doubles per failure up to `backoff_max_seconds`. Rejected requests still cost budget, so retrying at the poll interval is what keeps an account locked out. |
| serves stale | The row keeps its last known numbers for `max_stale_seconds` instead of blanking, then stops renewing and lets the TTL retire it. |
| stays put | The backoff is on disk, per account, so the event hook and the action inherit it instead of each spending a fresh request. |

An account whose panes are all idle is polled every `idle_interval_seconds` instead — an idle agent
spends no limit, so there is nothing to re-read. One pane going `working` puts the whole account back
on `interval_seconds`. A row Herdr reports without an `agent_status` counts as working.

The `refresh` action ignores the backoff: it is user-initiated, and one deliberate request is the
point of it. Lower `interval_seconds` at your own risk — it is also the backoff's first step.

## Config

`$(herdr plugin config-dir barsoom.claude-usage)/config.json`. Every key is optional.

```json
{
  "interval_seconds": 300,
  "idle_interval_seconds": 900,
  "limits": ["5h", "1w", "Fable"],
  "separator": " · ",
  "token_name": "claude_usage",
  "style": "text",
  "bar_width": 10,
  "backoff_max_seconds": 1800,
  "max_stale_seconds": 1800
}
```

- `interval_seconds` — poll interval, clamped to 60..3600. Also the first backoff step.
- `idle_interval_seconds` — poll interval for an account with no working pane, clamped to 60..86400.
  Never faster than `interval_seconds`.
- `backoff_max_seconds` — ceiling on the doubling backoff after a failed request, clamped to
  60..21600. Never shorter than one interval.
- `max_stale_seconds` — how long a rate-limited row keeps showing its last known numbers, clamped to
  0..86400. `0` blanks the row the moment a request fails.
- `limits` — whitelist *and* display order. `5h` is the session window, `1w` the all-model weekly
  window; any other entry matches a model-scoped weekly window by its display name, so plans with
  per-model caps can ask for `"Opus"` or `"Sonnet"`. Windows your account does not have are dropped
  from the string.
- `token_name` — rename if you want a different `$token` in your row config.
- `style` — `"text"` (default) or `"bars"`. See below.
- `bar_width` — bar length in characters, clamped to 1..40. `"bars"` only.

Herdr caps a token value at 80 characters. The text renderer drops whole trailing segments to fit
rather than truncating mid-word.

### `"style": "bars"`

80 characters is Herdr's cap on a token *value*, not the visible width of the sidebar's agent-row
column — that is nearer 22 characters at regular width, 32 at Herdr's widest, and Herdr exposes it
to plugins nowhere. So the text form overflows and gets truncated mid-word before the drop logic
ever fires. `"bars"` stacks the same numbers into one glyph instead:

```
  claude   ██🬹🬓      ▏
```

Three limits, one per dot-row of a Unicode sextant (2 dot-columns × 3 dot-rows per character), in
`limits` order: first on top, second in the middle, third on the bottom. Limits your account does
not have are skipped rather than left blank, and anything past the third present limit is dropped —
there are only three rows. Row identity is position, not a label; that is the whole point of the
format.

`bar_width` characters is `bar_width * 2` steps of resolution — 20 steps, one dot per 5%, at the
default 10. The trailing `▏` is a fixed marker for the 100% edge, one per token rather than per row:
Herdr's token schema is a plain string with no color, so the unfilled remainder cannot be darkened
instead.

Needs a font with the Legacy Computing block (`U+1FB00`). Developed against Ghostty with
Inconsolata plus Ghostty's built-in Symbols Nerd Font.

## When Herdr hangs on start

It should not any more, but the shape of that failure is worth knowing. Herdr records a plugin
command's completion when its output closes, so a detached loop that keeps the inherited
stdout/stderr open blocks startup. The daemon therefore redirects both to `daemon.log` in its state
dir the moment it detaches. `plugin.disable` is a socket call and needs a running server, so if a
plugin ever wedges startup, the server-less escape hatch is the registry:

```bash
mv ~/.config/herdr/plugins.json ~/.config/herdr/plugins.json.off   # then start Herdr and fix
```

## When a row is empty

- **No credentials in that config dir** — the token is cleared on purpose. An empty row beats a stale
  number.
- **API or network failure** — the previous value is left alone and expires on its own TTL.
- **Anything else** — the plugin logs to stderr and Herdr keeps it:

```bash
herdr plugin log list --plugin barsoom.claude-usage   # hooks and actions; also names the daemon log
herdr pane get <pane_id>                              # `tokens` shows what the sidebar is reading
```

The poll loop logs to `daemon.log` beside its pidfile in the plugin's state dir, since its own
stdout and stderr have to be released for Herdr to start. The startup hook prints that path before
detaching, so `plugin log list` tells you where to look.

## Development

```bash
python3 -m unittest discover -s tests -t .
```

190 tests, no network and no live Herdr server: every outward effect — the `herdr` CLI, the HTTP
opener, `/proc`, the clock — is injected.

```
herdr-plugin.toml
claude_usage/
  config.py    defaults + config.json overlay
  creds.py     account scope resolution, token from file or keychain
  procenv.py   another process's environment (/proc on Linux, ps -E on macOS)
  api.py       the usage endpoint
  limits.py    usage JSON -> {label: percent}
  render.py    {label: percent} -> token value, text or sextant bars
  herdr.py     herdr CLI wrapper
  gate.py      per-scope retry backoff, on disk so every entry point shares it
  refresh.py   one pass over every claude pane
  daemon.py    poll loop, pidfile takeover, orphan guard
```

## Publishing

Herdr's marketplace is an automatic index of public GitHub repos carrying the topic `herdr-plugin`
whose `herdr-plugin.toml` parses. Add the topic and the repo shows up within about 30 minutes; no
submission step:

```bash
gh repo edit <owner>/herdr-claude-usage --add-topic herdr-plugin
```

Design notes: `docs/superpowers/specs/2026-09-10-herdr-claude-usage-design.md`.
