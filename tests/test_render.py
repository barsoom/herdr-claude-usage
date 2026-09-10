import unittest

from claude_usage import render


class Render(unittest.TestCase):
    def test_renders_configured_order(self):
        out = render.render({"1w": 37, "5h": 14, "Fable": 36}, ["5h", "1w", "Fable"])
        self.assertEqual(out, "5h 14% · 1w 37% · Fable 36%")

    def test_skips_labels_the_account_does_not_have(self):
        out = render.render({"5h": 14, "1w": 37}, ["5h", "1w", "Fable"])
        self.assertEqual(out, "5h 14% · 1w 37%")

    def test_ignores_labels_outside_the_configured_order(self):
        out = render.render({"5h": 14, "Opus": 80}, ["5h", "1w"])
        self.assertEqual(out, "5h 14%")

    def test_honours_a_custom_separator(self):
        out = render.render({"5h": 1, "1w": 2}, ["5h", "1w"], separator=" | ")
        self.assertEqual(out, "5h 1% | 1w 2%")

    def test_no_data_renders_empty(self):
        self.assertEqual(render.render({}, ["5h"]), "")

    def test_drops_trailing_segments_rather_than_truncating_mid_word(self):
        percents = {"a" * 30: 10, "b" * 30: 20, "c" * 30: 30}
        out = render.render(percents, ["a" * 30, "b" * 30, "c" * 30])
        self.assertLessEqual(len(out), render.MAX_TOKEN_LEN)
        self.assertEqual(out, "a" * 30 + " 10% · " + "b" * 30 + " 20%")

    def test_hard_truncates_a_single_oversized_segment(self):
        out = render.render({"z" * 200: 5}, ["z" * 200])
        self.assertEqual(len(out), render.MAX_TOKEN_LEN)
