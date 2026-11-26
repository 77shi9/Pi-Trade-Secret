import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.http import MAX_BACKOFF_SECONDS, MAX_RETRY_AFTER_SECONDS, backoff_delay, next_link


class BackoffTest(unittest.TestCase):
    def test_exponential_growth(self):
        self.assertEqual(backoff_delay(1, None), 1.0)
        self.assertEqual(backoff_delay(2, None), 2.0)
        self.assertEqual(backoff_delay(3, None), 4.0)
        self.assertEqual(backoff_delay(4, None), 8.0)

    def test_backoff_capped(self):
        self.assertEqual(backoff_delay(10, None), MAX_BACKOFF_SECONDS)

    def test_retry_after_respected(self):
        self.assertEqual(backoff_delay(1, "45"), 45.0)

    def test_retry_after_capped(self):
        self.assertEqual(backoff_delay(1, "999"), MAX_RETRY_AFTER_SECONDS)

    def test_http_date_retry_after_falls_back_to_exponential(self):
        self.assertEqual(backoff_delay(1, "Wed, 21 Oct 2015 07:28:00 GMT"), 1.0)

    def test_invalid_retry_after_falls_back(self):
        self.assertEqual(backoff_delay(2, ""), 2.0)
        self.assertEqual(backoff_delay(2, "abc"), 2.0)


class NextLinkTest(unittest.TestCase):
    def test_graph_odata_next_link(self):
        body = {"value": [], "@odata.nextLink": "https://graph.microsoft.com/v1.0/x?$skiptoken=1"}
        self.assertEqual(next_link(body), "https://graph.microsoft.com/v1.0/x?$skiptoken=1")

    def test_sharepoint_verbose_next_link(self):
        body = {"d": {"results": [], "__next": "https://x.sharepoint.com/_api/y"}}
        self.assertEqual(next_link(body), "https://x.sharepoint.com/_api/y")

    def test_no_next_link(self):
        self.assertIsNone(next_link({"value": []}))
        self.assertIsNone(next_link(None))
        self.assertIsNone(next_link({"d": {"results": []}}))

    def test_non_string_next_link_ignored(self):
        self.assertIsNone(next_link({"nextLink": 123}))


if __name__ == "__main__":
    unittest.main()
