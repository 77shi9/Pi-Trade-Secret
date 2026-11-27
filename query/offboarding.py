"""M2 — email -> complete grant inventory (offboarding report source).

Reads ONLY the SQLite baseline produced by `cli.py scan` — no API calls.

Sections:
  direct_grants            role assignments granted to the user personally
  site_group_memberships   SharePoint site groups containing the user
  sharing_links            links where the user is a recipient or the owner
  m365_group_memberships   Microsoft 365 groups containing the user (if any)
  via_group_access         access derived through group memberships (context)

Remediation hints preview the M3 actions; system-managed groups
(Limited Access / SharingLinks.*) are flagged and never suggested for removal.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any


def _is_system_group(group_name: str) -> bool:
    name = str(group_name or "")
    return name.startswith("Limited Access") or name.startswith("SharingLinks.")


def query_grants(conn: sqlite3.Connection, email: str) -> dict:
    email = str(email or "").strip().lower()
    principal_key = f"user:{email}"

    direct = [
        dict(row) for row in conn.execute(
            "SELECT ps.scope_id, ps.scope_type, ps.root_path, ra.roles, "
            "ra.permission_id, ra.principal_id, p.principal_type, "
            "p.email AS principal_email, p.display_name, p.login_name "
            "FROM role_assignments ra "
            "JOIN permission_scopes ps ON ps.scope_id = ra.scope_id "
            "LEFT JOIN principals p ON p.principal_key = ra.principal_key "
            "WHERE ra.principal_key = ? "
            "ORDER BY ps.root_path",
            (principal_key,),
        )
    ]

    memberships = [
        dict(row) for row in conn.execute(
            "SELECT sg.group_id, sg.group_name, sg.is_default_group, m.member_login "
            "FROM site_group_members m "
            "JOIN site_groups sg ON sg.site_id = m.site_id AND sg.group_id = m.group_id "
            "WHERE m.member_key = ? OR m.member_email = ? "
            "ORDER BY sg.group_id",
            (principal_key, email),
        )
    ]
    for row in memberships:
        row["is_system"] = _is_system_group(row["group_name"])

    link_rows = conn.execute(
        "SELECT ps.scope_type, ps.root_path, sl.link_id, sl.link_type, sl.link_scope, "
        "sl.web_url, sl.recipients_json, sl.recipient_count, sl.owner_email "
        "FROM sharing_links sl "
        "JOIN permission_scopes ps ON ps.scope_id = sl.scope_id "
        "WHERE sl.owner_email = ? OR sl.recipients_json LIKE ? "
        "ORDER BY ps.root_path",
        (email, f"%{email}%"),
    ).fetchall()
    links = []
    for row in link_rows:
        recipients = json.loads(row["recipients_json"] or "[]")
        is_recipient = any(
            isinstance(r, dict) and isinstance(r.get("user"), dict)
            and str(r["user"].get("email", "")).strip().lower() == email
            for r in recipients
        )
        is_owner = str(row["owner_email"] or "").strip().lower() == email
        if not (is_recipient or is_owner):
            continue  # LIKE matched a substring only; verify precisely
        links.append({
            "scope_type": row["scope_type"],
            "root_path": row["root_path"],
            "link_id": row["link_id"],
            "link_type": row["link_type"],
            "link_scope": row["link_scope"],
            "web_url": row["web_url"],
            "recipient_count": int(row["recipient_count"] or 0),
            "owner_email": row["owner_email"],
            "is_recipient": is_recipient,
            "is_owner": is_owner,
            "multi_recipient": int(row["recipient_count"] or 0) > 1,
        })

    m365_memberships = [
        dict(row) for row in conn.execute(
            "SELECT group_key, group_name, group_mail "
            "FROM m365_group_members "
            "WHERE member_key = ? OR member_email = ? "
            "ORDER BY group_name",
            (principal_key, email),
        )
    ]

    via_group = [
        dict(row) for row in conn.execute(
            "SELECT DISTINCT sg.group_id, sg.group_name, ps.scope_type, ps.root_path, "
            "ps.inheriting_count, ra.roles "
            "FROM site_group_members m "
            "JOIN site_groups sg ON sg.site_id = m.site_id AND sg.group_id = m.group_id "
            "JOIN role_assignments ra ON ra.principal_key = 'spgroup:' || m.group_id "
            "JOIN permission_scopes ps ON ps.scope_id = ra.scope_id "
            "WHERE m.member_key = ? OR m.member_email = ? "
            "ORDER BY ps.root_path",
            (principal_key, email),
        )
    ]

    return {
        "email": email,
        "principal_key": principal_key,
        "direct_grants": direct,
        "site_group_memberships": memberships,
        "sharing_links": links,
        "m365_group_memberships": m365_memberships,
        "via_group_access": via_group,
    }


def remediation_hints(report: dict) -> list[dict]:
    """Preview of the M3 plan: what a cleanup would do for this user."""
    actions: list[dict] = []
    for grant in report["direct_grants"]:
        actions.append({
            "action": "delete_role_assignment",
            "scope_path": grant["root_path"],
            "scope_type": grant["scope_type"],
            "roles": grant["roles"],
        })
    for member in report["site_group_memberships"]:
        if member["is_system"]:
            actions.append({
                "action": "skip_system_group",
                "group": member["group_name"],
                "note": "系统管理组，不可手动移除",
            })
        else:
            actions.append({
                "action": "remove_site_group_member",
                "group": member["group_name"],
                "group_id": member["group_id"],
            })
    for link in report["sharing_links"]:
        if link["is_recipient"]:
            if link["multi_recipient"]:
                actions.append({
                    "action": "update_sharing_link_recipients",
                    "link": link["web_url"],
                    "scope_path": link["root_path"],
                    "note": "多人链接：仅移除该用户，保留链接",
                })
            else:
                actions.append({
                    "action": "revoke_sharing_link",
                    "link": link["web_url"],
                    "scope_path": link["root_path"],
                    "note": "唯一收件人：整条撤销",
                })
        if link["is_owner"]:
            actions.append({
                "action": "review_link_owner",
                "link": link["web_url"],
                "note": "该用户是链接创建者（人工决策）",
            })
    for member in report["m365_group_memberships"]:
        actions.append({
            "action": "skip_m365_group_manual",
            "group": member["group_name"] or member["group_key"],
            "note": "M365/Entra 组：输出建议，人工执行（已确认边界）",
        })
    return actions


def via_group_summary(report: dict) -> list[dict]:
    """Compact via-group view: (group, role) -> scope count."""
    summary: dict[tuple, dict] = {}
    for row in report["via_group_access"]:
        key = (row["group_name"], row["roles"])
        entry = summary.setdefault(key, {
            "group": row["group_name"], "roles": row["roles"],
            "scope_count": 0, "inheriting_objects": 0,
        })
        entry["scope_count"] += 1
        entry["inheriting_objects"] += int(row["inheriting_count"] or 0)
    return sorted(summary.values(), key=lambda r: -r["scope_count"])
