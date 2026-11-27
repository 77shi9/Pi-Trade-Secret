"""M1 scanner orchestration: Phase 1 discovery + Phase 2 expansion -> SQLite.

Run flow (all endpoints proven by m0/m0b):

    Phase 1  Graph site -> drives -> list GUIDs -> REST items (flags only)
             + REST web/site-list flags + site groups & members
    Phase 2  Graph delta (path->id map, one per library)
             + Graph permissions ONLY for unique scopes (site/library/item)
             - entries without inheritedFrom -> direct grants of that scope
             - entries with    inheritedFrom -> site ('web') scope grants
             - link entries     -> sharing_links (full recipient list kept)

The scanner never reads permissions for inherited objects — that is the
whole point of the permission-scope model. API requests are counted per
category for the M4 research comparison.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from core.auth import TokenSession
from core.http import ScHttpClient
from scan import discovery, expansion
from scan.persist import RunWriter
from store.schema import connect, init_schema

LOGGER = logging.getLogger("s3scope.scanner")


def _classify(url: str) -> str:
    if "/root/delta" in url:
        return "graph_delta"
    if "/permissions" in url:
        return "graph_permissions"
    if "/root:/" in url:
        return "graph_path_lookup"
    if "/sitegroups(" in url:
        return "sp_group_users"
    if "/sitegroups" in url:
        return "sp_groups"
    if "/items?" in url:
        return "sp_items"
    if "/lists('" in url:
        return "sp_list"
    if "/_api/web" in url:
        return "sp_web"
    if "/root?" in url:
        return "graph_drive_root"
    if "/drives" in url:
        return "graph_drives"
    if "graph.microsoft.com" in url and "/sites/" in url:
        return "graph_site"
    return "other"


class CountingClient:
    """Wraps ScHttpClient (or any client) and counts requests per category."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.counts: Counter[str] = Counter()

    def get_json(self, url: str, **kwargs: Any) -> Any:
        self.counts[_classify(url)] += 1
        return self._inner.get_json(url, **kwargs)

    def pages(self, url: str, **kwargs: Any):
        for page in self._inner.pages(url, **kwargs):
            self.counts[_classify(url)] += 1
            yield page

    @property
    def total(self) -> int:
        return sum(self.counts.values())


