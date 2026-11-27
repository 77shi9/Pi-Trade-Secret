"""Phase 2 — expand ONLY unique permission scopes (Graph permissions).

Proven endpoints (m0 T5d / m0b A8, A10):
- Graph /drives/{id}/root/delta               -> path -> graph item id map (A10)
- Graph /drives/{id}/root/permissions         -> library scope + site-inherited grants
- Graph /drives/{id}/items/{graphId}/permissions -> direct grants + sharing links

REST roleassignments is NOT used: it returns 403 with Sites.Read.All tokens
(m0b A5/A6) even for site owners. Graph permissions returns the same
information (roles, principals incl. principalId, inheritedFrom markers).
"""

from __future__ import annotations

import logging
from typing import Any

from core.parse import entries, parse_permission

LOGGER = logging.getLogger("s3scope.expansion")
GRAPH_BASE = "https://graph.microsoft.com/v1.0"
DELTA_PAGE_SIZE = 200


def build_drive_maps(client: Any, libraries: list[dict]) -> dict[str, dict[str, str]]:
    """Path -> Graph item id map per drive (one paged delta per library)."""
    maps: dict[str, dict[str, str]] = {}
    for lib in libraries:
        drive_id = lib["drive_id"]
        path_to_id: dict[str, str] = {}
        delta_url = (
            f"{GRAPH_BASE}/drives/{drive_id}/root/delta"
            f"?$select=id,name,webUrl&$top={DELTA_PAGE_SIZE}"
        )
        try:
            for page in client.pages(delta_url):
                for entry in entries(page):
                    if not isinstance(entry, dict):
                        continue
                    web_url = entry.get("webUrl")
                    item_id = entry.get("id")
                    if web_url and item_id:
                        from core.parse import server_relative_path
                        path_to_id[server_relative_path(web_url)] = str(item_id)
        except Exception as error:
            LOGGER.error("[SCAN] delta for '%s' failed: %s", lib["title"], error)
        maps[drive_id] = path_to_id
        LOGGER.info("[SCAN] delta map '%s': %d entries", lib["title"], len(path_to_id))
    return maps


def expand_library_root(client: Any, drive_id: str) -> list[dict]:
    """Permissions of a drive root = library-level permission set.

    Entries WITHOUT inheritedFrom are direct grants on the library scope;
    entries WITH inheritedFrom belong to ancestor (site) scopes.
    """
    body = client.get_json(f"{GRAPH_BASE}/drives/{drive_id}/root/permissions")
    return [parse_permission(e) for e in entries(body) if isinstance(e, dict)]


def expand_item(client: Any, drive_id: str, graph_item_id: str) -> list[dict]:
    """Permissions of one item (queried only for unique-permission objects)."""
    body = client.get_json(
        f"{GRAPH_BASE}/drives/{drive_id}/items/{graph_item_id}/permissions"
    )
    return [parse_permission(e) for e in entries(body) if isinstance(e, dict)]


def expand_unique_items(client: Any, library: dict, items: list[dict],
                        path_to_id: dict[str, str],
                        errors: list[dict]) -> list[tuple[dict, list[dict]]]:
    """Fetch permissions for each unique item of one library.

    Returns [(item, parsed_permissions)] plus errors for unresolvable ids.
    """
    results: list[tuple[dict, list[dict]]] = []
    drive_id = library["drive_id"]
    for item in items:
        if not item["unique_flag"]:
            continue
        graph_id = path_to_id.get(item["path"])
        if not graph_id:
            message = f"no Graph id for unique item path={item['path']!r}"
            errors.append({"stage": "phase2", "target": item["path"], "error": message})
            LOGGER.warning("[SCAN] %s", message)
            continue
        try:
            permissions = expand_item(client, drive_id, graph_id)
        except Exception as error:
            errors.append({"stage": "phase2", "target": item["path"], "error": str(error)})
            LOGGER.error("[SCAN] permissions for %s failed: %s", item["path"], error)
            continue
        results.append((item, permissions))
    return results
