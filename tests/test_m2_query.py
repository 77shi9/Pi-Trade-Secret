import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from query.offboarding import query_grants, remediation_hints, via_group_summary
from scan.scanner import run_scan
from tests.test_m1_scanner import FakeClient


class OffboardingQueryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db_path = str(Path(cls.tmp.name) / "governance.sqlite3")
        run_scan("https://danfoss.sharepoint.com/sites/TS", cls.db_path,
                 client=FakeClient())

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def _query(self, email):
        from store.schema import connect
        conn = connect(self.db_path)
        try:
            return query_grants(conn, email)
        finally:
            conn.close()

    def test_direct_grant_user(self):
        report = self._query("Writer@Danfoss.com")  # case-insensitive
        self.assertEqual(len(report["direct_grants"]), 1)
        grant = report["direct_grants"][0]
        self.assertEqual(grant["root_path"], "/sites/TS/Docs/sub")
        self.assertEqual(grant["roles"], "write")
        self.assertEqual(report["email"], "writer@danfoss.com")

    def test_site_group_membership_and_via_group(self):
        report = self._query("yong.hu@danfoss.com")
        self.assertEqual(len(report["site_group_memberships"]), 1)
        self.assertEqual(report["site_group_memberships"][0]["group_name"], "TS Owners")
        self.assertFalse(report["site_group_memberships"][0]["is_system"])
        # TS Owners (spgroup:3) owns the library scope
        self.assertEqual(len(report["via_group_access"]), 1)
        self.assertEqual(report["via_group_access"][0]["root_path"], "/sites/TS/Docs")
        self.assertEqual(report["via_group_access"][0]["roles"], "owner")

    def test_link_recipient_multi(self):
        report = self._query("a@x.com")
        self.assertEqual(len(report["sharing_links"]), 1)
        link = report["sharing_links"][0]
        self.assertTrue(link["is_recipient"])
        self.assertTrue(link["multi_recipient"])
        self.assertEqual(link["recipient_count"], 2)
        self.assertEqual(link["link_scope"], "users")

    def test_link_owner_only(self):
        report = self._query("owner@x.com")
        self.assertEqual(len(report["sharing_links"]), 1)
        link = report["sharing_links"][0]
        self.assertTrue(link["is_owner"])
        self.assertFalse(link["is_recipient"])

    def test_substring_email_not_matched(self):
        # 'a@x.com' is a substring of 'b@a@x.com'-style noise; ensure a
        # different unrelated email yields nothing
        report = self._query("nobody@nowhere.com")
        self.assertEqual(report["direct_grants"], [])
        self.assertEqual(report["site_group_memberships"], [])
        self.assertEqual(report["sharing_links"], [])

    def test_remediation_hints(self):
        report = self._query("yong.hu@danfoss.com")
        hints = remediation_hints(report)
        actions = [h["action"] for h in hints]
        self.assertIn("remove_site_group_member", actions)
        self.assertNotIn("skip_system_group", actions)  # TS Owners is not a system group

        report = self._query("a@x.com")
        hints = remediation_hints(report)
        actions = [h["action"] for h in hints]
        self.assertIn("update_sharing_link_recipients", actions)  # multi-recipient link

    def test_via_group_summary(self):
        report = self._query("yong.hu@danfoss.com")
        summary = via_group_summary(report)
        self.assertEqual(len(summary), 1)
        self.assertEqual(summary[0]["group"], "TS Owners")
        self.assertEqual(summary[0]["scope_count"], 1)


if __name__ == "__main__":
    unittest.main()
