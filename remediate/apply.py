"""M3 — apply: execute a remediation plan (dry-run by default, --apply to execute).

Safety model:
  - dry-run (default): prints every operation, NO HTTP calls, NO audit rows.
  - --apply: executes operations one by one; every attempt lands in
    audit_log (operation_id, http method/url, response status, result).
  - A failing operation never stops the run; the summary reports it.

Write paths:
  Graph : DELETE /drives/{d}/items/{i}/permissions/{p}   (direct grants, links)
         DELETE /drives/{d}/root/permissions/{p}          (library scope grants)
         PATCH .../permissions/{p} {"recipients": [...]}  (multi-person links)
  REST  : POST  sitegroups({g})/users/removebyloginname(@v)  (group members)
         DELETE lists('l')/items(i)/roleassignments(principalId)
         DELETE web/roleassignments(principalId)
  REST non-GET calls require X-RequestDigest (fetched once per apply run).
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

from core.auth import TokenSession
from core.http import RequestError, ScHttpClient
from remediate.plan import build_plan

LOGGER = logging.getLogger("s3scope.apply")
GRAPH_BASE = "https://graph.microsoft.com/v1.0"


def _get_digest(client: Any, site_url: str) -> str:
    """Fetch the SharePoint request digest (POST contextinfo), verbose JSON."""
    body = client.post_json(f"{site_url.rstrip('/')}/_api/contextinfo",
                            None, accept="application/json;odata=verbose")
    nested = body.get("d") if isinstance(body, dict) else None
    info = nested.get("GetContextWebInformation") if isinstance(nested, dict) else None
    digest = info.get("FormDigestValue") if isinstance(info, dict) else None
    if not digest:
        raise RequestError(None, f"{site_url}/_api/contextinfo", json.dumps(body or {}),
                           "contextinfo returned no FormDigestValue")
    return str(digest)


def _audit(conn: sqlite3.Connection, operation_id: str, target_email: str,
           op: dict, *, dry_run: bool, result: str, http_method: str | None = None,
           url: str | None = None, request_json: str | None = None,
           response_status: int | None = None, response_excerpt: str | None = None,
           error: str | None = None) -> None:
    conn.execute(
        "INSERT INTO audit_log(operation_id, acted_at, target_email, action_type, "
        "dry_run, scope_id, object_path, principal_key, link_id, http_method, url, "
        "request_json, response_status, response_excerpt, result, error) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            operation_id, target_email,
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            op.get("op"), 1 if dry_run else 0,
            op.get("scope_id"), op.get("path") or op.get("group") or op.get("link"),
            op.get("principal_key") or op.get("member_key"),
            op.get("link_id") or op.get("graph_permission_id"),
            http_method, url, request_json, response_status,
            (response_excerpt or "")[:300], result, error,
        ),
    )


def execute_plan(plan: dict, conn: sqlite3.Connection, site_url: str,
                 *, session: TokenSession | None = None, client: Any | None = None,
                 apply_changes: bool = False) -> dict:
    """Run the plan. dry-run prints only; apply executes with full audit."""
    operation_id = plan["operation_id"]
    target_email = plan["target_email"]
    site_url = site_url.rstrip("/")
    client = client or ScHttpClient(session or TokenSession())
    digest: str | None = None
    executed = 0
    ok_count = 0
    failed: list[dict] = []
    skipped = 0

    def sp_headers() -> dict:
        nonlocal digest
        if digest is None:
            digest = _get_digest(client, site_url)
        return {"X-RequestDigest": digest}

    for index, op in enumerate(plan.get("operations", []), 1):
        name = op.get("op")
        target = (op.get("path") or op.get("group") or op.get("link")
                  or op.get("principal_email") or "")
        if not apply_changes or name.startswith("skip_") or name.startswith("review_"):
            if name.startswith("skip_") or name.startswith("review_"):
                skipped += 1
            mode = "DRY-RUN" if apply_changes else "DRY-RUN"
            print(f"  {index:>3}. [{mode}] {name:<34} {target} "
                  f"{op.get('note') or op.get('roles') or ''}")
            continue

        executed += 1
        try:
            status, detail = _execute_operation(op, client, site_url, sp_headers)
            ok_count += 1
            result = "ok"
            _audit(conn, operation_id, target_email, op, dry_run=False, result=result,
                   http_method=detail.get("method"), url=detail.get("url"),
                   request_json=detail.get("request_json"),
                   response_status=status,
                   response_excerpt=detail.get("response_excerpt"))
            print(f"  {index:>3}. [OK    ] {name:<34} {target} (HTTP {status})")
        except Exception as error:
            status = getattr(error, "status", None)
            failed.append({"op": name, "target": target, "error": str(error)})
            _audit(conn, operation_id, target_email, op, dry_run=False, result="failed",
                   http_method=None, url=None, response_status=status,
                   error=str(error))
            print(f"  {index:>3}. [FAILED] {name:<34} {target} — {error}")

    if apply_changes:
        conn.commit()
    summary = {
        "operation_id": operation_id,
        "target_email": target_email,
        "executed": executed,
        "ok": ok_count,
        "failed": len(failed),
        "failed_details": failed,
        "skipped": skipped,
        "apply_changes": apply_changes,
    }
    LOGGER.info("[APPLY] %s", json.dumps({k: v for k, v in summary.items()
                                          if k != "failed_details"}))
    return summary


def _execute_operation(op: dict, client: Any, site_url: str,
                       sp_headers) -> tuple[int | None, dict]:
    name = op.get("op")
    if name == "delete_role_assignment":
        if op.get("method") == "graph":
            drive = op["graph_drive_id"]
            permission = op["graph_permission_id"]
            if op.get("graph_item_id"):
                url = (f"{GRAPH_BASE}/drives/{drive}/items/{op['graph_item_id']}"
                       f"/permissions/{permission}")
            else:  # library scope: root address
                url = f"{GRAPH_BASE}/drives/{drive}/root/permissions/{permission}"
            client.delete(url)
            return 200, {"method": "DELETE", "url": url}
        if op.get("method") == "rest":
            principal_id = op.get("principal_id")
            if principal_id is None:
                raise RuntimeError(
                    f"REST 删除需要 principal_id，但 {op.get('path')} 上的授权没有 "
                    "(Graph 模式不可用时无法自动删除；可用 REST web/siteusers 解析后重试)"
                )
            if op.get("scope_type") == "site" or not op.get("item_id"):
                url = f"{site_url}/_api/web/roleassignments({principal_id})"
            else:
                url = (f"{site_url}/_api/web/lists('{op['list_id']}')"
                       f"/items({op['item_id']})/roleassignments({principal_id})")
            client.delete(url, headers=sp_headers())
            return 200, {"method": "DELETE", "url": url}
        raise RuntimeError("无可用删除路径（manual）")

    if name == "remove_site_group_member":
        login = op.get("member_login")
        if not login:
            raise RuntimeError(f"组 {op.get('group')} 缺少成员登录名，无法移除")
        encoded = quote(str(login), safe="")
        url = (f"{site_url}/_api/web/sitegroups({op['group_id']})"
               f"/users/removebyloginname(@v)?@v='{encoded}'")
        client.post_json(url, None, accept="application/json;odata=verbose",
                         headers=sp_headers())
        return 200, {"method": "POST", "url": url}

    if name == "update_sharing_link_recipients":
        drive, item, permission = op["graph_drive_id"], op["graph_item_id"], op["link_id"]
        url = f"{GRAPH_BASE}/drives/{drive}/items/{item}/permissions/{permission}"
        body = {"recipients": op["remaining_recipients"], "roles": op.get("roles") or ["read"]}
        request_json = json.dumps(body, ensure_ascii=False)
        client.patch_json(url, body)
        return 200, {"method": "PATCH", "url": url, "request_json": request_json,
                     "response_excerpt": request_json}

    if name == "revoke_sharing_link":
        if op.get("method") == "graph":
            url = (f"{GRAPH_BASE}/drives/{op['graph_drive_id']}"
                   f"/items/{op['graph_item_id']}/permissions/{op['link_id']}")
            client.delete(url)
            return 200, {"method": "DELETE", "url": url}
        raise RuntimeError("链接缺少 Graph 标识（manual）")

    raise RuntimeError(f"未知操作类型: {name}")
