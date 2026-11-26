"""M0 endpoint validation for s3scope.

Run once with a real login (Site Owner account):

    python m0_validate.py https://<tenant>.sharepoint.com/sites/<site>

Validates, against the real tenant:

  T1   SharePoint site-resource token + web select incl. HasUniqueRoleAssignments
  T2   libraries: combined $select (Id/Title/BaseType/Hidden + flag) with $expand
  T2b  single library $select fallback
  T2c  library root folder $select fallback
  T3   list items $select with HasUniqueRoleAssignments   <-- CRITICAL for Phase 1
  T4   roleassignments?$expand=RoleDefinitionBindings,Member <-- CRITICAL for Phase 2
  T5a-d  Graph chain: site -> drives -> children -> permissions (sharing links)
  T6   token claims (audience / scopes diagnostics)

Writes ``m0_results.json`` next to this script. Tokens are never written;
response bodies are truncated to 600 characters to keep the file small.

Exit codes: 0 = all critical tests passed; 2 = partial failures; 1 = fatal.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from core.auth import TokenSession  # noqa: E402
from core.http import RequestError, ScHttpClient  # noqa: E402

LOGGER = logging.getLogger("s3scope.m0")
GRAPH_BASE = "https://graph.microsoft.com/v1.0"
EXCERPT_LIMIT = 600
CRITICAL_TESTS = ("T1", "T3", "T4", "T5d")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _excerpt(body: Any, limit: int = EXCERPT_LIMIT) -> str:
    if body is None:
        return ""
    try:
        text = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
    except Exception:
        text = str(body)
    text = text or ""
    return text[:limit] + ("...[truncated]" if len(text) > limit else "")


def _entries(body: Any) -> list[Any]:
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


def _entity(body: Any) -> Mapping[str, Any]:
    """Single entity from verbose ({"d": {...}}) or minimalmetadata (flat) body."""
    if isinstance(body, Mapping):
        nested = body.get("d")
        if isinstance(nested, Mapping):
            return nested
    return body if isinstance(body, Mapping) else {}


def _first_entry(body: Any) -> Mapping[str, Any] | None:
    for entry in _entries(body):
        if isinstance(entry, Mapping):
            return entry
    return None


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes")
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="M0 endpoint validation for s3scope")
    parser.add_argument("site_url", help="e.g. https://<tenant>.sharepoint.com/sites/<site>")
    parser.add_argument("--json-out", default=str(BASE_DIR / "m0_results.json"))
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
    ) -> None:
        results.append(
            {
                "test": test,
                "title": title,
                "critical": test in CRITICAL_TESTS,
                "ok": bool(ok),
                "status": status,
                "url": url,
                "excerpt": _excerpt(body),
                "notes": notes,
            }
        )
        marker = "PASS" if ok else "FAIL"
        LOGGER.info("[%s] %s %s | %s", marker, test, title, notes)

    def get(url: str) -> tuple[Any, int | None, str | None]:
        try:
            return client.get_json(url), 200, None
        except RequestError as error:
            return None, error.status, str(error)

    # -- login up front so no browser prompt appears mid-tests ----------------
    try:
        session.get_token(("Sites.Read.All",))
        session.get_token([f"https://{host}/.default"])
    except Exception as error:
        print(f"[FATAL] Authentication failed: {error}")
        return 1

    # -- T1: web ----------------------------------------------------------------
    try:
        url = f"{site_url}/_api/web?$select=Id,Title,ServerRelativeUrl,HasUniqueRoleAssignments"
        body, status, err = get(url)
        web = _entity(body)
        ok = bool(web.get("Id"))
        record(
            "T1",
            "web select incl. HasUniqueRoleAssignments",
            ok,
            url,
            body,
            status,
            "site unique permissions: "
            f"{_truthy(web.get('HasUniqueRoleAssignments'))}"
            + (f"; error: {err}" if err else ""),
        )
    except Exception as error:  # unexpected, keep going
        record("T1", "web select incl. HasUniqueRoleAssignments", False, "", None, notes=f"unexpected: {error}")

    # -- T2: libraries (combined select) -----------------------------------------
    lib_guid: str | None = None
    try:
        url = (
            f"{site_url}/_api/web/lists?$top=200"
            "&$select=Id,Title,BaseType,Hidden,HasUniqueRoleAssignments,RootFolder/ServerRelativeUrl"
            "&$expand=RootFolder"
        )
        body, status, err = get(url)
        entries = [e for e in _entries(body) if isinstance(e, Mapping)]
        libraries = [
            e for e in entries
            if str(e.get("BaseType")) == "101" and not _truthy(e.get("Hidden"))
        ]
        first = libraries[0] if libraries else (entries[0] if entries else None)
        lib_guid = (first or {}).get("Id")
        ok = first is not None and "HasUniqueRoleAssignments" in first
        record(
            "T2",
            "libraries combined $select with flag + $expand=RootFolder",
            ok,
            url,
            body,
            status,
            f"{len(entries)} lists ({len(libraries)} doc libraries); flag present: {ok}"
            + (f"; error: {err}" if err else ""),
        )
    except Exception as error:
        record("T2", "libraries combined $select", False, "", None, notes=f"unexpected: {error}")

    # -- T2b: single library select ----------------------------------------------
    if lib_guid:
        url = f"{site_url}/_api/web/lists('{lib_guid}')?$select=Id,Title,HasUniqueRoleAssignments"
        body, status, err = get(url)
        lib = _entity(body)
        ok = "HasUniqueRoleAssignments" in lib
        record(
            "T2b",
            "single library $select fallback",
            ok,
            url,
            body,
            status,
            f"flag present: {ok}; library unique: {_truthy(lib.get('HasUniqueRoleAssignments'))}"
            + (f"; error: {err}" if err else ""),
        )
    else:
        record("T2b", "single library $select fallback", False, "", None, notes="skipped: no library guid from T2")

    # -- T2c: library root folder select -------------------------------------------
    if lib_guid:
        url = f"{site_url}/_api/web/lists('{lib_guid}')/rootfolder?$select=ServerRelativeUrl,HasUniqueRoleAssignments"
        body, status, err = get(url)
        folder = _entity(body)
        ok = "HasUniqueRoleAssignments" in folder
        record(
            "T2c",
            "library rootfolder $select fallback",
            ok,
            url,
            body,
            status,
            f"flag present: {ok}; root unique: {_truthy(folder.get('HasUniqueRoleAssignments'))}"
            + (f"; error: {err}" if err else ""),
        )
    else:
        record("T2c", "library rootfolder $select fallback", False, "", None, notes="skipped: no library guid from T2")

    # -- T3: items with HasUniqueRoleAssignments (CRITICAL) ------------------------
    sample_items: list[Mapping[str, Any]] = []
    if lib_guid:
        url = (
            f"{site_url}/_api/web/lists('{lib_guid}')/items"
            "?$top=25&$select=Id,FSObjType,FileRef,FileLeafRef,HasUniqueRoleAssignments"
        )
        body, status, err = get(url)
        sample_items = [e for e in _entries(body) if isinstance(e, Mapping)]
        first = sample_items[0] if sample_items else None
        flag_present = first is not None and "HasUniqueRoleAssignments" in first
        unique_count = sum(1 for e in sample_items if _truthy(e.get("HasUniqueRoleAssignments")))
        record(
            "T3",
            "list items $select with HasUniqueRoleAssignments (CRITICAL Phase 1)",
            flag_present,
            url,
            body,
            status,
            f"{len(sample_items)} items sampled; flag present: {flag_present}; unique in sample: {unique_count}"
            + (f"; error: {err}" if err else ""),
        )
    else:
        record(
            "T3",
            "list items $select with HasUniqueRoleAssignments (CRITICAL Phase 1)",
            False,
            "",
            None,
            notes="skipped: no library guid from T2",
        )

    # -- T4: roleassignments expansion (CRITICAL) -----------------------------------
    unique_item = next(
        (e for e in sample_items if _truthy(e.get("HasUniqueRoleAssignments"))), None
    )
    if unique_item is not None and lib_guid:
        item_id = unique_item.get("Id")
        url = (
            f"{site_url}/_api/web/lists('{lib_guid}')/items({item_id})"
            "/roleassignments?$expand=RoleDefinitionBindings,Member&$top=50"
        )
        label = f"item {item_id} roleassignments (unique-permission item)"
    else:
        url = f"{site_url}/_api/web/roleassignments?$expand=RoleDefinitionBindings,Member&$top=50"
        label = "web roleassignments (fallback: no unique item in sample)"
    try:
        body, status, err = get(url)
        first_ra = _first_entry(body)
        member = first_ra.get("Member") if isinstance(first_ra, Mapping) else None
        member = member if isinstance(member, Mapping) else {}
        bindings = first_ra.get("RoleDefinitionBindings") if isinstance(first_ra, Mapping) else None
        role_names = (
            ";".join(str(b.get("Name")) for b in bindings if isinstance(b, Mapping))
            if isinstance(bindings, list)
            else None
        )
        ok = first_ra is not None
        record(
            "T4",
            f"{label} (CRITICAL Phase 2)",
            ok,
            url,
            body,
            status,
            f"Member.LoginName={member.get('LoginName')}; Member.Id={member.get('Id')}; "
            f"roles={role_names or 'n/a'}"
            + (f"; error: {err}" if err else ""),
        )
    except Exception as error:
        record("T4", "roleassignments expansion", False, "", None, notes=f"unexpected: {error}")

    # -- T5: Graph chain -------------------------------------------------------------
    graph_site_id = None
    try:
        url = f"{GRAPH_BASE}/sites/{host}:{urllib.parse.quote(site_path, safe='/')}"
        body, status, err = get(url)
        site = _entity(body)
        graph_site_id = site.get("id")
        record(
            "T5a",
            "graph site by host:path",
            bool(graph_site_id),
            url,
            body,
            status,
            f"graph site id: {graph_site_id}" + (f"; error: {err}" if err else ""),
        )
    except Exception as error:
        record("T5a", "graph site by host:path", False, "", None, notes=f"unexpected: {error}")

    drive_id = None
    if graph_site_id:
        url = f"{GRAPH_BASE}/sites/{graph_site_id}/drives?$top=20&$select=id,name,driveType,webUrl"
        body, status, err = get(url)
        drives = [e for e in _entries(body) if isinstance(e, Mapping)]
        doc_drives = [e for e in drives if e.get("driveType") == "documentLibrary"]
        chosen_drive = doc_drives[0] if doc_drives else (drives[0] if drives else None)
        drive_id = (chosen_drive or {}).get("id")
        record(
            "T5b",
            "graph drives",
            bool(drive_id),
            url,
            body,
            status,
            f"{len(drives)} drives; chosen: {(chosen_drive or {}).get('name')}"
            + (f"; error: {err}" if err else ""),
        )
    else:
        record("T5b", "graph drives", False, "", None, notes="skipped: no graph site id")

    graph_item_id = None
    if drive_id:
        url = f"{GRAPH_BASE}/drives/{drive_id}/root/children?$top=10&$select=id,name,file,folder"
        body, status, err = get(url)
        children = [e for e in _entries(body) if isinstance(e, Mapping)]
        chosen_item = next(
            (c for c in children if c.get("file") is not None),
            children[0] if children else None,
        )
        graph_item_id = (chosen_item or {}).get("id")
        record(
            "T5c",
            "graph drive root children",
            bool(graph_item_id),
            url,
            body,
            status,
            f"{len(children)} children; chosen: {(chosen_item or {}).get('name')}"
            + (f"; error: {err}" if err else ""),
        )
    else:
        record("T5c", "graph drive root children", False, "", None, notes="skipped: no drive id")

    if drive_id and graph_item_id:
        url = f"{GRAPH_BASE}/drives/{drive_id}/items/{graph_item_id}/permissions"
        body, status, err = get(url)
        perms = [e for e in _entries(body) if isinstance(e, Mapping)]
        notes_parts = [f"{len(perms)} permissions on chosen item"]
        if not perms:
            # a fresh first child may have no links; probe the drive root as backup
            root_url = f"{GRAPH_BASE}/drives/{drive_id}/root/permissions"
            root_body, root_status, root_err = get(root_url)
            root_perms = [e for e in _entries(root_body) if isinstance(e, Mapping)]
            notes_parts.append(f"{len(root_perms)} permissions on drive root (backup probe)")
            if root_perms:
                perms = root_perms
                body, status = root_body, root_status
        first = perms[0] if perms else None
        link = first.get("link") if isinstance(first, Mapping) else None
        link = link if isinstance(link, Mapping) else {}
        ok = body is not None
        record(
            "T5d",
            "graph driveItem permissions / sharing links (CRITICAL link layer)",
            ok,
            url,
            body,
            status,
            "; ".join(notes_parts)
            + f"; link.type={link.get('type')}; link.scope={link.get('scope')}; "
              f"grantedToIdentitiesV2={'grantedToIdentitiesV2' in (first or {})}; "
              f"inheritedFrom={'inheritedFrom' in (first or {})}"
            + (f"; error: {err}" if err else ""),
        )
    else:
        record(
            "T5d",
            "graph driveItem permissions / sharing links (CRITICAL link layer)",
            False,
            "",
            None,
            notes="skipped: no drive/item id",
        )

    # -- T6: token claims ---------------------------------------------------------------
    try:
        graph_claims = session.claims_for(("Sites.Read.All",))
        sp_claims = session.claims_for([f"https://{host}/.default"])

        def safe(claims: dict) -> dict:
            return {k: claims.get(k) for k in ("aud", "scp", "upn", "tid") if claims.get(k) is not None}

        record(
            "T6",
            "token claims (audience / scopes)",
            True,
            "-",
            None,
            None,
            notes=json.dumps({"graph": safe(graph_claims), "sharepoint": safe(sp_claims)}),
        )
    except Exception as error:
        record("T6", "token claims (audience / scopes)", False, "-", None, notes=str(error))

    # -- summary --------------------------------------------------------------------------
    summary = {
        "total": len(results),
        "passed": sum(1 for r in results if r["ok"]),
        "failed": sum(1 for r in results if not r["ok"]),
        "critical_failed": [r["test"] for r in results if r["critical"] and not r["ok"]],
    }
    payload = {
        "generated_at": _now(),
        "site_url": site_url,
        "summary": summary,
        "results": results,
    }
    out_path = Path(args.json_out)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print()
    print("=" * 72)
    for r in results:
        marker = "PASS" if r["ok"] else ("FAIL*" if r["critical"] else "FAIL")
        print(f"{r['test']:<5}{marker:<7}{r['title']}")
    print("=" * 72)
    print(f"Results written to {out_path}")
    print(f"Summary: {summary['passed']}/{summary['total']} passed"
          + (f"; CRITICAL failures: {summary['critical_failed']}" if summary["critical_failed"] else ""))
    return 0 if not summary["critical_failed"] else 2


if __name__ == "__main__":
    sys.exit(main())
