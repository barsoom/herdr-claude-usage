import io
import json
import unittest

from claude_usage import api


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


class FetchUsage(unittest.TestCase):
    def test_sends_a_bearer_token_and_returns_parsed_json(self):
        seen = {}

        def opener(request, timeout=None):
            seen["url"] = request.full_url
            seen["headers"] = {k.lower(): v for k, v in request.header_items()}
            seen["timeout"] = timeout
            return FakeResponse(json.dumps({"limits": []}).encode("utf-8"))

        got = api.fetch_usage("tok", opener=opener, timeout=7)
        self.assertEqual(got, {"limits": []})
        self.assertEqual(seen["url"], api.USAGE_URL)
        self.assertEqual(seen["headers"]["authorization"], "Bearer tok")
        self.assertEqual(seen["timeout"], 7)

    def test_wraps_transport_failure(self):
        def opener(request, timeout=None):
            raise OSError("no route to host")

        with self.assertRaises(api.UsageApiError):
            api.fetch_usage("tok", opener=opener)

    def test_wraps_unparseable_body(self):
        def opener(request, timeout=None):
            return FakeResponse(b"<html>nope</html>")

        with self.assertRaises(api.UsageApiError):
            api.fetch_usage("tok", opener=opener)

    def test_reports_the_http_status_of_a_rejected_token(self):
        import urllib.error

        def opener(request, timeout=None):
            raise urllib.error.HTTPError(api.USAGE_URL, 401, "Unauthorized", {}, None)

        with self.assertRaises(api.UsageApiError) as ctx:
            api.fetch_usage("tok", opener=opener)
        self.assertEqual(ctx.exception.status, 401)
