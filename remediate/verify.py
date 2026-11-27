"""M3 — verify: the closed loop's final step.

Flow: snapshot the user's grant footprint -> fresh scan -> re-query ->
diff. A successful remediation shows zero residual direct grants,
group memberships (non-system), and link grants for the target user.
"""

from __future__ import annotations

import logging
from typing import Any

from query.offboarding import query_grants
from scan.scanner import run_scan
from store.schema import connect

LOGGER = logging.getLogger("s3scope.verify")


def _footprint(report: dict) -> dict:
    return {
        "direct_grants": len(report["direct_grants"]),
        "real_group_memberships": sum(
            1 for m in report["site_group_memberships"] if not m["is_system"]
        ),
        "link_recipient": sum(
            1 for l in report["sharing_links"] if l["is_recipient"]
        ),
        "link_owner": sum(1 for l in report["sharing_links"] if l["is_owner"]),
    }


def _details(report: dict) -> dict:
    return {
        "direct_grants": [
            f"{g['scope_type']}:{g['root_path']} ({g['roles']})"
            for g in report["direct_grants"]
        ],
        "group_memberships": [
            m["group_name"] for m in report["site_group_memberships"]
        ],
        "links": [
            f"{l['root_path']} {l['link_type']}/{l['link_scope']}"
            for l in report["sharing_links"]
        ],
    }


def verify_user(site_url: str, db_path: str, email: str,
                *, session: Any = None, client: Any = None) -> dict:
    """Re-scan, re-query, and report residual access for one user."""
    conn = connect(db_path)
    try:
        before_report = query_grants(conn, email)
        before = _footprint(before_report)
    finally:
        conn.close()

    scan_stats = run_scan(site_url, db_path, session=session, client=client)

    conn = connect(db_path)
    try:
        after_report = query_grants(conn, email)
        after = _footprint(after_report)
    finally:
        conn.close()

    residual = after["direct_grants"] > 0 or after["real_group_memberships"] > 0 \
        or after["link_recipient"] > 0
    result = {
        "email": email,
        "before": before,
        "after": after,
        "residual": residual,
        "scan": {"run_id": scan_stats.get("run_id"),
                 "status": scan_stats.get("status"),
                 "requests": scan_stats.get("requests", {}).get("total")},
        "after_details": _details(after_report),
    }
    LOGGER.info("[VERIFY] %s residual=%s after=%s",
                email, residual, after)
    return result
