"""s3scope CLI — scan / status.

Usage:
    python cli.py scan <site-url> [--db data/governance.sqlite3] [--verbose]
    python cli.py status [--db data/governance.sqlite3]

scan   runs the two-phase permission-scope scan and writes the SQLite baseline.
status prints a read-only summary of the last scan and the stored scopes.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from scan.scanner import run_scan  # noqa: E402
from store.schema import connect, init_schema, schema_status  # noqa: E402

DEFAULT_DB = BASE_DIR / "data" / "governance.sqlite3"


def cmd_scan(args: argparse.Namespace) -> int:
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
    )
    stats = run_scan(args.site_url, args.db)

    print()
    print("=" * 60)
    print(f"站点        {stats['site_title']}")
    obj = stats["objects"]
    print(f"对象        {obj['total']} 个 "
          f"(站点 {obj['site']} / 库 {obj['library']} / 文件夹 {obj['folder']} / 文件 {obj['file']})")
    uniq = stats["unique_scopes"]
    print(f"独立作用域  {uniq['total']} 个 "
          f"(站点 {uniq['site']} / 库 {uniq['library']} / 文件夹 {uniq['folder']} / 文件 {uniq['file']})"
          f"  ← 例外权限")
    print(f"继承率      {stats['inheritance_rate']}%"
          f"  ({stats['inherited_objects']} 个对象未读取权限)")
    print(f"权限读取    {stats['permission_reads']} 次（仅独立作用域）")
    print(f"API 请求    {stats['requests']['total']} 次")
    grants = stats["grants"]
    print(f"授权        角色授权 {grants['role_assignment_rows']} 行 / "
          f"共享链接 {grants['sharing_link_rows']} 条 / "
          f"站点组 {grants['site_groups']} 组 {grants['group_members']} 成员")
    print(f"数据库      {stats['db_path']}")
    print(f"运行        {stats['run_id']}  状态 {stats['status']}  "
          f"耗时 {stats['duration_seconds']}s  错误 {stats['errors']}")
    print("=" * 60)
    return 0 if stats["status"] == "success" else 2


def cmd_status(args: argparse.Namespace) -> int:
    db_path = Path(args.db)
    if not db_path.exists():
        print(f"数据库不存在: {db_path}（先运行 scan）")
        return 1
    conn = connect(db_path)
    try:
        status = schema_status(conn)
        last_run = conn.execute(
            "SELECT run_id, scan_mode, status, started_at, completed_at, stats_json, errors_json "
            "FROM scan_runs ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        print(f"数据库      {db_path}  (schema v{status['schema_version']})")
        if last_run:
            stats = json.loads(last_run["stats_json"] or "{}")
            print(f"最近运行    {last_run['run_id']}  {last_run['status']}  "
                  f"{last_run['started_at']} -> {last_run['completed_at']}")
            if stats:
                print(f"对象/作用域 {stats.get('objects', {}).get('total', '?')} / "
                      f"{stats.get('unique_scopes', {}).get('total', '?')}  "
                      f"(继承率 {stats.get('inheritance_rate', '?')}%)")
                print(f"API 请求    {stats.get('requests', {}).get('total', '?')} 次 "
                      f"(权限读取 {stats.get('permission_reads', '?')} 次)")
            errors = json.loads(last_run["errors_json"] or "[]")
            for error in errors[:5]:
                print(f"  [错误] {error.get('stage')}: {error.get('target')} — {error.get('error')}")
        print(f"存储        作用域 {status['tables']['permission_scopes']} / "
              f"对象 {status['tables']['objects']} / "
              f"角色授权 {status['tables']['role_assignments']} / "
              f"共享链接 {status['tables']['sharing_links']} / "
              f"主体 {status['tables']['principals']} / "
              f"站点组 {status['tables']['site_groups']}")
        top_scopes = conn.execute(
            "SELECT scope_id, scope_type, root_path, inheriting_count FROM permission_scopes "
            "ORDER BY inheriting_count DESC LIMIT 10"
        ).fetchall()
        if top_scopes:
            print("最大作用域 (inheriting_count):")
            for row in top_scopes:
                print(f"  {row['scope_type']:<8}{row['inheriting_count']:>6}  {row['root_path']}")
        return 0
    finally:
        conn.close()


def cmd_dump(args: argparse.Namespace) -> int:
    """Print the database as compact, paste-able text."""
    db_path = Path(args.db)
    if not db_path.exists():
        print(f"数据库不存在: {db_path}（先运行 scan）")
        return 1
    conn = connect(db_path)
    try:
        run = conn.execute(
            "SELECT run_id, status, started_at, completed_at, stats_json FROM scan_runs "
            "ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        if not run:
            print("(no runs)")
            return 0
        stats = json.loads(run["stats_json"] or "{}")
        summary_keys = ("objects", "unique_scopes", "inheritance_rate",
                        "permission_reads", "requests", "grants")
        summary = json.dumps({k: stats.get(k) for k in summary_keys},
                             ensure_ascii=False)
        print(f"RUN {run['run_id']} {run['status']} {run['started_at']} -> {run['completed_at']}")
        print(f"STATS {summary}")

        scopes = conn.execute(
            "SELECT scope_id, scope_type, root_path, inheriting_count, status "
            "FROM permission_scopes ORDER BY scope_type, inheriting_count DESC"
        ).fetchall()
        print(f"\nSCOPES ({len(scopes)})")
        for s in scopes[: args.limit]:
            print(f"  [{s['scope_type']:<7}] {s['root_path']}  "
                  f"inheriting={s['inheriting_count']}  {s['scope_id']}")

        grants = conn.execute(
            "SELECT ra.roles, ps.scope_type, ps.root_path, p.principal_type, "
            "p.email, p.display_name, p.login_name, p.principal_key "
            "FROM role_assignments ra "
            "JOIN permission_scopes ps ON ps.scope_id = ra.scope_id "
            "LEFT JOIN principals p ON p.principal_key = ra.principal_key "
            "ORDER BY ps.scope_type, ps.root_path, p.email"
        ).fetchall()
        print(f"\nGRANTS ({len(grants)})")
        for g in grants[: args.limit]:
            who = (g["email"] or g["display_name"] or g["login_name"]
                   or g["principal_key"] or "?")
            print(f"  [{g['scope_type']:<7}] {g['root_path']}  "
                  f"{who} ({g['principal_type']})  {g['roles']}")

        links = conn.execute(
            "SELECT sl.link_type, sl.link_scope, sl.recipient_count, sl.owner_email, "
            "sl.web_url, sl.expiration, ps.scope_type, ps.root_path "
            "FROM sharing_links sl "
            "JOIN permission_scopes ps ON ps.scope_id = sl.scope_id "
            "ORDER BY ps.root_path"
        ).fetchall()
        print(f"\nLINKS ({len(links)})")
        for l in links[: args.limit]:
            web = str(l["web_url"] or "")[:60]
            print(f"  [{l['scope_type']:<7}] {l['root_path']}  "
                  f"{l['link_type']}/{l['link_scope']}  recipients={l['recipient_count']}  "
                  f"owner={l['owner_email']}  {web}")

        groups = conn.execute(
            "SELECT group_id, group_name FROM site_groups ORDER BY group_id"
        ).fetchall()
        print(f"\nGROUPS ({len(groups)})")
        for grp in groups:
            members = conn.execute(
                "SELECT member_email, member_name, member_login FROM site_group_members "
                "WHERE group_id = ? ORDER BY member_email",
                (grp["group_id"],),
            ).fetchall()
            shown = ", ".join(
                m["member_email"] or m["member_name"] or m["member_login"] or "?"
                for m in members[: args.limit]
            )
            suffix = f" ... (+{len(members) - args.limit})" if len(members) > args.limit else ""
            print(f"  {grp['group_name']} ({grp['group_id']}): {shown}{suffix}")
        return 0
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="s3scope", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    scan_parser = sub.add_parser("scan", help="两阶段作用域扫描 -> SQLite 底账")
    scan_parser.add_argument("site_url", help="https://<tenant>.sharepoint.com/sites/<site>")
    scan_parser.add_argument("--db", default=str(DEFAULT_DB))
    scan_parser.add_argument("--verbose", action="store_true")
    scan_parser.set_defaults(func=cmd_scan)

    status_parser = sub.add_parser("status", help="数据库只读概况")
    status_parser.add_argument("--db", default=str(DEFAULT_DB))
    status_parser.set_defaults(func=cmd_status)

    dump_parser = sub.add_parser(
        "dump", help="数据库内容转文本（可直接粘贴分享/推送）")
    dump_parser.add_argument("--db", default=str(DEFAULT_DB))
    dump_parser.add_argument("--limit", type=int, default=100,
                             help="每节最多输出行数（默认 100）")
    dump_parser.set_defaults(func=cmd_dump)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
