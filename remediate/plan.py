"""M3 — plan: email -> executable remediation operation list (dry-run source).

Pure database work, no API calls. Every operation carries the concrete ids the
apply step needs:

  delete_role_assignment
      method 'graph' : graph_drive_id + graph_item_id (or library root) +
                       permission_id  -> Graph DELETE /permissions/{id}
      method 'rest'  : REST DELETE roleassignments(principalId) — site scope
                       or principal_id available (SP groups)
      method 'manual': neither available
  remove_site_group_member   REST POST removebyloginname (group_id + login)
  update_sharing_link_recipients  Graph PATCH recipients minus the target user
  revoke_sharing_link        Graph DELETE (single-recipient link)
  skip_*                     informational (system groups, M365 groups, owner)
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote, urlsplit

from query.offboarding import query_grants

LINK_ROLE = {"view": "read", "edit": "write"}


def _host_root(site_url: str) -> str:
    parts = urlsplit(site_url)
    return f"{parts.scheme}://{parts.netloc}"


def _ui_links(site_url: str, scope: dict, object_ids: dict) -> dict:
    """Clickable browser pages for manual execution of each operation.

    Even without any write consent, the site owner can perform every action
    in the browser; these links land directly on the right page.
    """
    links: dict[str, str] = {}
    if not site_url:
        return links
    site_url = site_url.rstrip("/")
    root_path = scope.get("root_path")
    list_id = object_ids.get("list_id")
    item_id = object_ids.get("item_id")
    if root_path:
        links["item_url"] = _host_root(site_url) + quote(str(root_path), safe="/")
    if item_id and list_id:
        encoded_list = quote("{" + str(list_id) + "}", safe="")
        links["permission_page"] = (
            f"{site_url}/_layouts/15/user.aspx?"
            f"obj={encoded_list},{item_id},LISTITEM&List={encoded_list}"
        )
    elif list_id:
        encoded_list = quote("{" + str(list_id) + "}", safe="")
        links["permission_page"] = (
            f"{site_url}/_layouts/15/user.aspx?"
            f"obj={encoded_list},LIST&List={encoded_list}"
        )
    else:  # site scope
        links["permission_page"] = f"{site_url}/_layouts/15/user.aspx"
    return links


def _scope_graph_identity(conn: sqlite3.Connection, scope_id: str) -> dict:
    row = conn.execute(
        "SELECT scope_type, root_path, graph_drive_id, graph_item_id "
        "FROM permission_scopes WHERE scope_id = ?",
        (scope_id,),
    ).fetchone()
    if row is None:
        return {"scope_type": None, "root_path": None, "graph_drive_id": None,
                "graph_item_id": None}
    return dict(row)


def _object_ids(conn: sqlite3.Connection, scope_id: str) -> dict:
    row = conn.execute(
        "SELECT site_id, list_id, item_id FROM objects WHERE object_key = ?",
        (scope_id,),
    ).fetchone()
    if row is None:
        return {"site_id": None, "list_id": None, "item_id": None}
    return dict(row)


def build_plan(conn: sqlite3.Connection, email: str,
               *, operation_id: str | None = None) -> dict:
    """Build the full remediation plan for one user from the scan baseline."""
    email = str(email or "").strip().lower()
    report = query_grants(conn, email)
    operations: list[dict[str, Any]] = []
    site_row = conn.execute(
        "SELECT site_url FROM scan_runs ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    site_url = (site_row["site_url"] if site_row else "") or ""

    # -- direct grants ------------------------------------------------------
    for grant in report["direct_grants"]:
        scope_id = grant["scope_id"]
        scope = _scope_graph_identity(conn, scope_id)
        object_ids = _object_ids(conn, scope_id)
        drive = scope.get("graph_drive_id")
        item = scope.get("graph_item_id")
        permission_id = grant.get("permission_id")
        if drive and permission_id and (item or scope.get("scope_type") == "library"):
            method = "graph"
        elif scope.get("scope_type") == "site" or grant.get("principal_id"):
            method = "rest"
        else:
            method = "manual"
        operations.append({
            "op": "delete_role_assignment",
            "method": method,
            "principal_key": report["principal_key"],
            "principal_email": email,
            "principal_id": grant.get("principal_id"),
            "roles": grant["roles"],
            "scope_id": scope_id,
            "scope_type": scope.get("scope_type"),
            "path": scope.get("root_path"),
            "site_id": object_ids.get("site_id"),
            "list_id": object_ids.get("list_id"),
            "item_id": object_ids.get("item_id"),
            "graph_drive_id": drive,
            "graph_item_id": item,
            "graph_permission_id": permission_id,
            "ui_links": _ui_links(site_url, scope, object_ids),
        })

    # -- site group memberships ----------------------------------------------
    for member in report["site_group_memberships"]:
        if member["is_system"]:
            operations.append({
                "op": "skip_system_group",
                "group": member["group_name"],
                "group_id": member["group_id"],
                "note": "系统管理组，不可手动移除",
            })
            continue
        login_row = conn.execute(
            "SELECT member_login, member_email FROM site_group_members "
            "WHERE group_id = ? AND (member_key = ? OR member_email = ?)",
            (member["group_id"], report["principal_key"], email),
        ).fetchone()
        operations.append({
            "op": "remove_site_group_member",
            "method": "rest",
            "group": member["group_name"],
            "group_id": member["group_id"],
            "member_login": login_row["member_login"] if login_row else None,
            "member_email": email,
            "ui_links": {
                "group_page": (f"{site_url.rstrip('/')}/_layouts/15/people.aspx"
                                f"?MembershipGroupId={member['group_id']}"),
            },
        })

    # -- sharing links ----------------------------------------------------------
    for link in report["sharing_links"]:
        link_row = conn.execute(
            "SELECT drive_id, graph_item_id, recipients_json, link_type "
            "FROM sharing_links WHERE link_id = ?",
            (link["link_id"],),
        ).fetchone()
        drive = link_row["drive_id"] if link_row else None
        item = link_row["graph_item_id"] if link_row else None
        recipients = json.loads(link_row["recipients_json"]) if link_row else []
        if link["is_recipient"]:
            remaining = [
                r for r in recipients
                if not (isinstance(r, dict) and isinstance(r.get("user"), dict)
                        and str(r["user"].get("email", "")).strip().lower() == email)
            ]
            if link["multi_recipient"] and drive and item:
                operations.append({
                    "op": "update_sharing_link_recipients",
                    "method": "graph",
                    "link_id": link["link_id"],
                    "path": link["root_path"],
                    "graph_drive_id": drive,
                    "graph_item_id": item,
                    "roles": [LINK_ROLE.get(link_row["link_type"] if link_row else "view",
                                            "read")],
                    "remaining_recipients": [
                        {"email": r["user"]["email"]} for r in remaining
                        if isinstance(r, dict) and isinstance(r.get("user"), dict)
                        and r["user"].get("email")
                    ],
                    "removed_recipient": email,
                    "ui_links": _ui_links(site_url, {"root_path": link["root_path"]},
                                          {}),
                })
            elif drive and item:
                operations.append({
                    "op": "revoke_sharing_link",
                    "method": "graph",
                    "link_id": link["link_id"],
                    "path": link["root_path"],
                    "graph_drive_id": drive,
                    "graph_item_id": item,
                    "note": "唯一收件人：整条撤销",
                    "ui_links": _ui_links(site_url, {"root_path": link["root_path"]},
                                          {}),
                })
            else:
                operations.append({
                    "op": "revoke_sharing_link",
                    "method": "manual",
                    "link_id": link["link_id"],
                    "path": link["root_path"],
                    "note": "缺少 Graph 标识，人工处理",
                })
        if link["is_owner"]:
            operations.append({
                "op": "review_link_owner",
                "link": link["web_url"],
                "note": "该用户是链接创建者（人工决策）",
            })

    # -- M365 groups (confirmed boundary: suggestions only) ----------------------
    for member in report["m365_group_memberships"]:
        operations.append({
            "op": "skip_m365_group_manual",
            "group": member["group_name"] or member["group_key"],
            "note": "M365/Entra 组：建议人工执行",
        })

    last_run = conn.execute(
        "SELECT run_id FROM scan_runs WHERE status IN ('success', 'partial') "
        "ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    counts: dict[str, int] = {}
    for op in operations:
        counts[op["op"]] = counts.get(op["op"], 0) + 1
    return {
        "operation_id": operation_id or (
            datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
            + "_" + uuid.uuid4().hex[:6]
        ),
        "target_email": email,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_run_id": last_run["run_id"] if last_run else None,
        "site_url": site_url,
        "operations": operations,
        "summary": {
            "total": len(operations),
            "by_op": counts,
            "executable": sum(
                1 for op in operations
                if op.get("method") in ("graph", "rest")
            ),
            "with_ui_links": sum(
                1 for op in operations if op.get("ui_links")
            ),
        },
    }
