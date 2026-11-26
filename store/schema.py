"""Versioned SQLite schema for the S3 permission-scope governance store.

Design decisions (see GOALS.md):
- One union table ``objects`` holds every securable discovered in Phase 1
  (site / library / folder / file) with the ``unique_flag`` boundary column.
  object_key: 'web' | 'list:{listGuid}' | 'item:{listGuid}:{itemId}'.
- ``permission_scopes`` rows exist only for unique-permission objects; the
  scope_id equals the scope root's object_key.
- ``role_assignments`` stores the SharePoint principal id needed later for
  ``DELETE .../roleassignments(principalId)`` remediation.
- ``sharing_links`` stores the full recipient list JSON so the remediation
  layer can decide "remove one recipient" vs "revoke the whole link".
- No cross-table foreign keys by design: scan tables follow a
  first_seen / last_seen discipline instead of cascade deletes.
- Schema evolves only additively, driven by ``PRAGMA user_version``.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 1

TABLES: dict[str, str] = {
    "scan_runs": """
        CREATE TABLE IF NOT EXISTS scan_runs (
            run_id TEXT PRIMARY KEY,
            scan_mode TEXT NOT NULL,          -- 'scope_full' | 'verify'
            site_id TEXT NOT NULL,            -- SharePoint web id (GUID)
            site_url TEXT NOT NULL,
            graph_site_id TEXT,
            status TEXT NOT NULL,             -- 'running' | 'success' | 'partial' | 'failed'
            started_at TEXT NOT NULL,
            completed_at TEXT,
            stats_json TEXT NOT NULL DEFAULT '{}',
            errors_json TEXT NOT NULL DEFAULT '[]'
        )
    """,
    "objects": """
        CREATE TABLE IF NOT EXISTS objects (
            object_key TEXT PRIMARY KEY,      -- 'web' | 'list:{guid}' | 'item:{listguid}:{itemid}'
            site_id TEXT NOT NULL,
            list_id TEXT,
            item_id INTEGER,
            object_type TEXT NOT NULL,        -- 'site' | 'library' | 'folder' | 'file'
            path TEXT,                        -- server-relative URL
            name TEXT,
            parent_path TEXT,
            unique_flag INTEGER NOT NULL DEFAULT 0,
            scope_id TEXT,                    -- set when unique_flag = 1 (equals object_key)
            graph_drive_id TEXT,              -- filled for library rows in Phase 2
            first_seen_run_id TEXT NOT NULL,
            last_seen_run_id TEXT NOT NULL
        )
    """,
    "permission_scopes": """
        CREATE TABLE IF NOT EXISTS permission_scopes (
            scope_id TEXT PRIMARY KEY,        -- equals the scope root's object_key
            site_id TEXT NOT NULL,
            scope_type TEXT NOT NULL,         -- 'site' | 'library' | 'folder' | 'file'
            root_path TEXT,
            inheriting_count INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'active',
            first_seen_run_id TEXT NOT NULL,
            last_seen_run_id TEXT NOT NULL
        )
    """,
    "principals": """
        CREATE TABLE IF NOT EXISTS principals (
            principal_key TEXT PRIMARY KEY,   -- 'user:{email}' | 'spgroup:{siteId}:{groupId}' | 'm365group:{guid}' | 'other:{login}'
            principal_type TEXT NOT NULL,     -- 'user' | 'spgroup' | 'm365group' | 'securitygroup' | 'other'
            login_name TEXT,                  -- e.g. i:0#.f|membership|user@tenant
            email TEXT,
            display_name TEXT,
            first_seen_run_id TEXT NOT NULL,
            last_seen_run_id TEXT NOT NULL
        )
    """,
    "role_assignments": """
        CREATE TABLE IF NOT EXISTS role_assignments (
            scope_id TEXT NOT NULL,
            principal_key TEXT NOT NULL,
            principal_id INTEGER,             -- SharePoint principal id (used by DELETE)
            roles TEXT,                       -- 'Full Control;Contribute'
            first_seen_run_id TEXT NOT NULL,
            last_seen_run_id TEXT NOT NULL,
            PRIMARY KEY (scope_id, principal_key)
        )
    """,
    "site_groups": """
        CREATE TABLE IF NOT EXISTS site_groups (
            site_id TEXT NOT NULL,
            group_id INTEGER NOT NULL,        -- SharePoint site group id
            group_name TEXT NOT NULL,
            owner_title TEXT,
            description TEXT,
            is_default_group INTEGER NOT NULL DEFAULT 0,
            first_seen_run_id TEXT NOT NULL,
            last_seen_run_id TEXT NOT NULL,
            PRIMARY KEY (site_id, group_id)
        )
    """,
    "site_group_members": """
        CREATE TABLE IF NOT EXISTS site_group_members (
            site_id TEXT NOT NULL,
            group_id INTEGER NOT NULL,
            member_key TEXT NOT NULL,         -- principals.principal_key
            member_login TEXT,
            member_email TEXT,
            member_name TEXT,
            member_type TEXT,                 -- 'user' | 'spgroup' | 'adgroup'
            first_seen_run_id TEXT NOT NULL,
            last_seen_run_id TEXT NOT NULL,
            PRIMARY KEY (site_id, group_id, member_key)
        )
    """,
    "m365_group_members": """
        CREATE TABLE IF NOT EXISTS m365_group_members (
            group_key TEXT NOT NULL,          -- 'm365group:{guid}'
            group_name TEXT,
            group_mail TEXT,
            member_key TEXT NOT NULL,
            member_email TEXT,
            member_name TEXT,
            first_seen_run_id TEXT NOT NULL,
            last_seen_run_id TEXT NOT NULL,
            PRIMARY KEY (group_key, member_key)
        )
    """,
    "sharing_links": """
        CREATE TABLE IF NOT EXISTS sharing_links (
            scope_id TEXT NOT NULL,
            link_id TEXT NOT NULL,            -- Graph permission id
            drive_id TEXT,
            graph_item_id TEXT,               -- Graph driveItem id (for DELETE/PATCH)
            link_type TEXT,                   -- 'view' | 'edit'
            link_scope TEXT,                  -- 'anonymous' | 'organization' | 'users'
            web_url TEXT,
            web_html TEXT,
            owner_key TEXT,                   -- link creator
            owner_name TEXT,
            owner_email TEXT,
            recipients_json TEXT NOT NULL DEFAULT '[]',  -- full grantedToIdentitiesV2
            recipient_count INTEGER NOT NULL DEFAULT 0,
            has_password INTEGER NOT NULL DEFAULT 0,
            prevents_download INTEGER NOT NULL DEFAULT 0,
            expiration TEXT,
            first_seen_run_id TEXT NOT NULL,
            last_seen_run_id TEXT NOT NULL,
            PRIMARY KEY (scope_id, link_id)
        )
    """,
    "scope_snapshots": """
        CREATE TABLE IF NOT EXISTS scope_snapshots (
            snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            source_run_id TEXT NOT NULL,
            site_id TEXT NOT NULL,
            row_count INTEGER NOT NULL,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        )
    """,
    "scope_snapshot_rows": """
        CREATE TABLE IF NOT EXISTS scope_snapshot_rows (
            snapshot_id INTEGER NOT NULL,
            row_number INTEGER NOT NULL,
            scope_id TEXT,
            object_path TEXT,
            grant_kind TEXT,                  -- 'role_assignment' | 'site_group' | 'sharing_link' | 'm365_group'
            principal_key TEXT,
            principal_type TEXT,
            principal_email TEXT,
            roles TEXT,
            link_scope TEXT,
            detail_json TEXT,
            PRIMARY KEY (snapshot_id, row_number)
        )
    """,
    "audit_log": """
        CREATE TABLE IF NOT EXISTS audit_log (
            action_id INTEGER PRIMARY KEY AUTOINCREMENT,
            operation_id TEXT NOT NULL,       -- one id per apply run
            acted_at TEXT NOT NULL,
            target_email TEXT NOT NULL,
            action_type TEXT NOT NULL,        -- 'remove_site_group_member' | 'delete_role_assignment' | 'revoke_sharing_link' | 'update_sharing_link_recipients' | 'skip_manual'
            dry_run INTEGER NOT NULL DEFAULT 1,
            scope_id TEXT,
            object_path TEXT,
            principal_key TEXT,
            link_id TEXT,
            http_method TEXT,
            url TEXT,
            request_json TEXT,
            response_status INTEGER,
            response_excerpt TEXT,
            result TEXT NOT NULL,             -- 'ok' | 'failed' | 'skipped_manual' | 'skipped_protected'
            error TEXT
        )
    """,
}

INDEXES: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS idx_objects_site_type ON objects(site_id, object_type)",
    "CREATE INDEX IF NOT EXISTS idx_objects_unique ON objects(unique_flag)",
    "CREATE INDEX IF NOT EXISTS idx_objects_path ON objects(path)",
    "CREATE INDEX IF NOT EXISTS idx_objects_scope ON objects(scope_id)",
    "CREATE INDEX IF NOT EXISTS idx_scopes_site ON permission_scopes(site_id)",
    "CREATE INDEX IF NOT EXISTS idx_ra_principal ON role_assignments(principal_key)",
    "CREATE INDEX IF NOT EXISTS idx_ra_scope ON role_assignments(scope_id)",
    "CREATE INDEX IF NOT EXISTS idx_sgm_member ON site_group_members(member_email)",
    "CREATE INDEX IF NOT EXISTS idx_links_scope ON sharing_links(scope_id)",
    "CREATE INDEX IF NOT EXISTS idx_links_owner ON sharing_links(owner_key)",
    "CREATE INDEX IF NOT EXISTS idx_principals_email ON principals(email)",
    "CREATE INDEX IF NOT EXISTS idx_audit_target ON audit_log(target_email, operation_id)",
    "CREATE INDEX IF NOT EXISTS idx_snapshots_source ON scope_snapshots(source_run_id)",
)

TABLE_NAMES = tuple(TABLES)


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Open (and create) the governance database with safe pragmas."""
    path = str(db_path)
    if path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_schema(conn: sqlite3.Connection) -> dict:
    """Create all tables/indexes on a fresh database; idempotent.

    Future versions must only append migrations additively (never rewrite an
    existing table in place) and bump SCHEMA_VERSION.
    """
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    if current >= SCHEMA_VERSION:
        return {"schema_version": current, "already_initialized": True}
    for statement in TABLES.values():
        conn.execute(statement)
    for statement in INDEXES:
        conn.execute(statement)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.commit()
    return {"schema_version": SCHEMA_VERSION, "already_initialized": False}


def schema_status(conn: sqlite3.Connection) -> dict:
    """Read-only schema inventory (tables + row counts + user_version)."""
    tables = {}
    for name in TABLE_NAMES:
        tables[name] = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
    return {
        "schema_version": conn.execute("PRAGMA user_version").fetchone()[0],
        "tables": tables,
    }
