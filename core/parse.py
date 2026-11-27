"""Parsing helpers for SharePoint REST (minimalmetadata) and Graph responses.

Shared by the M1 scanner (discovery / expansion / persistence) and by tests.
The m0/m0b probe scripts keep their own copies; production code imports here.
"""

from __future__ import annotations

from typing import Any, Mapping
from urllib.parse import unquote, urlsplit

ROLE_LABELS = {
    "owner": "Full Control",
    "write": "Contribute",
    "read": "Read",
    "sp.web设计的": "Design",
}


def entries(body: Any) -> list[Any]:
    """List entries from a paged Graph / SharePoint REST collection body."""
    if isinstance(body, Mapping):
        value = body.get("value")
        if isinstance(value, list):
            return value
        nested = body.get("d")
        if isinstance(nested, Mapping):
            results = nested.get("results")
            if isinstance(results, list):
                return results
    return []


def entity(body: Any) -> Mapping[str, Any]:
    """Single entity from verbose ({"d": {...}}) or minimalmetadata (flat) body."""
    if isinstance(body, Mapping):
        nested = body.get("d")
        if isinstance(nested, Mapping):
            return nested
    return body if isinstance(body, Mapping) else {}


def first_entry(body: Any) -> Mapping[str, Any] | None:
    for entry in entries(body):
        if isinstance(entry, Mapping):
            return entry
    return None


def truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes")
    return False


def join_roles(roles: Any) -> str:
    if isinstance(roles, list):
        return ";".join(str(r) for r in roles if r)
    return str(roles or "")


def role_labels(roles: Any) -> str:
    return ";".join(ROLE_LABELS.get(str(r), str(r)) for r in (roles or []) if r) if isinstance(roles, list) else ""


def server_relative_path(url: str) -> str:
    """Server-relative, URL-decoded path of a full web URL."""
    try:
        return unquote(urlsplit(str(url)).path)
    except Exception:
        return str(url or "")


def user_key(email: str | None, ident: str | int | None) -> str | None:
    if email and "@" in str(email):
        return f"user:{str(email).strip().lower()}"
    if ident:
        return f"user:id:{str(ident).lower()}"
    return None


# ---------------------------------------------------------------------------
# Permission parsing (Graph driveItem permissions)
# ---------------------------------------------------------------------------

def _principal_from_identity_set(identity: Mapping[str, Any]) -> dict | None:
    """One Graph identity set -> normalized principal dict (or None)."""
    user = identity.get("user")
    if isinstance(user, Mapping):
        return {
            "key": user_key(user.get("email"), user.get("id")),
            "type": "user",
            "id": user.get("id"),
            "email": (user.get("email") or "").strip() or None,
            "login": user.get("loginName"),
            "name": user.get("displayName"),
        }
    site_user = identity.get("siteUser")
    if isinstance(site_user, Mapping):
        login = str(site_user.get("loginName") or "")
        email = (site_user.get("email") or "").strip() or None
        key = user_key(email, None) or (f"user:{login.split('|')[-1].lower()}" if "|" in login else None)
        return {"key": key, "type": "user", "id": site_user.get("id"), "email": email,
                "login": login or None, "name": site_user.get("displayName")}
    group = identity.get("group")
    if isinstance(group, Mapping):
        return {"key": f"m365group:{group.get('id')}", "type": "m365group",
                "id": group.get("id"), "email": group.get("email"), "name": group.get("displayName")}
    sp_group = identity.get("sharePointGroup")
    if isinstance(sp_group, Mapping):
        gid = sp_group.get("principalId") or sp_group.get("id")
        return {"key": f"spgroup:{gid}", "type": "spgroup", "id": gid,
                "email": None, "login": None, "name": sp_group.get("title")}
    site_group = identity.get("siteGroup")
    if isinstance(site_group, Mapping):
        gid = site_group.get("id")
        return {"key": f"spgroup:{gid}", "type": "spgroup", "id": gid,
                "email": None, "login": site_group.get("loginName"),
                "name": site_group.get("displayName")}
    app = identity.get("application")
    if isinstance(app, Mapping):
        return {"key": f"app:{app.get('id')}", "type": "app",
                "id": app.get("id"), "email": None, "name": app.get("displayName")}
    return None


def _principal_from_grant(permission: Mapping[str, Any]) -> dict | None:
    granted_v2 = permission.get("grantedToV2")
    if isinstance(granted_v2, Mapping):
        principal = _principal_from_identity_set(granted_v2)
        if principal and principal.get("key"):
            return principal
    legacy = permission.get("grantedTo")
    if isinstance(legacy, Mapping):
        principal = _principal_from_identity_set(legacy)
        if principal and principal.get("key"):
            return principal
    return None


def parse_permission(permission: Mapping[str, Any]) -> dict:
    """One Graph driveItem permission -> normalized grant/link description.

    Returns a dict with:
      permission_id, roles (joined raw), roles_label, inherited (bool),
      principal (dict | None), link (dict | None), owner (dict | None)
    """
    permission_id = str(permission.get("id") or "unknown")
    roles = permission.get("roles") or []
    inherited = isinstance(permission.get("inheritedFrom"), Mapping)

    principal = _principal_from_grant(permission)
    if principal is None:
        # link-only permissions have no grantedTo; keep the principal empty
        principal = None

    link_obj = permission.get("link")
    link = None
    if isinstance(link_obj, Mapping):
        recipients = permission.get("grantedToIdentitiesV2")
        if not isinstance(recipients, list):
            recipients = []
        granted_by = permission.get("grantedBy")
        owner = None
        if isinstance(granted_by, Mapping):
            owner = _principal_from_identity_set(granted_by)
        link = {
            "link_id": permission_id,
            "link_type": link_obj.get("type"),
            "link_scope": link_obj.get("scope"),
            "web_url": link_obj.get("webUrl"),
            "web_html": link_obj.get("webHtml"),
            "prevents_download": truthy(link_obj.get("preventsDownload")),
            "recipients": recipients,
            "recipient_count": len(recipients),
            "owner": owner,
        }

    return {
        "permission_id": permission_id,
        "roles": join_roles(roles),
        "roles_label": role_labels(roles),
        "inherited": inherited,
        "principal": principal,
        "link": link,
        "has_password": truthy(permission.get("hasPassword")),
        "expiration": permission.get("expirationDateTime"),
    }


def member_principal(login: str | None, email: str | None, name: str | None) -> dict:
    """Normalize a SharePoint site-group member row into a principal."""
    login = str(login or "")
    email = str(email or "").strip()
    if login.startswith("i:0#.f|membership|"):
        suffix = login.split("|")[-1].strip().lower()
        addr = (email or suffix).lower()
        return {"key": f"user:{addr}", "type": "user", "email": addr or None,
                "login": login, "name": name}
    if login.startswith(("c:0", "s:")):
        return {"key": f"other:{login}", "type": "securitygroup",
                "email": email or None, "login": login, "name": name}
    return {"key": f"other:{login or 'unknown'}", "type": "other",
            "email": email or None, "login": login or None, "name": name}
