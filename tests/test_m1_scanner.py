import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scan.scanner import CountingClient, run_scan
from store.schema import connect, init_schema, schema_status


class FakeClient:
    """Offline stand-in for ScHttpClient with canned tenant responses.

    Routes are matched as ordered (substring, response-body) pairs; the first
    matching substring wins, so specific routes must precede generic ones.
    """

    ROUTES = [
        # Graph site
        ("sites/danfoss.sharepoint.com:/sites/TS", {"id": "gsite1", "displayName": "TS"}),
        # Graph drives
        ("/drives?", {"value": [
            {"id": "DRIVE1", "name": "Docs", "driveType": "documentLibrary",
             "webUrl": "https://danfoss.sharepoint.com/sites/TS/Docs"},
        ]}),
        # Graph drive root -> list GUID
        ("/root?", {"id": "groot", "name": "root",
                    "webUrl": "https://danfoss.sharepoint.com/sites/TS/Docs",
                    "sharepointIds": {"listId": "LIB1", "siteId": "s1"}}),
        # Graph delta (path -> graph id map; 'sub' intentionally MISSING here to
        # exercise the path-lookup fallback; must match before permissions)
        ("/root/delta", {"value": [
            {"id": "groot", "webUrl": "https://danfoss.sharepoint.com/sites/TS/Docs"},
            {"id": "g_f4", "webUrl": "https://danfoss.sharepoint.com/sites/TS/Docs/sub/f4.txt"},
            {"id": "g_f1", "webUrl": "https://danfoss.sharepoint.com/sites/TS/Docs/f1.txt"},
            {"id": "g_f2", "webUrl": "https://danfoss.sharepoint.com/sites/TS/Docs/f2.txt"},
        ]}),
        # Graph path lookup fallback for the unique folder 'sub'
        ("root:/sub", {"id": "g_sub", "name": "sub"}),
        # Graph root permissions (library scope + site-inherited entries)
        ("/root/permissions", {"value": [
            {"id": "p1", "roles": ["owner"],
             "grantedToV2": {"siteGroup": {"displayName": "TS Owners", "id": "3",
                                           "loginName": "TS Owners"},
                             "sharePointGroup": {"title": "TS Owners", "principalId": "3"}}},
            {"id": "p2", "roles": ["read"],
             "grantedToV2": {"user": {"id": "u1", "email": "reader@danfoss.com"}},
             "inheritedFrom": {"id": "site"}},
            {"id": "p3", "roles": ["read"],
             "link": {"type": "view", "scope": "organization", "webUrl": "https://l"},
             "inheritedFrom": {"id": "site"}},
        ]}),
        # Graph item permissions for the unique folder 'sub'
        ("/items/g_sub/permissions", {"value": [
            {"id": "p4", "roles": ["write"],
             "grantedToV2": {"user": {"id": "u2", "email": "writer@danfoss.com"}}},
            {"id": "p5", "roles": ["read"],
             "link": {"type": "edit", "scope": "users", "webUrl": "https://l2"},
             "grantedToIdentitiesV2": [
                 {"user": {"email": "a@x.com"}},
                 {"user": {"email": "b@x.com"}},
             ],
             "grantedBy": {"user": {"id": "o1", "email": "owner@x.com",
                                     "displayName": "Owner"}}},
            {"id": "p6", "roles": ["read"],
             "grantedToV2": {"user": {"email": "inherited-skip@x.com"}},
             "inheritedFrom": {"id": "root"}},
        ]}),
        # REST group users (before generic sitegroups)
        ("/sitegroups(3)/users", {"value": [
            {"LoginName": "i:0#.f|membership|yong.hu@danfoss.com",
             "Email": "yong.hu@danfoss.com", "Title": "Yong Hu"},
        ]}),
        # REST site groups
        ("/sitegroups?", {"value": [{"Id": 3, "Title": "TS Owners", "Description": None}]}),
        # REST list items (before generic lists route)
        ("items?", {"value": [
            {"Id": 1, "ID": 1, "FSObjType": 1,
             "FileRef": "/sites/TS/Docs/sub", "FileLeafRef": "sub",
             "HasUniqueRoleAssignments": True},
            {"Id": 2, "ID": 2, "FSObjType": 0,
             "FileRef": "/sites/TS/Docs/f1.txt", "FileLeafRef": "f1.txt",
             "HasUniqueRoleAssignments": False},
            {"Id": 3, "ID": 3, "FSObjType": 0,
             "FileRef": "/sites/TS/Docs/f2.txt", "FileLeafRef": "f2.txt",
             "HasUniqueRoleAssignments": False},
            {"Id": 4, "ID": 4, "FSObjType": 0,
             "FileRef": "/sites/TS/Docs/sub/f4.txt", "FileLeafRef": "f4.txt",
             "HasUniqueRoleAssignments": False},
        ]}),
        # REST single library
        ("lists('LIB1')", {"Id": "LIB1", "Title": "Docs",
                           "HasUniqueRoleAssignments": True}),
        # REST web
        ("_api/web", {"Id": "WEB1", "Title": "TS",
                      "ServerRelativeUrl": "/sites/TS",
                      "HasUniqueRoleAssignments": True}),
    ]

    def __init__(self):
        self.calls = []

    def get_json(self, url, **kwargs):
        self.calls.append(url)
        for substring, body in self.ROUTES:
            if substring in url:
                return json.loads(json.dumps(body))
        raise AssertionError(f"unexpected URL: {url}")

    def pages(self, url, **kwargs):
        yield self.get_json(url, **kwargs)


class ScannerFlowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmp.name) / "governance.sqlite3")

    def tearDown(self):
        self.tmp.cleanup()

    def test_full_scan_flow(self):
        stats = run_scan("https://danfoss.sharepoint.com/sites/TS", self.db_path,
                         client=FakeClient())
        self.assertEqual(stats["status"], "success")
        # site(1) + library(1) + 4 items
        self.assertEqual(stats["objects"]["total"], 6)
        # web + library + unique folder 'sub'
        self.assertEqual(stats["unique_scopes"]["total"], 3)
        self.assertEqual(stats["unique_scopes"]["folder"], 1)
        self.assertEqual(stats["inherited_objects"], 3)
        # requests: site 1 + drives 1 + root 1 + web 1 + list 1 + items 1
        #         + groups 1 + group_users 1 + delta 1 + permissions 2
        #         + path_lookup fallback 1 (sub not in delta) = 12
        self.assertEqual(stats["requests"]["total"], 12)
        self.assertEqual(stats["requests"]["graph_path_lookup"], 1)
        self.assertEqual(stats["permission_reads"], 2)
        # grants: web(reader) + lib(TS Owners) + sub(writer); links: web(org) + sub(users)
        self.assertEqual(stats["grants"]["role_assignment_rows"], 3)
        self.assertEqual(stats["grants"]["sharing_link_rows"], 2)
        self.assertEqual(stats["grants"]["site_groups"], 1)
        self.assertEqual(stats["grants"]["group_members"], 1)

        conn = connect(self.db_path)
        try:
            status = schema_status(conn)
            self.assertEqual(status["tables"]["permission_scopes"], 3)
            self.assertEqual(status["tables"]["objects"], 6)
            self.assertEqual(status["tables"]["role_assignments"], 3)
            self.assertEqual(status["tables"]["sharing_links"], 2)
            self.assertEqual(status["tables"]["site_group_members"], 1)

            scopes = {
                row["scope_id"]: row for row in conn.execute(
                    "SELECT scope_id, scope_type, root_path, inheriting_count "
                    "FROM permission_scopes")
            }
            self.assertIn("web", scopes)
            self.assertIn("list:LIB1", scopes)
            self.assertIn("item:LIB1:1", scopes)
            # f1/f2 inherit from the unique library; f4 from the unique folder
            self.assertEqual(scopes["list:LIB1"]["inheriting_count"], 2)
            self.assertEqual(scopes["item:LIB1:1"]["inheriting_count"], 1)

            # direct grant rows
            grants = {(r["scope_id"], r["principal_key"]): r for r in conn.execute(
                "SELECT scope_id, principal_key, principal_id, roles FROM role_assignments")}
            self.assertIn(("web", "user:reader@danfoss.com"), grants)
            self.assertIn(("list:LIB1", "spgroup:3"), grants)
            self.assertEqual(grants[("list:LIB1", "spgroup:3")]["principal_id"], 3)
            self.assertIn(("item:LIB1:1", "user:writer@danfoss.com"), grants)
            # the inherited entry on 'sub' must NOT be stored
            self.assertNotIn(("item:LIB1:1", "user:inherited-skip@x.com"), grants)

            links = {r["scope_id"]: r for r in conn.execute(
                "SELECT scope_id, link_id, link_scope, recipient_count, owner_email "
                "FROM sharing_links")}
            self.assertIn("web", links)
            self.assertIn("item:LIB1:1", links)
            self.assertEqual(links["item:LIB1:1"]["recipient_count"], 2)
            self.assertEqual(links["item:LIB1:1"]["owner_email"], "owner@x.com")
            self.assertEqual(links["web"]["link_scope"], "organization")
        finally:
            conn.close()


class CountingClientTest(unittest.TestCase):
    def test_classify(self):
        from scan.scanner import _classify
        self.assertEqual(_classify("https://graph.microsoft.com/v1.0/sites/x/drives?x"), "graph_drives")
        self.assertEqual(_classify("https://graph.microsoft.com/v1.0/drives/d/root/delta?x"), "graph_delta")
        self.assertEqual(_classify("https://graph.microsoft.com/v1.0/drives/d/root/permissions"), "graph_permissions")
        self.assertEqual(_classify("https://graph.microsoft.com/v1.0/drives/d/root:/sub?x"), "graph_path_lookup")
        self.assertEqual(_classify("https://x.sharepoint.com/_api/web/lists('g')/items?"), "sp_items")
        self.assertEqual(_classify("https://x.sharepoint.com/_api/web/lists('g')?"), "sp_list")
        self.assertEqual(_classify("https://x.sharepoint.com/_api/web?"), "sp_web")
        self.assertEqual(_classify("https://x.sharepoint.com/_api/web/sitegroups(3)/users?"), "sp_group_users")
        self.assertEqual(_classify("https://graph.microsoft.com/v1.0/drives/d/root?"), "graph_drive_root")

    def test_counts_get_and_pages(self):
        fake = FakeClient()
        counting = CountingClient(fake)
        counting.get_json("https://x.sharepoint.com/_api/web?")
        for _ in counting.pages("https://x.sharepoint.com/_api/web/lists('LIB1')/items?"):
            pass
        self.assertEqual(counting.counts["sp_web"], 1)
        self.assertEqual(counting.counts["sp_items"], 1)
        self.assertEqual(counting.total, 2)


if __name__ == "__main__":
    unittest.main()
