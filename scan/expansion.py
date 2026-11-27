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

from core.parse import entries, entity, parse_permission, server_relative_path
from urllib.parse import quote

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


def _path_lookup(client: Any, drive_id: str, root_path: str, path: str) -> str | None:
    """Resolve a Graph item id by server-relative path (A8-proven endpoint).

    Used as a fallback when the delta map misses a unique item (delta may omit
    drafts or newly-created items; the path lookup resolves any addressable item).
    """
    if root_path and path.startswith(root_path):
        rel = path[len(root_path):].lstrip("/")
    else:
        rel = path.lstrip("/")
    if not rel:
        return None
    url = f"{GRAPH_BASE}/drives/{drive_id}/root:/{quote(rel, safe='/')}?$select=id"
    try:
        return entity(client.get_json(url)).get("id")
    except Exception as error:
        LOGGER.warning("[SCAN] path lookup failed for %s: %s", path, error)
        return None


def expand_unique_items(client: Any, library: dict, items: list[dict],
                        path_to_id: dict[str, str],
                        errors: list[dict]) -> list[tuple[dict, list[dict], str]]:
    """Fetch permissions for each unique item of one library.

    Returns [(item, parsed_permissions, graph_item_id)] plus errors for
    unresolvable ids. Delta misses fall back to the path lookup endpoint.
    """
    results: list[tuple[dict, list[dict], str]] = []
    drive_id = library["drive_id"]
    root_path = library.get("root_path") or ""
    for item in items:
        if not item["unique_flag"]:
            continue
        graph_id = path_to_id.get(item["path"])
        if not graph_id:
            # delta missed this item; fall back to the path lookup endpoint
            graph_id = _path_lookup(client, drive_id, root_path, item["path"])
        if not graph_id:
            message = (f"no Graph id for unique item path={item['path']!r} "
                       f"(delta map size={len(path_to_id)})")
            errors.append({"stage": "phase2", "target": item["path"], "error": message})
            LOGGER.warning("[SCAN] %s", message)
            continue
        try:
            permissions = expand_item(client, drive_id, str(graph_id))
        except Exception as error:
            errors.append({"stage": "phase2", "target": item["path"], "error": str(error)})
            LOGGER.error("[SCAN] permissions for %s failed: %s", item["path"], error)
            continue
        results.append((item, permissions, str(graph_id)))
    return results
