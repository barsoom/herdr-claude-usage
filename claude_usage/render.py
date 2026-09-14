"""{label: percent} -> one sidebar token value."""

from .config import STYLE_BARS

# Herdr caps a metadata token value at 80 characters.
MAX_TOKEN_LEN = 80

DEFAULT_SEPARATOR = " · "


def render_text(percents, order, separator=DEFAULT_SEPARATOR, max_len=MAX_TOKEN_LEN):
    """`order` is both the whitelist and the display order. Overflow drops whole segments."""
    segments = [f"{label} {percents[label]}%" for label in order if label in percents]
    while segments:
        out = separator.join(segments)
        if len(out) <= max_len:
            return out
        segments.pop()
        if not segments:
            # One segment alone is too long; a hard cut beats reporting nothing.
            return out[:max_len]
    return ""


# Sextant block: 2 dot-columns x 3 dot-rows per char. Bits 0,1 = top row; 2,3 = middle; 4,5 = bottom.
SEXTANT_BASE = 0x1FB00
# Unicode omits these four from the block; they already exist elsewhere.
_SEXTANT_EXCEPTIONS = {0: " ", 0b010101: "▌", 0b101010: "▐", 0b111111: "█"}


def sextant(mask):
    """Dot-grid bitmask -> one glyph."""
    glyph = _SEXTANT_EXCEPTIONS.get(mask)
    if glyph is not None:
        return glyph
    skipped = sum(1 for gap in (0, 0b010101, 0b101010) if mask > gap)
    return chr(SEXTANT_BASE + mask - skipped)


MAX_BAR_ROWS = 3
# No color in Herdr's token schema, so the 100% edge gets a glyph instead of a darkened track.
EDGE_MARKER = "▏"


def render_bars(percents, order, bar_width=10):
    """One stacked sextant bar per limit, `order` first-come. Rows: top, middle, bottom."""
    rows = [label for label in order if label in percents][:MAX_BAR_ROWS]
    if not rows:
        return ""
    steps = bar_width * 2
    # Half-up rounding on ints: 20 steps at the default width -> one dot per 5%.
    filled = [(min(max(percents[label], 0), 100) * steps + 50) // 100 for label in rows]
    out = []
    for char in range(bar_width):
        mask = 0
        for row, lit in enumerate(filled):
            for col in (0, 1):
                if char * 2 + col < lit:
                    mask |= 1 << (row * 2 + col)
        out.append(sextant(mask))
    return "".join(out) + EDGE_MARKER


def render(percents, order, config):
    """Style dispatcher. `text` stays the default so existing sidebars keep their format."""
    if config.style == STYLE_BARS:
        return render_bars(percents, order, config.bar_width)
    return render_text(percents, order, separator=config.separator)
