"""M0b follow-up endpoint probes for s3scope.

Answers the open questions left by m0_results.json (run against the real
document libraries, auto-derived from Graph drives):

  A1     Graph drives (document libraries only, all of them this time)
  A2-D*  drive root sharepointIds -> REST list GUID mapping
  A3-D*  REST single-library $select incl. HasUniqueRoleAssignments
  A4-D*  REST items $select incl. HasUniqueRoleAssignments   <-- CRITICAL retest
         (m0 hit an empty catalog list; this uses the real libraries)
  A5-D*  REST item-level roleassignments?$expand on a unique item <-- CRITICAL
  A6-D*  REST list-level roleassignments?$expand (fallback shape)
  A7     Graph sites/{id}/permissions (site-level permission set)
  A8-D*  Graph path lookup root:/{relpath} (REST item -> Graph item id join)
  A9     site groups + membership of the logged-in account (explains the m0 T4 403)
  A10-D* Graph delta first page (id-map strategy for Phase 2)

Writes m0b_results.json next to this script; tokens are never written; bodies
are truncated to 600 characters.

Exit codes: 0 = all probes ran; 2 = critical probes (A4/A5) failed;
1 = fatal (authentication).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import urllib.parse
from pathlib import Path
from typing import Any, Mapping

BASE_DIR = Path(__file__).resolve().parents[1]   # repo root
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from core.auth import TokenSession  # noqa: E402
from core.http import RequestError, ScHttpClient, next_link  # noqa: E402
from m0_validate import _entries, _entity, _excerpt, _first_entry, _now, _truthy  # noqa: E402

LOGGER = logging.getLogger("s3scope.m0b")
GRAPH_BASE = "https://graph.microsoft.com/v1.0"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="M0b follow-up endpoint probes")
    parser.add_argument("site_url", help="e.g. https://<tenant>.sharepoint.com/sites/<site>")
    parser.add_argument("--json-out", default=str(BASE_DIR / "results" / "m0b_results.json"))
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
    )

    site_url = args.site_url.rstrip("/")
    parts = urllib.parse.urlsplit(site_url)
    host = (parts.hostname or "").lower()
    site_path = parts.path.rstrip("/")
    if not host.endswith(".sharepoint.com") or not site_path:
        parser.error("site_url must look like https://<tenant>.sharepoint.com/sites/<site>")

    session = TokenSession(graph_scopes=("Sites.Read.All",))
    client = ScHttpClient(session)
    results: list[dict[str, Any]] = []

    def record(
        test: str,
        title: str,
        ok: bool,
        url: str,
        body: Any = None,
        status: int | None = None,
        notes: str = "",
        *,
        critical: bool = False,
        skipped: bool = False,
    ) -> None:
        results.append(
            {
                "test": test,
                "title": title,
                "critical": critical,
                "skipped": skipped,
                "ok": bool(ok),
                "status": status,
                "url": url,
                "excerpt": _excerpt(body),
                "notes": notes,
            }
        )
        marker = "SKIP" if skipped else ("PASS" if ok else "FAIL")
        LOGGER.info("[%s] %s %s | %s", marker, test, title, notes)

    def get(url: str) -> tuple[Any, int | None, str | None]:
        try:
            return client.get_json(url), 200, None
        except RequestError as error:
            return None, error.status, str(error)

    # -- login up front ----------------------------------------------------------
    try:
        session.get_token(("Sites.Read.All",))
        session.get_token([f"https://{host}/.default"])
    except Exception as error:
        print(f"[FATAL] Authentication failed: {error}")
        return 1
    upn = str(session.claims_for(("Sites.Read.All",)).get("upn") or "").lower()
    LOGGER.info("[AUTH] Logged in as %s", upn)

    # -- A1: graph site + drives ---------------------------------------------------
    graph_site_id = None
    url = f"{GRAPH_BASE}/sites/{host}:{urllib.parse.quote(site_path, safe='/')}"
    body, status, err = get(url)
    graph_site_id = _entity(body).get("id")
    record("A1", "graph site", bool(graph_site_id), url, body, status,
           f"site id: {graph_site_id}" + (f"; error: {err}" if err else ""))

    drives: list[Mapping[str, Any]] = []
    if graph_site_id:
        url = f"{GRAPH_BASE}/sites/{graph_site_id}/drives?$top=20&$select=id,name,driveType,webUrl"
        body, status, err = get(url)
        drives = [
            e for e in _entries(body)
            if isinstance(e, Mapping) and e.get("driveType") == "documentLibrary"
        ]
        record("A1", "graph drives (document libraries only)", bool(drives), url, body, status,
               f"{len(drives)} doc libraries: " + ", ".join(str(d.get("name")) for d in drives)
               + (f"; error: {err}" if err else ""))
    else:
        record("A1", "graph drives", False, "", None, notes="skipped: no site id", skipped=True)

    # -- A7: graph site-level permissions -------------------------------------------
    if graph_site_id:
        url = f"{GRAPH_BASE}/sites/{graph_site_id}/permissions"
        body, status, err = get(url)
        perms = [e for e in _entries(body) if isinstance(e, Mapping)]
        record("A7", "graph sites/{id}/permissions (site level)", body is not None, url, body, status,
               f"{len(perms)} site permission entries" + (f"; error: {err}" if err else ""))
    else:
        record("A7", "graph site permissions", False, "", None, notes="skipped", skipped=True)

    # -- per-drive probes -------------------------------------------------------------
    for index, drive in enumerate(drives, start=1):
        drive_id = str(drive.get("id") or "")
        drive_name = str(drive.get("name") or f"drive{index}")
        tag = f"D{index}"
        label = f"[{drive_name}]"

        # A2: root sharepointIds -> REST list GUID
        list_guid = None
        root_url = f"{GRAPH_BASE}/drives/{drive_id}/root?$select=id,name,webUrl,sharepointIds"
        body, status, err = get(root_url)
        root = _entity(body)
        sharepoint_ids = root.get("sharepointIds") if isinstance(root, Mapping) else None
        sharepoint_ids = sharepoint_ids if isinstance(sharepoint_ids, Mapping) else {}
        list_guid = sharepoint_ids.get("listId")
        record(f"A2-{tag}", f"root sharepointIds {label}", bool(list_guid), root_url, body, status,
               f"listId: {list_guid}; siteUrl: {sharepoint_ids.get('siteUrl')}"
               + (f"; error: {err}" if err else ""))

        if not list_guid:
            for probe in ("A3", "A4", "A5", "A6", "A8", "A10"):
                record(f"{probe}-{tag}", f"{probe} {label}", False, "", None,
                       notes="skipped: no list guid", skipped=True)
            continue

        # A3: REST single-library select with flag
        url = f"{site_url}/_api/web/lists('{list_guid}')?$select=Id,Title,HasUniqueRoleAssignments"
        body, status, err = get(url)
        lib = _entity(body)
        record(f"A3-{tag}", f"library select incl. flag {label}", "HasUniqueRoleAssignments" in lib,
               url, body, status,
               f"flag present: {'HasUniqueRoleAssignments' in lib}; "
               f"library unique: {_truthy(lib.get('HasUniqueRoleAssignments'))}"
               + (f"; error: {err}" if err else ""))

        # A4: REST items with flag (CRITICAL retest on the real library)
        items: list[Mapping[str, Any]] = []
        url = (
            f"{site_url}/_api/web/lists('{list_guid}')/items"
            "?$top=50&$select=Id,FSObjType,FileRef,FileLeafRef,HasUniqueRoleAssignments"
        )
        body, status, err = get(url)
        items = [e for e in _entries(body) if isinstance(e, Mapping)]
        first = items[0] if items else None
        flag_present = first is not None and "HasUniqueRoleAssignments" in first
        folders = sum(1 for e in items if str(e.get("FSObjType")) == "1")
        files = len(items) - folders
        unique_items = [e for e in items if _truthy(e.get("HasUniqueRoleAssignments"))]
        record(
            f"A4-{tag}",
            f"items $select incl. flag {label} (CRITICAL Phase 1)",
            flag_present,
            url,
            body,
            status,
            f"sample {len(items)} items ({folders} folders / {files} files); "
            f"flag present: {flag_present}; unique in sample: {len(unique_items)}; "
            f"nextLink: {next_link(body) is not None}"
            + (f"; error: {err}" if err else ""),
            critical=True,
        )

        # A5: REST item-level roleassignments on a unique item (CRITICAL)
        if unique_items:
            u = unique_items[0]
            url = (
                f"{site_url}/_api/web/lists('{list_guid}')/items({u.get('Id')})"
                "/roleassignments?$expand=RoleDefinitionBindings,Member&$top=50"
            )
            body, status, err = get(url)
            first_ra = _first_entry(body)
            member = first_ra.get("Member") if isinstance(first_ra, Mapping) else None
            member = member if isinstance(member, Mapping) else {}
            bindings = first_ra.get("RoleDefinitionBindings") if isinstance(first_ra, Mapping) else None
            role_names = (
                ";".join(str(b.get("Name")) for b in bindings if isinstance(b, Mapping))
                if isinstance(bindings, list) else None
            )
            record(
                f"A5-{tag}",
                f"item roleassignments expand {label} (CRITICAL Phase 2 REST)",
                first_ra is not None,
                url,
                body,
                status,
                f"on unique item id={u.get('Id')} path={u.get('FileRef')}; "
                f"Member.LoginName={member.get('LoginName')}; Member.Id={member.get('Id')}; "
                f"roles={role_names or 'n/a'}"
                + (f"; error: {err}" if err else ""),
                critical=True,
            )
        else:
            record(f"A5-{tag}", f"item roleassignments expand {label} (CRITICAL Phase 2 REST)",
                   False, "", None, notes="skipped: no unique item in sample", critical=True, skipped=True)

        # A6: REST list-level roleassignments (fallback shape)
        url = (
            f"{site_url}/_api/web/lists('{list_guid}')"
            "/roleassignments?$expand=RoleDefinitionBindings,Member&$top=20"
        )
        body, status, err = get(url)
        first_ra = _first_entry(body)
        record(f"A6-{tag}", f"list roleassignments expand {label}", first_ra is not None, url, body, status,
               f"entries present: {first_ra is not None}" + (f"; error: {err}" if err else ""))

        # A8: Graph path lookup (REST item path -> Graph item id)
        probe_item = next((e for e in items if str(e.get("FSObjType")) == "0"), items[0] if items else None)
        if probe_item is not None:
            file_ref = str(probe_item.get("FileRef") or "")
            root_web_url = str(root.get("webUrl") or "")
            root_path = urllib.parse.unquote(urllib.parse.urlsplit(root_web_url).path).rstrip("/")
            rel = file_ref[len(root_path):].lstrip("/") if file_ref.startswith(root_path) else ""
            if rel:
                lookup_url = (
                    f"{GRAPH_BASE}/drives/{drive_id}/root:/"
                    f"{urllib.parse.quote(rel, safe='/')}?$select=id,name"
                )
                body, status, err = get(lookup_url)
                found = _entity(body)
                record(f"A8-{tag}", f"graph path lookup {label}", bool(found.get("id")), lookup_url,
                       body, status,
                       f"rel='{rel}' -> id: {found.get('id')}"
                       + (f"; error: {err}" if err else ""))
            else:
                record(f"A8-{tag}", f"graph path lookup {label}", False, "", None,
                       notes=f"skipped: could not derive rel path from FileRef '{file_ref}'",
                       skipped=True)
        else:
            record(f"A8-{tag}", f"graph path lookup {label}", False, "", None,
                   notes="skipped: no items", skipped=True)

        # A10: Graph delta first page (id-map strategy)
        delta_url = f"{GRAPH_BASE}/drives/{drive_id}/root/delta?$select=id,name,parentReference&$top=100"
        body, status, err = get(delta_url)
        delta_entries = _entries(body)
        record(f"A10-{tag}", f"graph delta first page {label}", body is not None, delta_url, body, status,
               f"{len(delta_entries)} entries; nextLink: {next_link(body) is not None}"
               + (f"; error: {err}" if err else ""))

    # -- A9: site groups + logged-in user membership (explains the m0 T4 403) ----------
    try:
        groups_url = f"{site_url}/_api/web/sitegroups?$top=200"
        body, status, err = get(groups_url)
        groups = [e for e in _entries(body) if isinstance(e, Mapping)]
        memberships: list[str] = []
        group_errors = 0
        for g in groups:
            gid = g.get("Id")
            gtitle = str(g.get("Title") or f"group{gid}")
            try:
                users_url = f"{site_url}/_api/web/sitegroups({gid})/users?$top=500"
                ubody, _, _ = get(users_url)
                for u in _entries(ubody):
                    if not isinstance(u, Mapping):
                        continue
                    email = str(u.get("Email") or "").lower()
                    login = str(u.get("LoginName") or "").lower()
                    if upn and (upn in email or upn in login):
                        memberships.append(gtitle)
                        break
            except Exception:
                group_errors += 1
        record("A9", "site groups + logged-in user membership", bool(groups), groups_url, None, status,
               f"{len(groups)} groups; '{upn}' is member of: "
               f"{memberships or 'NONE'}; failed group reads: {group_errors}"
               + (f"; error: {err}" if err else ""))
    except Exception as error:
        record("A9", "site groups + logged-in user membership", False, "", None, notes=f"unexpected: {error}")

    # -- summary ------------------------------------------------------------------------
    critical_failures = [
        r["test"] for r in results
        if r["critical"] and not r["ok"] and not r.get("skipped")
    ]
    summary = {
        "logged_in_as": upn,
        "total": len(results),
        "passed": sum(1 for r in results if r["ok"]),
        "failed": sum(1 for r in results if not r["ok"] and not r.get("skipped")),
        "skipped": sum(1 for r in results if r.get("skipped")),
        "critical_failed": critical_failures,
    }
    payload = {"generated_at": _now(), "site_url": site_url, "summary": summary, "results": results}
    out_path = Path(args.json_out)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print()
    print("=" * 76)
    for r in results:
        marker = "SKIP" if r.get("skipped") else ("PASS" if r["ok"] else ("FAIL*" if r["critical"] else "FAIL"))
        print(f"{r['test']:<8}{marker:<7}{r['title']}")
    print("=" * 76)
    print(f"Results written to {out_path}")
    print(f"Summary: {summary['passed']}/{summary['total']} passed"
          + (f"; CRITICAL failures: {critical_failures}" if critical_failures else ""))
    return 0 if not critical_failures else 2


if __name__ == "__main__":
    sys.exit(main())
