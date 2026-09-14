import unicodedata
import unittest

from claude_usage import config, render


class RenderText(unittest.TestCase):
    def test_renders_configured_order(self):
        out = render.render_text({"1w": 37, "5h": 14, "Fable": 36}, ["5h", "1w", "Fable"])
        self.assertEqual(out, "5h 14% · 1w 37% · Fable 36%")

    def test_skips_labels_the_account_does_not_have(self):
        out = render.render_text({"5h": 14, "1w": 37}, ["5h", "1w", "Fable"])
        self.assertEqual(out, "5h 14% · 1w 37%")

    def test_ignores_labels_outside_the_configured_order(self):
        out = render.render_text({"5h": 14, "Opus": 80}, ["5h", "1w"])
        self.assertEqual(out, "5h 14%")

    def test_honours_a_custom_separator(self):
        out = render.render_text({"5h": 1, "1w": 2}, ["5h", "1w"], separator=" | ")
        self.assertEqual(out, "5h 1% | 1w 2%")

    def test_no_data_renders_empty(self):
        self.assertEqual(render.render_text({}, ["5h"]), "")

    def test_drops_trailing_segments_rather_than_truncating_mid_word(self):
        percents = {"a" * 30: 10, "b" * 30: 20, "c" * 30: 30}
        out = render.render_text(percents, ["a" * 30, "b" * 30, "c" * 30])
        self.assertLessEqual(len(out), render.MAX_TOKEN_LEN)
        self.assertEqual(out, "a" * 30 + " 10% · " + "b" * 30 + " 20%")

    def test_hard_truncates_a_single_oversized_segment(self):
        out = render.render_text({"z" * 200: 5}, ["z" * 200])
        self.assertEqual(len(out), render.MAX_TOKEN_LEN)


class Sextant(unittest.TestCase):
    def test_empty_mask_is_a_space(self):
        self.assertEqual(render.sextant(0), " ")

    def test_full_mask_is_a_full_block(self):
        self.assertEqual(render.sextant(0b111111), "█")

    def test_full_columns_use_the_half_blocks(self):
        self.assertEqual(render.sextant(0b010101), "▌")
        self.assertEqual(render.sextant(0b101010), "▐")

    def test_bits_follow_the_standard_sextant_numbering(self):
        for bit, position in enumerate("123456"):
            name = unicodedata.name(render.sextant(1 << bit))
            self.assertEqual(name, f"BLOCK SEXTANT-{position}")

    def test_every_mask_maps_to_its_own_single_glyph(self):
        glyphs = [render.sextant(mask) for mask in range(64)]
        self.assertEqual(len(set(glyphs)), 64)
        self.assertTrue(all(len(g) == 1 for g in glyphs))


def mask_of(glyph):
    """Glyph -> dot bitmask, decoded from the Unicode name rather than render's own table."""
    if glyph == " ":
        return 0
    name = unicodedata.name(glyph)
    fixed = {"FULL BLOCK": 0b111111, "LEFT HALF BLOCK": 0b010101, "RIGHT HALF BLOCK": 0b101010}
    if name in fixed:
        return fixed[name]
    return sum(1 << (int(d) - 1) for d in name.split("-")[-1])


class Bars(unittest.TestCase):
    def rows(self, bar, bar_width=10):
        """Bar string -> lit dot count per row, asserting each row is a contiguous run."""
        self.assertTrue(bar.endswith(render.EDGE_MARKER))
        body = bar[: -len(render.EDGE_MARKER)]
        self.assertEqual(len(body), bar_width)
        masks = [mask_of(ch) for ch in body]
        counts = []
        for row in range(3):
            dots = [bool(m >> (row * 2 + col) & 1) for m in masks for col in (0, 1)]
            lit = sum(dots)
            self.assertEqual(dots, [True] * lit + [False] * (len(dots) - lit))
            counts.append(lit)
        return counts

    def test_rows_follow_the_configured_order(self):
        bar = render.render_bars({"1w": 50, "5h": 100, "Fable": 0}, ["5h", "1w", "Fable"], 10)
        self.assertEqual(self.rows(bar), [20, 10, 0])

    def test_two_dot_columns_per_character(self):
        bar = render.render_bars({"5h": 100}, ["5h"], 4)
        self.assertEqual(self.rows(bar, bar_width=4), [8, 0, 0])

    def test_absent_labels_are_skipped_rather_than_reserved(self):
        bar = render.render_bars({"Fable": 100}, ["5h", "1w", "Fable"], 10)
        self.assertEqual(self.rows(bar), [20, 0, 0])

    def test_labels_outside_the_configured_order_are_ignored(self):
        bar = render.render_bars({"5h": 100, "Opus": 100}, ["5h", "1w"], 10)
        self.assertEqual(self.rows(bar), [20, 0, 0])

    def test_drops_everything_past_the_third_present_label(self):
        percents = {"5h": 100, "1w": 100, "Opus": 100, "Sonnet": 100}
        bar = render.render_bars(percents, ["5h", "1w", "Opus", "Sonnet"], 10)
        self.assertEqual(self.rows(bar), [20, 20, 20])

    def test_clamps_out_of_range_percents(self):
        bar = render.render_bars({"5h": 140, "1w": -5}, ["5h", "1w"], 10)
        self.assertEqual(self.rows(bar), [20, 0, 0])

    def test_rounds_to_the_nearest_dot(self):
        self.assertEqual(self.rows(render.render_bars({"5h": 5}, ["5h"], 10)), [1, 0, 0])
        self.assertEqual(self.rows(render.render_bars({"5h": 2}, ["5h"], 10)), [0, 0, 0])

    def test_marks_the_full_edge_at_every_fill(self):
        for percent in (0, 37, 100):
            bar = render.render_bars({"5h": percent}, ["5h"], 10)
            self.assertEqual(len(bar), 11)
            self.assertTrue(bar.endswith(render.EDGE_MARKER))

    def test_no_present_labels_renders_empty_so_the_row_clears(self):
        self.assertEqual(render.render_bars({}, ["5h", "1w"], 10), "")
        self.assertEqual(render.render_bars({"Opus": 50}, ["5h"], 10), "")

    def test_renders_the_expected_glyphs(self):
        self.assertEqual(render.render_bars({"5h": 100}, ["5h"], 1), "\U0001fb02▏")


class Dispatch(unittest.TestCase):
    def test_text_style_renders_the_text_form(self):
        cfg = config.Config(style=config.STYLE_TEXT, separator=" | ")
        out = render.render({"5h": 14, "1w": 37}, ["5h", "1w"], cfg)
        self.assertEqual(out, "5h 14% | 1w 37%")

    def test_default_style_is_text(self):
        out = render.render({"5h": 14}, ["5h"], config.Config())
        self.assertEqual(out, "5h 14%")

    def test_bars_style_renders_the_bar_form(self):
        cfg = config.Config(style=config.STYLE_BARS, bar_width=4)
        out = render.render({"5h": 100}, ["5h"], cfg)
        self.assertEqual(out, render.render_bars({"5h": 100}, ["5h"], 4))
        self.assertEqual(len(out), 5)
