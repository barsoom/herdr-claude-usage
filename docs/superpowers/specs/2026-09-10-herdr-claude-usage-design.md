# herdr-claude-usage — design

Herdr plugin. Shows Claude limit usage (5h / weekly / Fable) on `claude` agent rows in the
Herdr sidebar, scoped to whichever Claude account each pane actually runs under.

## Surface

Herdr panes carry display-only metadata tokens (`herdr pane report-metadata --token NAME=VALUE`).
Pane tokens render in sidebar agent rows as `$name`. The plugin owns one token, `claude_usage`:

```
claude   5h 14% · 1w 37% · Fable 36%
```

Percent **used**, matching every other Claude usage UI. Absent limits drop out of the string, so
plans without a Fable window show two segments. Herdr caps token values at 80 chars; the renderer
drops trailing segments before it lets Herdr truncate mid-word.

The user wires the token into their own `config.toml` once:

```toml
[ui.sidebar.agents.rows_by_agent]
claude = [["state_icon", "machine", "workspace", "tab"], ["terminal_title_stripped"], ["agent", "$claude_usage"]]
```

## Modules

| module | purpose |
| --- | --- |
| `claude_usage/config.py` | defaults + `HERDR_PLUGIN_CONFIG_DIR/config.json` overlay |
| `claude_usage/creds.py` | resolve config dir per pane, read `claudeAiOauth.accessToken` |
| `claude_usage/procenv.py` | `/proc/<pid>/environ` reader (Linux only) |
| `claude_usage/api.py` | `GET api.anthropic.com/api/oauth/usage` |
| `claude_usage/limits.py` | usage JSON -> `{label: percent}` |
| `claude_usage/render.py` | `{label: percent}` -> token string |
| `claude_usage/herdr.py` | `herdr` CLI wrapper (agent list, pane process-info, pane report-metadata) |
| `claude_usage/refresh.py` | one-shot pass over every claude pane |
| `claude_usage/daemon.py` | poll loop, pidfile takeover, orphan guard |

Stdlib only (`urllib`, `json`, `subprocess`). Manifest commands are `["python3", "-m", "claude_usage.X"]`;
Herdr runs plugin commands with the plugin root as cwd, so there is no install step.

Every module that touches the outside world takes its effect as an injected callable — the `herdr`
runner, the HTTP opener, the environ reader, the clock. Tests use fakes; nothing in the suite
touches the network or a live Herdr server.

## One refresh pass

1. `herdr agent list` -> keep `agent == "claude"` -> pane ids.
2. Per pane: `herdr pane process-info` -> the foreground process named `claude` -> read
   `/proc/<pid>/environ` -> `CLAUDE_CONFIG_DIR`. Falls back to the plugin's own environment, then
   `~/.claude`.

   Linux only, declared as such in the manifest. Both halves of step 2 and step 4 are Linux-shaped:
   `/proc/<pid>/environ` does not exist elsewhere, and macOS Claude Code keeps the token in the
   Keychain rather than in `.credentials.json`. Supporting macOS means a `security find-generic-password`
   fallback in `creds.py`; until that exists the manifest does not claim the platform.
3. Group panes by resolved config dir. One HTTP call per distinct dir per tick, cached under
   `HERDR_PLUGIN_STATE_DIR` for the poll interval.
4. `.credentials.json` -> `claudeAiOauth.accessToken`. Response `limits[]`: `session` -> `5h`,
   `weekly_all` -> `1w`, `weekly_scoped` -> `scope.model.display_name`. When `limits[]` is absent,
   fall back to the legacy top-level `five_hour` / `seven_day` / `seven_day_overage_included`
   `utilization` fields.
5. `herdr pane report-metadata <pane> --source barsoom.claude-usage --token claude_usage=... --seq <ts> --ttl-ms <2.5x interval>`.

TTL above the poll interval is deliberate: a dead daemon makes the row vanish instead of showing
stale numbers.

## Freshness

Plugins get no timer surface, so:

- `[[startup]]` -> `daemon.py`. SIGTERMs the pid in `state/daemon.pid` (this is what makes live
  handoff replace rather than duplicate the loop), double-forks, parent exits so Herdr sees the
  hook complete. The child polls every `interval_seconds` and exits once `HERDR_SOCKET_PATH`
  disappears, so no loop outlives its server.
- `[[events]] on = "pane.agent_detected"` -> `refresh.py`, so a newly started agent gets its row
  without waiting out a poll interval.
- `[[actions]] id = "refresh"` -> `refresh.py`, bindable to a key.

## Errors

A refresh pass never raises. Credentials absent -> `--clear-token`, so the row shows nothing rather
than a lie. HTTP or parse failure -> leave the token alone and let its TTL expire it. Diagnostics go
to stderr, which Herdr records: `herdr plugin log list --plugin barsoom.claude-usage`.

## Config

`$(herdr plugin config-dir barsoom.claude-usage)/config.json`, every key optional:

```json
{ "interval_seconds": 60, "limits": ["5h", "1w", "Fable"], "separator": " · ", "token_name": "claude_usage" }
```

`interval_seconds` clamps to 15..3600. JSON rather than TOML because the target python is 3.10,
which has no `tomllib`.

## Tests

`python3 -m unittest discover -s tests`. Limit extraction including the legacy fallback and an
absent Fable window, render truncation at the 80-char cap, config-dir precedence, credential
parsing, `agent list` filtering, process-info -> pid, pidfile takeover, and a full refresh pass
against a fake runner asserting the exact `report-metadata` argv.
