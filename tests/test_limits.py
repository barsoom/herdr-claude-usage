import unittest

from claude_usage import limits


class ExtractFromLimitsArray(unittest.TestCase):
    def test_maps_session_weekly_and_scoped_model(self):
        usage = {
            "limits": [
                {"kind": "session", "percent": 14, "resets_at": "2026-09-10T10:20:00+00:00"},
                {"kind": "weekly_all", "percent": 37, "resets_at": "2026-09-13T17:00:00+00:00"},
                {
                    "kind": "weekly_scoped",
                    "percent": 36,
                    "scope": {"model": {"display_name": "Fable"}},
                },
            ]
        }
        self.assertEqual(limits.extract(usage), {"5h": 14, "1w": 37, "Fable": 36})

    def test_omits_absent_windows(self):
        usage = {"limits": [{"kind": "session", "percent": 3}]}
        self.assertEqual(limits.extract(usage), {"5h": 3})

    def test_rounds_fractional_percent(self):
        usage = {"limits": [{"kind": "session", "percent": 13.6}]}
        self.assertEqual(limits.extract(usage), {"5h": 14})

    def test_skips_rows_without_a_percent(self):
        usage = {"limits": [{"kind": "session"}, {"kind": "weekly_all", "percent": 5}]}
        self.assertEqual(limits.extract(usage), {"1w": 5})

    def test_skips_scoped_row_without_a_model_name(self):
        usage = {"limits": [{"kind": "weekly_scoped", "percent": 9, "scope": None}]}
        self.assertEqual(limits.extract(usage), {})

    def test_ignores_unknown_kinds(self):
        usage = {"limits": [{"kind": "hourly_moon_phase", "percent": 50}]}
        self.assertEqual(limits.extract(usage), {})


class ExtractLegacyFallback(unittest.TestCase):
    def test_reads_top_level_fields_when_limits_array_is_absent(self):
        usage = {
            "five_hour": {"utilization": 14.0},
            "seven_day": {"utilization": 37.0},
            "seven_day_overage_included": {"utilization": 36.0},
        }
        self.assertEqual(limits.extract(usage), {"5h": 14, "1w": 37, "Fable": 36})

    def test_ignores_null_windows(self):
        usage = {"five_hour": {"utilization": 2.0}, "seven_day_opus": None}
        self.assertEqual(limits.extract(usage), {"5h": 2})

    def test_prefers_the_limits_array_over_legacy_fields(self):
        usage = {
            "five_hour": {"utilization": 99.0},
            "limits": [{"kind": "session", "percent": 1}],
        }
        self.assertEqual(limits.extract(usage), {"5h": 1})

    def test_empty_usage_yields_nothing(self):
        self.assertEqual(limits.extract({}), {})
