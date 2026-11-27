"""M3 pre-flight probe — READ-ONLY, no write operations.

Purpose: decide the M3 remediation path before building it.

  1. Requests Sites.FullControl.All consent (a browser prompt may appear once;
     your account carries admin-level consents, so accepting should work).
  2. After consent, retests the REST roleassignments endpoints that returned
     403 in m0b (A5/A6) — if they pass now, M3 gets precise role definitions
     AND principal ids for direct REST deletes.
  3. Records both tokens' scp claims as evidence of which write operations
     (Graph DELETE/PATCH vs REST DELETE) are available.

Writes m3_probe_results.json next to this script (tokens never written).

Exit codes: 0 = all REST retests passed; 2 = some failed; 1 = fatal (auth).
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

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from core.auth import TokenSession  # noqa: E402
from core.http import RequestError, ScHttpClient  # noqa: E402
from core.parse import _excerpt, _first_entry  # noqa: E402

LOGGER = logging.getLogger("s3scope.m3probe")
EXCERPT_LIMIT = 600
DEFAULT_LIST = "66d491e7-961a-4103-bf06-f9fa351f66cb"   # Trade Secret Library
DEFAULT_ITEM = 35                                        # Test_Permission.docx


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="M3 pre-flight probe (read-only)")
    parser.add_argument("site_url", help="e.g. https://<tenant>.sharepoint.com/sites/<site>")
    parser.add_argument("--list", default=DEFAULT_LIST, help="list GUID to retest")
    parser.add_argument("--item", type=int, default=DEFAULT_ITEM,
                        help="list item id to retest (unique-permission item)")
    parser.add_argument("--json-out", default=str(BASE_DIR / "m3_probe_results.json"))
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
                        "status": status, "url": url,
                        "excerpt": _excerpt(body), "notes": notes})
        marker = "PASS" if ok else "FAIL"
        LOGGER.info("[%s] %s %s | %s", marker, test, title, notes)

    def get(url):
        try:
            return client.get_json(url), 200, None
        except RequestError as error:
            return None, error.status, str(error)

    # -- 1. consent: ask for FullControl (single scope set with Read) -----------
    fullcontrol_scopes = ("Sites.Read.All", "Sites.FullControl.All")
    consent_ok = True
    try:
        session.get_token(fullcontrol_scopes)
        record("C1", "Graph token with Sites.FullControl.All consent", True, "-", None,
               "consent accepted")
    except Exception as error:
        consent_ok = False
        record("C1", "Graph token with Sites.FullControl.All consent", False, "-", None,
               f"consent failed: {error}; continuing with Sites.Read.All")
        session = TokenSession(graph_scopes=("Sites.Read.All",))
        client = ScHttpClient(session)
        session.get_token(("Sites.Read.All",))

    # -- 2. SP site-resource token (inherits the new consent via .default) ------
    try:
        session.get_token([f"https://{host}/.default"])
        record("C2", "SharePoint site-resource token", True, "-", None, "acquired")
    except Exception as error:
        record("C2", "SharePoint site-resource token", False, "-", None, str(error))

    # -- 3. claims evidence -------------------------------------------------------
    def safe(claims):
        scp = str(claims.get("scp") or "")
        return {
            "has_fullcontrol": "Sites.FullControl.All" in scp,
            "has_allSites": "AllSites" in scp,
            "scp_excerpt": scp[:300],
        }

    try:
        graph_claims = session.claims_for(fullcontrol_scopes if consent_ok
                                          else ("Sites.Read.All",))
        sp_claims = session.claims_for([f"https://{host}/.default"])
        record("C3", "token scp claims", True, "-", None,
               notes=json.dumps({"graph": safe(graph_claims),
                                 "sharepoint": safe(sp_claims)}))
    except Exception as error:
        record("C3", "token scp claims", False, "-", None, str(error))

    # -- 4. REST roleassignments retests (were 403 in m0b) ------------------------
    url = f"{site_url}/_api/web/roleassignments?$expand=RoleDefinitionBindings,Member&$top=50"
    body, status, err = get(url)
    first = _first_entry(body)
    record("P1", "web roleassignments (m0b was 403)", first is not None, url, body, status,
           f"entries: {first is not None}" + (f"; error: {err}" if err else ""))

    url = (f"{site_url}/_api/web/lists('{args.list}')"
           "/roleassignments?$expand=RoleDefinitionBindings,Member&$top=50")
    body, status, err = get(url)
    first = _first_entry(body)
    record("P2", "list roleassignments (m0b was 403)", first is not None, url, body, status,
           f"entries: {first is not None}" + (f"; error: {err}" if err else ""))

    url = (f"{site_url}/_api/web/lists('{args.list}')/items({args.item})"
           "/roleassignments?$expand=RoleDefinitionBindings,Member&$top=50")
    body, status, err = get(url)
    first = _first_entry(body)
    member = first.get("Member") if isinstance(first, dict) else {}
    bindings = first.get("RoleDefinitionBindings") if isinstance(first, dict) else None
    role_names = (";".join(str(b.get("Name")) for b in bindings if isinstance(b, dict))
                  if isinstance(bindings, list) else None)
    record("P3", "item roleassignments on unique item (m0b was 403)",
           first is not None, url, body, status,
           f"Member={member.get('LoginName') if isinstance(member, dict) else None}; "
           f"roles={role_names or 'n/a'}"
           + (f"; error: {err}" if err else ""))

    # -- summary --------------------------------------------------------------------
    failed = [r["test"] for r in results if not r["ok"]]
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "site_url": site_url,
        "summary": {"total": len(results),
                    "passed": sum(1 for r in results if r["ok"]),
                    "failed": failed},
        "results": results,
    }
    out_path = Path(args.json_out)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    print()
    print("=" * 64)
    for r in results:
        print(f"{r['test']:<4}{'PASS' if r['ok'] else 'FAIL':<7}{r['title']}")
    print("=" * 64)
    print(f"Results written to {out_path}")
    return 0 if not failed else 2


if __name__ == "__main__":
    sys.exit(main())
