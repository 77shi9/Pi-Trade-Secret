import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from remediate.apply import execute_plan
from remediate.plan import build_plan
from scan.scanner import run_scan
from store.schema import SCHEMA_VERSION, connect, init_schema
from tests.test_m1_scanner import FakeClient


class FakeApplyClient:
    """Records write calls; serves the contextinfo digest."""

    def __init__(self):
        self.calls = []

    def get_json(self, url, **kwargs):
        self.calls.append(("GET", url, None))
        raise AssertionError(f"apply should not GET: {url}")

    def post_json(self, url, body=None, **kwargs):
        self.calls.append(("POST", url, body))
        if url.endswith("/_api/contextinfo"):
            return {"d": {"GetContextWebInformation": {"FormDigestValue": "DIGEST-123"}}}
        return None

    def delete(self, url, **kwargs):
        self.calls.append(("DELETE", url, None))
        return None

    def patch_json(self, url, body, **kwargs):
        self.calls.append(("PATCH", url, body))
        return None


class M3PlanTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db_path = str(Path(cls.tmp.name) / "governance.sqlite3")
        run_scan("https://danfoss.sharepoint.com/sites/TS", cls.db_path,
                 client=FakeClient())

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def _conn(self):
        return connect(self.db_path)

    def test_schema_migrated_to_v2(self):
        conn = self._conn()
        try:
            self.assertEqual(
                conn.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION
            )
            columns = {row[1] for row in conn.execute("PRAGMA table_info(role_assignments)")}
            self.assertIn("permission_id", columns)
            scope_columns = {row[1] for row in conn.execute("PRAGMA table_info(permission_scopes)")}
            self.assertIn("graph_drive_id", scope_columns)
            self.assertIn("graph_item_id", scope_columns)
            # scanner populated graph identity of the unique folder scope
            row = conn.execute(
                "SELECT graph_drive_id, graph_item_id FROM permission_scopes "
                "WHERE scope_id = 'item:LIB1:1'"
            ).fetchone()
            self.assertEqual(row["graph_drive_id"], "DRIVE1")
            self.assertEqual(row["graph_item_id"], "g_sub")
        finally:
            conn.close()

    def test_plan_direct_grant_graph_method(self):
        conn = self._conn()
        try:
            plan = build_plan(conn, "writer@danfoss.com")
        finally:
            conn.close()
        delete_ops = [op for op in plan["operations"]
                      if op["op"] == "delete_role_assignment"]
        self.assertEqual(len(delete_ops), 1)
        op = delete_ops[0]
        self.assertEqual(op["method"], "graph")
        self.assertEqual(op["scope_id"], "item:LIB1:1")
        self.assertEqual(op["graph_drive_id"], "DRIVE1")
        self.assertEqual(op["graph_item_id"], "g_sub")
        self.assertEqual(op["graph_permission_id"], "p4")

    def test_plan_link_recipient_update_with_remaining(self):
        conn = self._conn()
        try:
            plan = build_plan(conn, "a@x.com")
        finally:
            conn.close()
        update_ops = [op for op in plan["operations"]
                      if op["op"] == "update_sharing_link_recipients"]
        self.assertEqual(len(update_ops), 1)
        op = update_ops[0]
        self.assertEqual(op["link_id"], "p5")
        self.assertEqual(op["remaining_recipients"], [{"email": "b@x.com"}])
        self.assertEqual(op["roles"], ["write"])  # link_type edit

    def test_plan_json_round_trip(self):
        conn = self._conn()
        try:
            plan = build_plan(conn, "a@x.com", operation_id="op_test_1")
        finally:
            conn.close()
        text = json.dumps(plan, ensure_ascii=False)
        restored = json.loads(text)
        self.assertEqual(restored["operation_id"], "op_test_1")
        self.assertEqual(restored["target_email"], "a@x.com")
        self.assertEqual(len(restored["operations"]), len(plan["operations"]))


