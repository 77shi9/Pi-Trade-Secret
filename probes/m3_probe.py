"""M3 write-capability probe — ZERO mutation on the tenant.

Background: the Sites.FullControl.All / Sites.ReadWrite.All consent pages were
declined (correctly — they are tenant-wide and admin-gated). This probe tests
which write paths work WITHOUT any admin-granted permission:

  F0   User-level consent for Files.ReadWrite (Graph delegated; user
       consentable, no admin approval) — Microsoft's documented least
       privileged permission for driveItem permission DELETE/PATCH.
  F0b  Resolve the probe target item by path (A8-proven endpoint).
  F1   Graph DELETE .../permissions/{NONEXISTENT id} on a real unique item
       -> HTTP 404 = write rights present; 403 = blocked. Nothing is deleted.
  F2a  REST contextinfo (request digest) — if this 403s, REST writes are
       blocked wholesale.
  F2   REST DELETE .../roleassignments(999999) (nonexistent principal id)
       -> 404 = write rights; 403 = blocked. Nothing is deleted.
  F3   REST POST sitegroups(...)/users/removebyloginname(@v) with a
       NONEXISTENT login -> "user not found" style error = write rights;
       403 = blocked. Nothing is removed.
  F4   Token scp claims for both audiences (evidence).

Defaults target Trade Secret Library / Confidential / Test_Permission.docx
(known unique-permission file from the scans); override with
--drive/--path/--list/--item/--group. Writes m3_probe_results.json.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parents[1]   # repo root
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from core.auth import TokenSession  # noqa: E402
from core.http import RequestError, ScHttpClient  # noqa: E402
from core.parse import entity  # noqa: E402

LOGGER = logging.getLogger("s3scope.m3probe")
GRAPH_BASE = "https://graph.microsoft.com/v1.0"
DEFAULT_DRIVE = "b!uYewc-mCeEq2cYTW8Jf-C3OPuFn8BJZHuhB9oAlV2B3nkdRmGpYDQb8G-fo1H2bL"
DEFAULT_PATH = "Confidential/Test_Permission.docx"
DEFAULT_LIST = "66d491e7-961a-4103-bf06-f9fa351f66cb"
DEFAULT_ITEM = 35
DEFAULT_GROUP = 12  # TS-L1 Group (fake-removal probe target)
FAKE_PERMISSION = "00000000-0000-0000-0000-000000000000"
FAKE_PRINCIPAL = 999999
FAKE_LOGIN = "nonexistent.probe@invalid.example"
EXCERPT_LIMIT = 600


def _excerpt(body: Any, limit: int = EXCERPT_LIMIT) -> str:
    if body is None:
        return ""
    try:
        text = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
    except Exception:
        text = str(body)
    text = text or ""
    return text[:limit] + ("...[truncated]" if len(text) > limit else "")


def _interpret_delete(status: int | None) -> str:
    if status == 404:
        return "404 = 有写权限（目标不存在，请求已通过授权层）"
    if status == 403:
        return "403 = 无写权限（授权层拦截）"
    return f"HTTP {status} = 需人工判读"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="M3 write-capability probe (zero mutation)")
    parser.add_argument("site_url", help="https://<tenant>.sharepoint.com/sites/<site>")
    parser.add_argument("--drive", default=DEFAULT_DRIVE, help="Graph drive id of the library")
    parser.add_argument("--path", default=DEFAULT_PATH,
                        help="drive-relative path of the unique-permission item")
    parser.add_argument("--list", default=DEFAULT_LIST, help="REST list GUID of the library")
    parser.add_argument("--item", type=int, default=DEFAULT_ITEM, help="REST item id")
    parser.add_argument("--group", type=int, default=DEFAULT_GROUP, help="site group id probe")
    parser.add_argument("--json-out", default=str(BASE_DIR / "results" / "m3_probe_results.json"))
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
    )

    site_url = args.site_url.rstrip("/")
    parts = urllib.parse.urlsplit(site_url)
    host = (parts.hostname or "").lower()
    if not host.endswith(".sharepoint.com"):
        parser.error("site_url must be a *.sharepoint.com site")

    session = TokenSession(graph_scopes=("Sites.Read.All",))
    client = ScHttpClient(session)
    results: list[dict[str, Any]] = []

    def record(test, title, ok, url, body=None, status=None, notes=""):
        results.append({"test": test, "title": title, "ok": bool(ok),
                        "status": status, "url": url, "excerpt": _excerpt(body),
                        "notes": notes})
        marker = "PASS" if ok else "FAIL"
        LOGGER.info("[%s] %s %s | %s", marker, test, title, notes)

    # -- silent login first -----------------------------------------------------
    try:
        session.get_token(("Sites.Read.All",))
    except Exception as error:
        print(f"[FATAL] Authentication failed: {error}")
        return 1

    # -- F0: Files.ReadWrite user-level consent -----------------------------------
    files_rw = False
    try:
        session.get_token(("Sites.Read.All", "Files.ReadWrite"))
        files_rw = True
        # carry the new scope in every subsequent Graph call
        session.graph_scopes = ("Sites.Read.All", "Files.ReadWrite")
        record("F0", "Files.ReadWrite 用户级同意（无需管理员）", True, "-", None,
               "已同意；后续 Graph 写探测将携带该权限")
    except Exception as error:
        record("F0", "Files.ReadWrite 用户级同意（无需管理员）", False, "-", None,
               f"未同意（{error}）；写探测按只读令牌进行，预期 403")

    # -- F0b: resolve the target item by path --------------------------------------
    url = (f"{GRAPH_BASE}/drives/{args.drive}/root:/"
           f"{urllib.parse.quote(args.path, safe='/')}?$select=id,name")
    try:
        body = client.get_json(url)
        graph_item_id = entity(body).get("id")
        record("F0b", "目标项路径寻址", bool(graph_item_id), url, body, 200,
               f"item id: {graph_item_id}")
    except RequestError as error:
        graph_item_id = None
        record("F0b", "目标项路径寻址", False, url, None, error.status, str(error))

    # -- F1: Graph write probe (fake permission id) -----------------------------------
    if graph_item_id:
        url = (f"{GRAPH_BASE}/drives/{args.drive}/items/{graph_item_id}"
               f"/permissions/{FAKE_PERMISSION}")
        try:
            client.delete(url)
            record("F1", "Graph DELETE 写权限探测（假 permission id）", False, url, None, 200,
                   "意外返回 2xx——请人工核查（不应发生）")
        except RequestError as error:
            record("F1", "Graph DELETE 写权限探测（假 permission id）",
                   error.status == 404, url, error.body, error.status,
                   _interpret_delete(error.status))
    else:
        record("F1", "Graph DELETE 写权限探测", False, "", None,
               notes="skipped: no graph item id", status=None)

    # -- SP site-resource token -------------------------------------------------------
    try:
        session.get_token([f"https://{host}/.default"])
        record("F2a-0", "SP 站点资源令牌", True, "-", None, None, "acquired")
    except Exception as error:
        record("F2a-0", "SP 站点资源令牌", False, "-", None, None, str(error))

    # -- F2a: request digest ------------------------------------------------------------
    digest = None
    try:
        body = client.post_json(f"{site_url}/_api/contextinfo", None,
                                accept="application/json;odata=verbose")
        nested = body.get("d") if isinstance(body, dict) else None
        info = nested.get("GetContextWebInformation") if isinstance(nested, dict) else None
        digest = info.get("FormDigestValue") if isinstance(info, dict) else None
        record("F2a", "REST contextinfo（request digest）", bool(digest),
               f"{site_url}/_api/contextinfo", body, 200,
               "digest acquired" if digest else "no FormDigestValue in response")
    except RequestError as error:
        record("F2a", "REST contextinfo（request digest）", False,
               f"{site_url}/_api/contextinfo", None, error.status,
               f"{_interpret_delete(error.status)} —— REST 写路径可能整体被拦")
    headers = {"X-RequestDigest": digest} if digest else None

    # -- F2: REST write probe (fake principal id) -----------------------------------------
    url = (f"{site_url}/_api/web/lists('{args.list}')/items({args.item})"
           f"/roleassignments({FAKE_PRINCIPAL})")
    try:
        client.delete(url, headers=headers)
        record("F2", "REST DELETE 写权限探测（假 principal id）", False, url, None, 200,
               "意外返回 2xx——请人工核查（不应发生）")
    except RequestError as error:
        record("F2", "REST DELETE 写权限探测（假 principal id）",
               error.status == 404, url, error.body, error.status,
               _interpret_delete(error.status))

    # -- F3: REST group-member removal probe (fake login) ------------------------------------
    encoded = urllib.parse.quote(FAKE_LOGIN, safe="")
    url = (f"{site_url}/_api/web/sitegroups({args.group})"
           f"/users/removebyloginname(@v)?@v='{encoded}'")
    try:
        client.post_json(url, None, accept="application/json;odata=verbose",
                         headers=headers)
        record("F3", "REST POST 移组成员写权限探测（假登录名）", False, url, None, 200,
               "意外返回 2xx——请人工核查（不应发生）")
    except RequestError as error:
        passed_auth = error.status not in (401, 403)
        note = ("已过授权层，业务错误（用户不存在）= 有写权限"
                if passed_auth else "403 = 无写权限")
        record("F3", "REST POST 移组成员写权限探测（假登录名）", passed_auth,
               url, error.body, error.status, note)

    # -- F4: claims ----------------------------------------------------------------------------
    try:
        graph_claims = session.claims_for(("Sites.Read.All", "Files.ReadWrite")
                                          if files_rw else ("Sites.Read.All",))
        sp_claims = session.claims_for([f"https://{host}/.default"])

        def safe(claims):
            scp = str(claims.get("scp") or "")
            return {"has_files_rw": "Files.ReadWrite" in scp,
                    "has_fullcontrol": "Sites.FullControl.All" in scp,
                    "has_sites_read": "Sites.Read.All" in scp,
                    "scp_excerpt": scp[:300]}

        record("F4", "令牌 scp 证据", True, "-", None, None,
               notes=json.dumps({"graph": safe(graph_claims),
                                 "sharepoint": safe(sp_claims)}))
    except Exception as error:
        record("F4", "令牌 scp 证据", False, "-", None, None, str(error))

    # -- summary ----------------------------------------------------------------------------------
    failed = [r["test"] for r in results if not r["ok"]]
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "site_url": site_url,
        "files_readwrite_consented": files_rw,
        "summary": {"total": len(results), "passed": sum(1 for r in results if r["ok"]),
                    "failed": failed},
        "results": results,
    }
    out_path = Path(args.json_out)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    print()
    print("=" * 68)
    for r in results:
        marker = "PASS" if r["ok"] else "FAIL"
        print(f"{r['test']:<6}{marker:<7}{r['title']}")
        print(f"{'':<13}{r['notes']}")
    print("=" * 68)
    print(f"Results written to {out_path}")
    print("判读: F1/F2 的 404 = 有写权限; 403 = 无写权限。F3 非403 = 有写权限。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
