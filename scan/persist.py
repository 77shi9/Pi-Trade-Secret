"""Persistence for the M1 scanner: upserts into the permission-scope schema.

Upsert discipline: ``first_seen_run_id`` is preserved on conflict; only the
mutable columns and ``last_seen_run_id`` are updated. Nothing is deleted; a
later verification scan (M3) compares runs by ``last_seen``.
"""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from typing import Any, Mapping

from core.parse import server_relative_path

_OBJECT_UPSERT = """
INSERT INTO objects(object_key, site_id, list_id, item_id, object_type, path, name,
                    parent_path, unique_flag, scope_id, graph_drive_id,
                    first_seen_run_id, last_seen_run_id)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(object_key) DO UPDATE SET
    path = excluded.path,
    name = excluded.name,
    parent_path = excluded.parent_path,
    unique_flag = excluded.unique_flag,
    scope_id = excluded.scope_id,
    graph_drive_id = excluded.graph_drive_id,
    last_seen_run_id = excluded.last_seen_run_id
"""

_SCOPE_UPSERT = """
INSERT INTO permission_scopes(scope_id, site_id, scope_type, root_path,
                              inheriting_count, status,
                              first_seen_run_id, last_seen_run_id)
VALUES (?, ?, ?, ?, 0, 'active', ?, ?)
ON CONFLICT(scope_id) DO UPDATE SET
    root_path = excluded.root_path,
    status = 'active',
    last_seen_run_id = excluded.last_seen_run_id
"""

_PRINCIPAL_UPSERT = """
INSERT INTO principals(principal_key, principal_type, login_name, email, display_name,
                       first_seen_run_id, last_seen_run_id)
VALUES (?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(principal_key) DO UPDATE SET
    login_name = COALESCE(excluded.login_name, principals.login_name),
    email = COALESCE(excluded.email, principals.email),
    display_name = COALESCE(excluded.display_name, principals.display_name),
    last_seen_run_id = excluded.last_seen_run_id
"""

_ROLE_ASSIGNMENT_UPSERT = """
INSERT INTO role_assignments(scope_id, principal_key, principal_id, roles, permission_id,
                             first_seen_run_id, last_seen_run_id)
VALUES (?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(scope_id, principal_key) DO UPDATE SET
    principal_id = excluded.principal_id,
    roles = excluded.roles,
    permission_id = excluded.permission_id,
    last_seen_run_id = excluded.last_seen_run_id
"""

_LINK_UPSERT = """
INSERT INTO sharing_links(scope_id, link_id, drive_id, graph_item_id, link_type, link_scope,
                          web_url, web_html, owner_key, owner_name, owner_email,
                          recipients_json, recipient_count, has_password, prevents_download,
                          expiration, first_seen_run_id, last_seen_run_id)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(scope_id, link_id) DO UPDATE SET
    drive_id = excluded.drive_id,
    graph_item_id = excluded.graph_item_id,
    link_type = excluded.link_type,
    link_scope = excluded.link_scope,
    web_url = excluded.web_url,
    web_html = excluded.web_html,
    owner_key = excluded.owner_key,
    owner_name = excluded.owner_name,
    owner_email = excluded.owner_email,
    recipients_json = excluded.recipients_json,
    recipient_count = excluded.recipient_count,
    has_password = excluded.has_password,
    prevents_download = excluded.prevents_download,
    expiration = excluded.expiration,
    last_seen_run_id = excluded.last_seen_run_id
"""

_SITE_GROUP_UPSERT = """
INSERT INTO site_groups(site_id, group_id, group_name, owner_title, description,
                        is_default_group, first_seen_run_id, last_seen_run_id)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(site_id, group_id) DO UPDATE SET
    group_name = excluded.group_name,
    description = excluded.description,
    last_seen_run_id = excluded.last_seen_run_id
"""

_MEMBER_UPSERT = """
INSERT INTO site_group_members(site_id, group_id, member_key, member_login, member_email,
                               member_name, member_type, first_seen_run_id, last_seen_run_id)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(site_id, group_id, member_key) DO UPDATE SET
    member_login = excluded.member_login,
    member_email = COALESCE(excluded.member_email, site_group_members.member_email),
    member_name = excluded.member_name,
    member_type = excluded.member_type,
    last_seen_run_id = excluded.last_seen_run_id
"""