class M3ApplyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db_path = str(Path(cls.tmp.name) / "governance.sqlite3")
        run_scan("https://danfoss.sharepoint.com/sites/TS", cls.db_path,
                 client=FakeClient())

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_dry_run_makes_no_http_calls_and_no_audit(self):
        conn = connect(self.db_path)
        fake = FakeApplyClient()
        try:
            plan = build_plan(conn, "writer@danfoss.com")
            summary = execute_plan(plan, conn, "https://danfoss.sharepoint.com/sites/TS",
                                   client=fake, apply_changes=False)
        finally:
            conn.close()
        self.assertEqual(fake.calls, [])  # no HTTP at all
        self.assertEqual(summary["executed"], 0)
        conn = connect(self.db_path)
        try:
            audit = conn.execute(
                "SELECT COUNT(*) FROM audit_log WHERE operation_id = ?",
                (plan["operation_id"],),
            ).fetchone()[0]
            self.assertEqual(audit, 0)  # dry-run leaves no audit rows
        finally:
            conn.close()

    def test_apply_executes_graph_delete_and_audits(self):
        conn = connect(self.db_path)
        fake = FakeApplyClient()
        try:
            plan = build_plan(conn, "writer@danfoss.com")
            summary = execute_plan(plan, conn, "https://danfoss.sharepoint.com/sites/TS",
                                   client=fake, apply_changes=True)
        finally:
            conn.close()
        self.assertEqual(summary["executed"], 1)
        self.assertEqual(summary["ok"], 1)
        self.assertEqual(summary["failed"], 0)
        # one Graph DELETE with the right URL
        deletes = [c for c in fake.calls if c[0] == "DELETE"]
        self.assertEqual(len(deletes), 1)
        self.assertIn("/drives/DRIVE1/items/g_sub/permissions/p4", deletes[0][1])
        # audit row written
        conn = connect(self.db_path)
        try:
            rows = conn.execute(
                "SELECT action_type, result, http_method, url, dry_run FROM audit_log "
                "WHERE operation_id = ?",
                (plan["operation_id"],),
            ).fetchall()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["action_type"], "delete_role_assignment")
            self.assertEqual(rows[0]["result"], "ok")
            self.assertEqual(rows[0]["http_method"], "DELETE")
            self.assertEqual(rows[0]["dry_run"], 0)
        finally:
            conn.close()

    def test_apply_link_recipient_patch(self):
        conn = connect(self.db_path)
        fake = FakeApplyClient()
        try:
            plan = build_plan(conn, "a@x.com")
            summary = execute_plan(plan, conn, "https://danfoss.sharepoint.com/sites/TS",
                                   client=fake, apply_changes=True)
        finally:
            conn.close()
        patches = [c for c in fake.calls if c[0] == "PATCH"]
        self.assertEqual(len(patches), 1)
        url, body = patches[0][1], patches[0][2]
        self.assertIn("/drives/DRIVE1/items/g_sub/permissions/p5", url)
        self.assertEqual(body["recipients"], [{"email": "b@x.com"}])
        self.assertEqual(summary["ok"], 1)

    def test_apply_group_member_removal_uses_digest(self):
        conn = connect(self.db_path)
        fake = FakeApplyClient()
        try:
            plan = build_plan(conn, "yong.hu@danfoss.com")
            summary = execute_plan(plan, conn, "https://danfoss.sharepoint.com/sites/TS",
                                   client=fake, apply_changes=True)
        finally:
            conn.close()
        posts = [c for c in fake.calls if c[0] == "POST"]
        # contextinfo + removebyloginname
        self.assertEqual(len(posts), 2)
        self.assertTrue(posts[0][1].endswith("/_api/contextinfo"))
        self.assertIn("sitegroups(3)/users/removebyloginname", posts[1][1])
        self.assertIn("yong.hu", posts[1][1])
        self.assertEqual(summary["ok"], 1)


class SchemaV2MigrationTest(unittest.TestCase):
    def test_migration_from_v1(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        try:
            # simulate a v1 database (old role_assignments without permission_id)
            conn.execute(
                "CREATE TABLE role_assignments ("
                "scope_id TEXT NOT NULL, principal_key TEXT NOT NULL, "
                "principal_id INTEGER, roles TEXT, "
                "first_seen_run_id TEXT NOT NULL, last_seen_run_id TEXT NOT NULL, "
                "PRIMARY KEY (scope_id, principal_key))"
            )
            conn.execute(
                "CREATE TABLE permission_scopes ("
                "scope_id TEXT PRIMARY KEY, site_id TEXT NOT NULL, "
                "scope_type TEXT NOT NULL, root_path TEXT, "
                "inheriting_count INTEGER NOT NULL DEFAULT 0, "
                "status TEXT NOT NULL DEFAULT 'active', "
                "first_seen_run_id TEXT NOT NULL, last_seen_run_id TEXT NOT NULL)"
            )
            conn.execute("PRAGMA user_version = 1")
            result = init_schema(conn)
            self.assertEqual(result["schema_version"], SCHEMA_VERSION)
            self.assertEqual(result["migrated_from"], 1)
            columns = {row[1] for row in conn.execute("PRAGMA table_info(role_assignments)")}
            self.assertIn("permission_id", columns)
            scope_columns = {row[1] for row in conn.execute("PRAGMA table_info(permission_scopes)")}
            self.assertIn("graph_drive_id", scope_columns)
            self.assertIn("graph_item_id", scope_columns)
            # pre-existing data survives
            conn.execute(
                "INSERT INTO role_assignments(scope_id, principal_key, roles, "
                "first_seen_run_id, last_seen_run_id) VALUES ('s1', 'user:x@y.com', 'read', 'r1', 'r1')"
            )
            row = conn.execute(
                "SELECT permission_id FROM role_assignments WHERE scope_id = 's1'"
            ).fetchone()
            self.assertIsNone(row["permission_id"])
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
