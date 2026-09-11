# Compact sextant-bar display — design

Today's `claude_usage` token is text: `5h 19% · 1w 37% · Fable 36%`. `render.py` already drops
whole trailing segments past `MAX_TOKEN_LEN` (80), but 80 chars is Herdr's own hard cap on a token
value, not the visible column width. In practice the sidebar's agent-row column is far narrower —
this user measured ~22 chars at regular width, ~32 at Herdr's max sidebar width — so even 2-3
segments overflow and Herdr truncates the token mid-word before our drop-logic ever triggers.

Herdr does not expose sidebar/column width to plugins: not in `config.toml` (checked — no
`width` key under `[ui.sidebar]` or anywhere else), not in `herdr api snapshot` (pane `rect`s are
terminal-content geometry, not sidebar chrome), not in `herdr api schema`. So there is no way to
auto-fit; the user sets a width budget by hand.

## Approach: opt-in `style: "bars"`

Add a second render style, `"bars"`, alongside the existing `"text"` (which stays the default —
this plugin may have other adopters with wider sidebars, so the working format shouldn't change
under them).

### Visual encoding

Each limit becomes one row of a single stacked bar glyph built from Unicode's Legacy Computing
Sextant block (`U+1FB00`, 2-column × 3-row dot grid per character, standard bit layout: bits 0,1 =
top row; 2,3 = middle row; 4,5 = bottom row; `0` → space, `0b111111` → `█`). Verified against the
actual rendering in the user's terminal (Ghostty, Inconsolata + Ghostty's built-in Symbols Nerd
Font) — braille (`U+2800`) did not render as dots/bars there, sextants did.

Row assignment: `config.limits` order, among labels actually present in the data, first ≤3 kept —
absent labels are skipped (not reserved as a blank row), matching today's text-mode behavior where
a missing label just doesn't appear. With the default `limits = ["5h", "1w", "Fable"]` that puts 5h
on top, 1w in the middle, Fable/model-scoped on the bottom, when present.

2 dot-columns of horizontal resolution per character. `bar_width=10` (default) → 20 steps, ~5%
resolution, in 10 characters — comfortably inside a 22-char sidebar.

No per-row label glyph: row position already encodes identity, and a single leading glyph can't
label three different rows anyway. The 5h/1w/Fable-or-model row order is documented here and in
the README, not shown per-render.

Trailing boundary marker: `herdr api schema --json` shows pane `tokens` are typed as plain
`string` (no color/style substructure), so there's no way to darken the unfilled remainder to mark
the 100% edge. Instead, append one fixed `▏` (U+258F, LEFT ONE EIGHTH BLOCK — the thinnest glyph in
the same eighth-block family already confirmed to render for this user) right after the
`bar_width` span, shared across all three stacked rows. At 100% fill the bar's trailing `█` sits
flush against it; at any lower fill it marks where the meter ends regardless of how much trailing
space precedes it. Adds exactly 1 character to the token, not per-row.

### Config additions (`config.py`)

- `style`: `"text"` (default, unchanged) | `"bars"`
- `bar_width`: int, default `10`, clamped `1..40` (same clamp pattern as `interval_seconds`)

`limits` and `token_name` keep their current meaning in both styles. `separator` keeps its current
meaning for `"text"` and is unused for `"bars"`.

### Render (`render.py`)

- Current `render()` renamed to `render_text()` — behavior and tests unchanged.
- New `render_bars(percents, order, bar_width)`:
  - Clamp each percent to `0..100` (defends against an overage window reporting >100).
  - Take the first ≤3 labels from `order` that are present in `percents`.
  - Build the sextant string per the encoding above, then append the `▏` marker.
- New `render(percents, order, config)` dispatches to `render_text`/`render_bars` by
  `config.style`. `refresh.py:122` calls this instead of `render.render(percents, order,
  separator=...)` directly.

### Edge cases

- 0 or 1 present limit → 1-2 rows lit, the rest blank string-wise (falls out of the same code, no
  special case).
- >3 present labels (e.g. more than one model-scoped window at once) → first 3 in configured
  order, rest silently dropped — same "drop rather than truncate mid-word" philosophy as today,
  just capped structurally instead of by width.
- Percent >100 → clamped to 100 before glyph math.

### Docs & tests

- README: `style`/`bar_width` config rows, a sextant example, the 3-row cap and row-order note.
- Tests: sextant glyph math, `render_bars` row assignment (missing labels, >3 labels, clamping,
  the trailing marker at 0%/partial/100% fill), `config.py` parsing/clamping of `style`/`bar_width`
  (including invalid values falling back to defaults), dispatcher wiring in `refresh.py`.
