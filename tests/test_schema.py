import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from store.schema import SCHEMA_VERSION, TABLE_NAMES, connect, init_schema, schema_status


class SchemaTest(unittest.TestCase):
    def test_init_creates_all_tables_and_version(self):
        conn = connect(":memory:")
        try:
            result = init_schema(conn)
            self.assertFalse(result["already_initialized"])
            self.assertEqual(result["schema_version"], SCHEMA_VERSION)
            present = {
                row[0]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            for name in TABLE_NAMES:
                self.assertIn(name, present)
            self.assertEqual(
                conn.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION
            )
        finally:
            conn.close()

    def test_init_is_idempotent(self):
        conn = connect(":memory:")
        try:
            init_schema(conn)
            second = init_schema(conn)
            self.assertTrue(second["already_initialized"])
            self.assertEqual(second["schema_version"], SCHEMA_VERSION)
        finally:
            conn.close()

    def test_scope_rows_round_trip(self):
        conn = connect(":memory:")
        try:
            init_schema(conn)
            conn.execute(
                "INSERT INTO scan_runs(run_id, scan_mode, site_id, site_url, status, started_at) "
                "VALUES ('r1', 'scope_full', 'site1', 'https://x', 'success', '2026-11-26T00:00:00Z')"
            )
            conn.execute(
                "INSERT INTO objects(object_key, site_id, object_type, path, name, unique_flag, "
                "first_seen_run_id, last_seen_run_id) "
                "VALUES ('item:l1:3', 'site1', 'file', '/sites/s/lib/f.docx', 'f.docx', 1, 'r1', 'r1')"
            )
            conn.execute(
                "INSERT INTO permission_scopes(scope_id, site_id, scope_type, root_path, "
                "first_seen_run_id, last_seen_run_id) "
                "VALUES ('item:l1:3', 'site1', 'file', '/sites/s/lib/f.docx', 'r1', 'r1')"
            )
            conn.execute(
                "INSERT INTO role_assignments(scope_id, principal_key, principal_id, roles, "
                "first_seen_run_id, last_seen_run_id) "
                "VALUES ('item:l1:3', 'user:a@x.com', 7, 'Full Control', 'r1', 'r1')"
            )
            row = conn.execute(
                "SELECT roles, principal_id FROM role_assignments WHERE principal_key = 'user:a@x.com'"
            ).fetchone()
            self.assertEqual(row["roles"], "Full Control")
            self.assertEqual(row["principal_id"], 7)
            counts = schema_status(conn)["tables"]
            self.assertEqual(counts["objects"], 1)
            self.assertEqual(counts["permission_scopes"], 1)
        finally:
            conn.close()

    def test_indexes_created(self):
        conn = connect(":memory:")
        try:
            init_schema(conn)
            indexes = {
                row[0]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
            }
            self.assertIn("idx_objects_unique", indexes)
            self.assertIn("idx_ra_principal", indexes)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