def run_scan(site_url: str, db_path: str | Path, *,
             session: TokenSession | None = None,
             client: Any | None = None) -> dict:
    """Run a full two-phase scan and persist the governance baseline."""
    started = time.monotonic()
    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "_" + uuid.uuid4().hex[:6]

    session = session or TokenSession()
    inner_client = client or ScHttpClient(session)
    counting = CountingClient(inner_client)

    conn = connect(db_path)
    try:
        init_schema(conn)
        site_url = site_url.rstrip("/")
        result = discovery.discover(counting, site_url)

        writer = RunWriter(conn, run_id, "scope_full", result["site_id"],
                           site_url, result["graph_site_id"])
        writer.start(started_at)
        writer.write_site({
            "Title": result["site_title"],
            "ServerRelativeUrl": result["site_path"],
            "unique": result["site_unique"],
        })
        for library in result["libraries"]:
            writer.write_library(library)
            writer.write_items(library["list_guid"], result["items"].get(library["list_guid"], []))
        writer.write_groups(result["groups"])

        # ---- Phase 2: expansion of unique scopes only -------------------------
        errors: list[dict] = list(result["errors"])
        drive_maps = expansion.build_drive_maps(counting, result["libraries"])
        site_grants: dict[tuple, dict] = {}
        site_links: dict[tuple, dict] = {}
        link_rows = 0
        grant_rows = 0

        def bucket_site(parsed: dict) -> None:
            """Inherited entries observed at library roots belong to the site scope."""
            if parsed.get("link"):
                key = ("link", parsed["permission_id"])
                site_links[key] = parsed
            else:
                principal = parsed.get("principal") or {}
                key = ("grant", principal.get("key") or parsed["permission_id"],
                       parsed.get("roles"))
                site_grants[key] = parsed

        for library in result["libraries"]:
            scope_id = f"list:{library['list_guid']}"
            try:
                root_permissions = expansion.expand_library_root(counting, library["drive_id"])
            except Exception as error:
                errors.append({"stage": "phase2", "target": library["title"],
                               "error": str(error)})
                LOGGER.error("[SCAN] root permissions of '%s' failed: %s",
                             library["title"], error)
                root_permissions = []
            for parsed in root_permissions:
                if library["unique_flag"] and not parsed["inherited"]:
                    # direct grant / link on the library scope itself
                    if parsed.get("link"):
                        writer.write_link(scope_id, parsed["link"], library["drive_id"],
                                          None, parsed)
                        link_rows += 1
                    else:
                        writer.write_grant(scope_id, parsed)
                        grant_rows += 1
                else:
                    # inherited entries — or every entry of a non-unique library,
                    # which inherits from the site — belong to the site scope
                    bucket_site(parsed)

            items = result["items"].get(library["list_guid"], [])
            unique_results = expansion.expand_unique_items(
                counting, library, items, drive_maps.get(library["drive_id"], {}), errors
            )
            for item, permissions, graph_id in unique_results:
                item_scope = f"item:{library['list_guid']}:{item['item_id']}"
                for parsed in permissions:
                    if parsed["inherited"]:
                        continue  # covered by the ancestor scope's own expansion
                    if parsed.get("link"):
                        writer.write_link(item_scope, parsed["link"],
                                          library["drive_id"], graph_id, parsed)
                        link_rows += 1
                    else:
                        writer.write_grant(item_scope, parsed)
                        grant_rows += 1

        for parsed in site_grants.values():
            writer.write_grant("web", parsed)
            grant_rows += 1
        for parsed in site_links.values():
            writer.write_link("web", parsed["link"], None, None, parsed)
            link_rows += 1

        # ---- stats ---------------------------------------------------------------
        objects_counts = {"site": 0, "library": 0, "folder": 0, "file": 0}
        unique_counts = {"site": 0, "library": 0, "folder": 0, "file": 0}
        objects_counts["site"] = 1
        if result["site_unique"]:
            unique_counts["site"] = 1
        for library in result["libraries"]:
            objects_counts["library"] += 1
            if library["unique_flag"]:
                unique_counts["library"] += 1
            for item in result["items"].get(library["list_guid"], []):
                objects_counts[item["object_type"]] += 1
                if item["unique_flag"]:
                    unique_counts[item["object_type"]] += 1
        total_objects = sum(objects_counts.values())
        total_unique = sum(unique_counts.values())
        stats = {
            "site_title": result["site_title"],
            "site_unique": result["site_unique"],
            "objects": {**objects_counts, "total": total_objects},
            "unique_scopes": {**unique_counts, "total": total_unique},
            "inherited_objects": total_objects - total_unique,
            "inheritance_rate": round((total_objects - total_unique) / total_objects * 100, 1)
                                if total_objects else 0.0,
            "permission_reads": counting.counts.get("graph_permissions", 0),
            "requests": {**dict(counting.counts), "total": counting.total},
            "grants": {
                "role_assignment_rows": grant_rows,
                "sharing_link_rows": link_rows,
                "site_groups": len(result["groups"]),
                "group_members": sum(len(g["members"]) for g in result["groups"]),
            },
            "errors": len(errors),
            "duration_seconds": round(time.monotonic() - started, 1),
        }
        status = "partial" if errors else "success"
        completed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        writer.finalize(stats, errors, status=status, completed_at=completed_at)
        stats["run_id"] = run_id
        stats["status"] = status
        stats["db_path"] = str(db_path)
        LOGGER.info("[SCAN] done run=%s status=%s objects=%d unique=%d requests=%d",
                    run_id, status, total_objects, total_unique, counting.total)
        return stats
    finally:
        conn.close()