class RunWriter:
    """Writes one scan run into the governance database."""

    def __init__(self, conn: sqlite3.Connection, run_id: str, scan_mode: str,
                 site_id: str, site_url: str, graph_site_id: str | None) -> None:
        self.conn = conn
        self.run_id = run_id
        self.scan_mode = scan_mode
        self.site_id = site_id
        self.site_url = site_url
        self.graph_site_id = graph_site_id

    # -- run lifecycle -----------------------------------------------------------

    def start(self, started_at: str) -> None:
        self.conn.execute(
            "INSERT INTO scan_runs(run_id, scan_mode, site_id, site_url, graph_site_id, "
            "status, started_at) VALUES (?, ?, ?, ?, ?, 'running', ?)",
            (self.run_id, self.scan_mode, self.site_id, self.site_url,
             self.graph_site_id, started_at),
        )
        self.conn.commit()

    def finalize(self, stats: Mapping[str, Any], errors: list[dict],
                 status: str = "success", completed_at: str = "") -> None:
        self.conn.execute(
            "UPDATE scan_runs SET status = ?, completed_at = ?, stats_json = ?, "
            "errors_json = ? WHERE run_id = ?",
            (status, completed_at, json.dumps(stats, ensure_ascii=False),
             json.dumps(errors, ensure_ascii=False), self.run_id),
        )
        self._recompute_inheriting_counts()
        self.conn.commit()

    # -- phase 1 ------------------------------------------------------------------

    def write_site(self, web: Mapping[str, Any]) -> None:
        path = str(web.get("ServerRelativeUrl") or "")
        unique = 1 if web.get("unique") else 0
        self.conn.execute(_OBJECT_UPSERT, (
            "web", self.site_id, None, None, "site", path,
            str(web.get("Title") or ""), None, unique, "web" if unique else None,
            None, self.run_id, self.run_id,
        ))
        if unique:
            self.conn.execute(_SCOPE_UPSERT, ("web", self.site_id, "site", path,
                                              self.run_id, self.run_id))

    def write_library(self, library: Mapping[str, Any]) -> None:
        object_key = f"list:{library['list_guid']}"
        unique = 1 if library["unique_flag"] else 0
        self.conn.execute(_OBJECT_UPSERT, (
            object_key, self.site_id, library["list_guid"], None, "library",
            library["root_path"], library["title"], None, unique,
            object_key if unique else None, library["drive_id"],
            self.run_id, self.run_id,
        ))
        if unique:
            self.conn.execute(_SCOPE_UPSERT, (
                object_key, self.site_id, "library", library["root_path"],
                self.run_id, self.run_id,
            ))

    def write_items(self, list_guid: str, items: list[dict]) -> None:
        rows = []
        for item in items:
            object_key = f"item:{list_guid}:{item['item_id']}"
            path = item["path"]
            parent = path.rsplit("/", 1)[0] if "/" in path else None
            unique = 1 if item["unique_flag"] else 0
            rows.append((
                object_key, self.site_id, list_guid, item["item_id"],
                item["object_type"], path, item["name"], parent, unique,
                object_key if unique else None, None, self.run_id, self.run_id,
            ))
        self.conn.executemany(_OBJECT_UPSERT, rows)
        scope_rows = [
            (f"item:{list_guid}:{item['item_id']}", self.site_id,
             item["object_type"], item["path"], self.run_id, self.run_id)
            for item in items if item["unique_flag"]
        ]
        if scope_rows:
            self.conn.executemany(_SCOPE_UPSERT, scope_rows)

    def set_scope_graph_ids(self, updates: list[tuple[str, str | None, str | None]]) -> None:
        """Phase 2: record each unique scope's Graph identity.

        (scope_id, graph_drive_id, graph_item_id). Library scopes use the
        root address (graph_item_id stays NULL); site scopes have neither.
        """
        for scope_id, drive_id, item_id in updates:
            self.conn.execute(
                "UPDATE permission_scopes SET graph_drive_id = ?, graph_item_id = ? "
                "WHERE scope_id = ?",
                (drive_id, item_id, scope_id),
            )

    def write_groups(self, groups: list[dict]) -> None:
        for group in groups:
            title = str(group["title"])
            is_default = 1 if title.endswith(("Owners", "Members", "Visitors")) else 0
            self.conn.execute(_SITE_GROUP_UPSERT, (
                self.site_id, group["group_id"], title, None,
                group.get("description"), is_default, self.run_id, self.run_id,
            ))
            member_rows = []
            for member in group["members"]:
                if not member.get("key"):
                    continue
                member_rows.append((
                    self.site_id, group["group_id"], member["key"],
                    member.get("login"), member.get("email"),
                    member.get("name"), member.get("type"),
                    self.run_id, self.run_id,
                ))
                self._write_principal(member)
            if member_rows:
                self.conn.executemany(_MEMBER_UPSERT, member_rows)

    # -- phase 2 -------------------------------------------------------------------

    def write_grant(self, scope_id: str, parsed: Mapping[str, Any]) -> None:
        principal = parsed.get("principal")
        if not principal or not principal.get("key"):
            principal_key = f"other:perm:{parsed.get('permission_id')}"
            self._write_principal({"key": principal_key, "type": "other",
                                   "login": None, "email": None, "name": None})
            principal_id = None
        else:
            self._write_principal(principal)
            principal_key = principal["key"]
            raw_id = principal.get("id")
            principal_id = int(raw_id) if str(raw_id).isdigit() else None
        self.conn.execute(_ROLE_ASSIGNMENT_UPSERT, (
            scope_id, principal_key, principal_id, parsed.get("roles") or "",
            parsed.get("permission_id"),
            self.run_id, self.run_id,
        ))

    def write_link(self, scope_id: str, link: Mapping[str, Any],
                   drive_id: str | None, graph_item_id: str | None,
                   parsed: Mapping[str, Any]) -> None:
        owner = link.get("owner")
        if isinstance(owner, dict) and owner.get("key"):
            self._write_principal(owner)
        self.conn.execute(_LINK_UPSERT, (
            scope_id, link["link_id"], drive_id, graph_item_id,
            link.get("link_type"), link.get("link_scope"),
            link.get("web_url"), link.get("web_html"),
            (owner or {}).get("key"), (owner or {}).get("name"),
            (owner or {}).get("email"),
            json.dumps(link.get("recipients") or [], ensure_ascii=False),
            int(link.get("recipient_count") or 0),
            1 if parsed.get("has_password") else 0,
            1 if link.get("prevents_download") else 0,
            parsed.get("expiration"),
            self.run_id, self.run_id,
        ))

    # -- internals -------------------------------------------------------------------

    def _write_principal(self, principal: Mapping[str, Any]) -> None:
        if not principal.get("key"):
            return
        self.conn.execute(_PRINCIPAL_UPSERT, (
            principal["key"], principal.get("type"), principal.get("login"),
            principal.get("email"), principal.get("name"),
            self.run_id, self.run_id,
        ))

    def _recompute_inheriting_counts(self) -> None:
        """Count, per unique scope, the objects whose nearest unique ancestor it is."""
        objects = self.conn.execute(
            "SELECT object_key, path, unique_flag FROM objects WHERE site_id = ?",
            (self.site_id,),
        ).fetchall()
        by_path = {row["path"]: row for row in objects if row["path"]}
        counts: dict[str, int] = defaultdict(int)
        for row in objects:
            if row["unique_flag"] or not row["path"]:
                continue
            path = row["path"]
            for _ in range(100):  # hop guard
                parent = path.rsplit("/", 1)[0] if "/" in path else None
                if not parent:
                    break
                parent_row = by_path.get(parent)
                if parent_row is None:
                    break
                if parent_row["unique_flag"]:
                    counts[parent_row["object_key"]] += 1
                    break
                path = parent
        self.conn.execute(
            "UPDATE permission_scopes SET inheriting_count = 0 WHERE site_id = ?",
            (self.site_id,),
        )
        for scope_id, count in counts.items():
            self.conn.execute(
                "UPDATE permission_scopes SET inheriting_count = ? WHERE scope_id = ?",
                (count, scope_id),
            )
