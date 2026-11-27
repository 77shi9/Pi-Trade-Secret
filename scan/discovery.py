"""Phase 1 — permission-scope discovery (metadata only, no permission reads).

Proven endpoints (m0b results):
- Graph  /sites/{host}:{path}                      -> site id
- Graph  /sites/{id}/drives                        -> document libraries
- Graph  /drives/{id}/root?$select=sharepointIds   -> REST list GUID
- REST   /_api/web?$select=...HasUniqueRoleAssignments        -> site flag
- REST   /_api/web/lists('{guid}')?$select=...flag            -> library flag
- REST   /_api/web/lists('{guid}')/items?...flag (paged)      -> item flags
- REST   /_api/web/sitegroups + /sitegroups({id})/users       -> group members
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote, urlsplit

from core.http import RequestError
from core.parse import entries, entity, member_principal, server_relative_path, truthy

LOGGER = logging.getLogger("s3scope.discovery")
GRAPH_BASE = "https://graph.microsoft.com/v1.0"
ITEMS_PAGE_SIZE = 1000
GROUPS_PAGE_SIZE = 500


def discover(client: Any, site_url: str) -> dict:
    """Run Phase 1 for one site. Returns site/libraries/items/groups/errors."""
    site_url = site_url.rstrip("/")
    parts = urlsplit(site_url)
    host = (parts.hostname or "").lower()
    site_path = parts.path.rstrip("/")
    errors: list[dict] = []

    graph_site = entity(client.get_json(f"{GRAPH_BASE}/sites/{host}:{quote(site_path, safe='/')}"))
    graph_site_id = graph_site.get("id")
    web = entity(client.get_json(
        f"{site_url}/_api/web?$select=Id,Title,ServerRelativeUrl,HasUniqueRoleAssignments"
    ))
    site_id = str(web.get("Id") or graph_site_id or "")
    drives = [
        d for d in entries(client.get_json(
            f"{GRAPH_BASE}/sites/{graph_site_id}/drives?$top=50&$select=id,name,driveType,webUrl"
        ))
        if isinstance(d, dict) and d.get("driveType") == "documentLibrary"
    ]
    LOGGER.info("[SCAN] site=%s libraries=%d", web.get("Title"), len(drives))

    libraries: list[dict] = []
    items_by_list: dict[str, list[dict]] = {}
    for drive in drives:
        drive_id = str(drive.get("id") or "")
        try:
            root = entity(client.get_json(
                f"{GRAPH_BASE}/drives/{drive_id}/root?$select=id,name,webUrl,sharepointIds"
            ))
            sharepoint_ids = root.get("sharepointIds") if isinstance(root.get("sharepointIds"), dict) else {}
            list_guid = sharepoint_ids.get("listId")
            root_path = server_relative_path(root.get("webUrl") or drive.get("webUrl"))
            if not list_guid:
                raise RequestError(None, f"{GRAPH_BASE}/drives/{drive_id}/root", "",
                                   "drive root returned no sharepointIds.listId")
            lib = entity(client.get_json(
                f"{site_url}/_api/web/lists('{list_guid}')"
                "?$select=Id,Title,HasUniqueRoleAssignments"
            ))
            unique_flag = truthy(lib.get("HasUniqueRoleAssignments"))
            items = _collect_items(client, site_url, str(list_guid), errors,
                                   str(lib.get("Title") or drive.get("name") or list_guid))
            items_by_list[str(list_guid)] = items
            libraries.append({
                "drive_id": drive_id,
                "drive_name": str(drive.get("name") or lib.get("Title") or list_guid),
                "list_guid": str(list_guid),
                "title": str(lib.get("Title") or drive.get("name") or list_guid),
                "root_path": root_path,
                "unique_flag": unique_flag,
                "item_count": len(items),
            })
            LOGGER.info("[SCAN] library '%s' items=%d unique=%s",
                        libraries[-1]["title"], len(items), unique_flag)
        except Exception as error:  # keep scanning other libraries
            errors.append({"stage": "library", "target": str(drive.get("name")),
                           "error": str(error)})
            LOGGER.error("[SCAN] library '%s' failed: %s", drive.get("name"), error)

    groups = discover_groups(client, site_url, errors)
    return {
        "site_id": site_id,
        "graph_site_id": graph_site_id,
        "site_title": str(web.get("Title") or ""),
        "site_path": str(web.get("ServerRelativeUrl") or site_path),
        "site_unique": truthy(web.get("HasUniqueRoleAssignments")),
        "libraries": libraries,
        "items": items_by_list,
        "groups": groups,
        "errors": errors,
    }


def _collect_items(client: Any, site_url: str, list_guid: str,
                   errors: list[dict], library_title: str) -> list[dict]:
    items: list[dict] = []
    page_url = (
        f"{site_url}/_api/web/lists('{list_guid}')/items"
        f"?$top={ITEMS_PAGE_SIZE}&$select=Id,FSObjType,FileRef,FileLeafRef,HasUniqueRoleAssignments"
    )
    try:
        for page in client.pages(page_url):
            for entry in entries(page):
                if not isinstance(entry, dict):
                    continue
                item_id = entry.get("Id") or entry.get("ID")
                file_ref = str(entry.get("FileRef") or "")
                if item_id is None or not file_ref:
                    continue
                fs_type = str(entry.get("FSObjType"))
                items.append({
                    "item_id": int(item_id),
                    "object_type": "folder" if fs_type == "1" else "file",
                    "path": file_ref,
                    "name": str(entry.get("FileLeafRef") or ""),
                    "unique_flag": truthy(entry.get("HasUniqueRoleAssignments")),
                })
    except Exception as error:
        errors.append({"stage": "items", "target": library_title, "error": str(error)})
        LOGGER.error("[SCAN] items of '%s' failed (partial=%d): %s",
                     library_title, len(items), error)
    return items


def discover_groups(client: Any, site_url: str, errors: list[dict]) -> list[dict]:
    """Site groups + members (A9-proven endpoints)."""
    groups: list[dict] = []
    try:
        for page in client.pages(f"{site_url}/_api/web/sitegroups?$top={GROUPS_PAGE_SIZE}"):
            for entry in entries(page):
                if not isinstance(entry, dict):
                    continue
                group_id = entry.get("Id")
                if group_id is None:
                    continue
                title = str(entry.get("Title") or f"group{group_id}")
                members: list[dict] = []
                try:
                    users_url = f"{site_url}/_api/web/sitegroups({group_id})/users?$top={GROUPS_PAGE_SIZE}"
                    for user_page in client.pages(users_url):
                        for user in entries(user_page):
                            if not isinstance(user, dict):
                                continue
                            principal = member_principal(
                                user.get("LoginName"), user.get("Email"), user.get("Title")
                            )
                            members.append(principal)
                except Exception as error:
                    errors.append({"stage": "group_members", "target": title,
                                   "error": str(error)})
                groups.append({
                    "group_id": int(group_id),
                    "title": title,
                    "description": entry.get("Description"),
                    "members": members,
                })
    except Exception as error:
        errors.append({"stage": "sitegroups", "target": site_url, "error": str(error)})
    LOGGER.info("[SCAN] site groups=%d", len(groups))
    return groups
