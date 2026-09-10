"""{label: percent} -> one sidebar token value."""

# Herdr caps a metadata token value at 80 characters.
MAX_TOKEN_LEN = 80

DEFAULT_SEPARATOR = " · "


def render(percents, order, separator=DEFAULT_SEPARATOR, max_len=MAX_TOKEN_LEN):
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
