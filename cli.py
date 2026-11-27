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


def cmd_query(args: argparse.Namespace) -> int:
    db_path = Path(args.db)
    if not db_path.exists():
        print(f"数据库不存在: {db_path}（先运行 scan）")
        return 1
    conn = connect(db_path)
    try:
        from query.offboarding import query_grants, remediation_hints, via_group_summary

        report = query_grants(conn, args.email)
        hints = remediation_hints(report)
        via = via_group_summary(report)

        print("=" * 64)
        print(f"查询        {report['email']}")
        print(f"直接授权    {len(report['direct_grants'])} 处")
        for g in report["direct_grants"]:
            print(f"  [{g['scope_type']:<7}] {g['root_path']}  {g['roles']}")

        print(f"站点组成员  {len(report['site_group_memberships'])} 个")
        for m in report["site_group_memberships"]:
            flag = " [系统组]" if m["is_system"] else (" [默认组]" if m["is_default_group"] else "")
            print(f"  {m['group_name']} ({m['group_id']}){flag}")

        print(f"共享链接    {len(report['sharing_links'])} 处")
        for l in report["sharing_links"]:
            role_bits = []
            if l["is_recipient"]:
                role_bits.append("收件人" + ("(多人)" if l["multi_recipient"] else "(唯一)"))
            if l["is_owner"]:
                role_bits.append("创建者")
            print(f"  [{l['scope_type']:<7}] {l['root_path']}  "
                  f"{l['link_type']}/{l['link_scope']}  {'/'.join(role_bits)}")

        if report["m365_group_memberships"]:
            print(f"M365 组     {len(report['m365_group_memberships'])} 个（建议人工处理）")
            for m in report["m365_group_memberships"]:
                print(f"  {m['group_name'] or m['group_key']}")

        print(f"通过组访问  {len(report['via_group_access'])} 个作用域（来自 {len(via)} 个组）")
        for row in via[:10]:
            print(f"  {row['group']} -> {row['roles']} 于 {row['scope_count']} 个作用域"
                  f"（覆盖 {row['inheriting_objects']} 个对象）")

        print(f"\n清除建议（M3 预览，共 {len(hints)} 项）")
        for i, h in enumerate(hints, 1):
            target = h.get("scope_path") or h.get("group") or h.get("link") or ""
            note = f"  {h.get('note') or h.get('roles') or ''}" if (h.get("note") or h.get("roles")) else ""
            print(f"  {i:>2}. {h['action']:<32} {target}{note}")
        print("=" * 64)

        if args.json:
            payload = {**report, "remediation_hints": hints,
                       "via_group_summary": via}
            Path(args.json).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"JSON 已写入 {args.json}")
        return 0
    finally:
        conn.close()


def cmd_plan(args: argparse.Namespace) -> int:
    db_path = Path(args.db)
    if not db_path.exists():
        print(f"数据库不存在: {db_path}（先运行 scan）")
        return 1
    conn = connect(db_path)
    try:
        from remediate.plan import build_plan

        plan = build_plan(conn, args.email)
    finally:
        conn.close()

    print("=" * 64)
    print(f"清除方案    {plan['target_email']}  ({plan['operation_id']})")
    print(f"数据源      扫描 {plan['source_run_id']}")
    print(f"操作        {plan['summary']['total']} 项，其中可自动执行 "
          f"{plan['summary']['executable']} 项")
    for i, op in enumerate(plan["operations"], 1):
        target = (op.get("path") or op.get("group") or op.get("link")
                  or op.get("principal_email") or "")
        method = op.get("method", "-")
        extra = op.get("note") or op.get("roles") or ""
        print(f"  {i:>3}. {op['op']:<34} [{method:<6}] {target} {extra}")
    print("=" * 64)
    print("提示: python cli.py apply <plan.json> 预览执行；加 --apply 才真正写入")

    out = Path(args.out) if args.out else Path("plans") / f"{plan['operation_id']}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(plan, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(f"方案已写入 {out}")
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    db_path = Path(args.db)
    plan_path = Path(args.plan_file)
    if not db_path.exists() or not plan_path.exists():
        print(f"缺少文件: {db_path} / {plan_path}")
        return 1
    plan = json.loads(plan_path.read_text(encoding="utf-8"))

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s")
    conn = connect(db_path)
    try:
        from remediate.apply import execute_plan

        if not args.apply:
            print(f"=" * 64)
            print(f"预览（dry-run）  {plan['target_email']}  "
                  f"({plan['operation_id']}) — 不会执行任何写操作")
        else:
            print(f"=" * 64)
            print(f"正式执行        {plan['target_email']}  "
                  f"({plan['operation_id']})")
        summary = execute_plan(plan, conn, args.site_url,
                               apply_changes=args.apply)
        print(f"=" * 64)
        print(f"执行 {summary['executed']} 项: 成功 {summary['ok']} / "
              f"失败 {summary['failed']} / 跳过 {summary['skipped']}")
        for failure in summary["failed_details"]:
            print(f"  [失败] {failure['op']} {failure['target']}: {failure['error']}")
        if summary["failed"] == 0 and summary["ok"] > 0:
            print("下一步: python cli.py verify <email> 验证零残留")
        return 0 if summary["failed"] == 0 else 2
    finally:
        conn.close()


def cmd_verify(args: argparse.Namespace) -> int:
    db_path = Path(args.db)
    if not db_path.exists():
        print(f"数据库不存在: {db_path}（先运行 scan）")
        return 1
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s")
    from remediate.verify import verify_user

    result = verify_user(args.site_url, str(db_path), args.email)
    print("=" * 64)
    print(f"验证        {result['email']}")
    print(f"清除前      {result['before']}")
    print(f"清除后      {result['after']}")
    print(f"复扫        {result['scan']['run_id']} ({result['scan']['status']}, "
          f"{result['scan']['requests']} 请求)")
    if result["residual"]:
        print("结论        仍有残留：")
        for item in result["after_details"]["direct_grants"]:
            print(f"  [直接授权] {item}")
        for item in result["after_details"]["group_memberships"]:
            print(f"  [组成员]   {item}")
        for item in result["after_details"]["links"]:
            print(f"  [链接]     {item}")
        print("=" * 64)
        return 2
    print("结论        零残留（直接授权 / 组成员 / 链接收件人全部清零）")
    print("=" * 64)
    return 0


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

    query_parser = sub.add_parser("query", help="邮箱 -> 完整授权清单（离线）")
    query_parser.add_argument("email")
    query_parser.add_argument("--db", default=str(DEFAULT_DB))
    query_parser.add_argument("--json", default=None, help="可选：同时写入 JSON 文件")
    query_parser.set_defaults(func=cmd_query)

    plan_parser = sub.add_parser("plan", help="邮箱 -> 清除方案（dry-run 源，离线）")
    plan_parser.add_argument("email")
    plan_parser.add_argument("--db", default=str(DEFAULT_DB))
    plan_parser.add_argument("--out", default=None, help="方案 JSON 输出路径")
    plan_parser.set_defaults(func=cmd_plan)

    apply_parser = sub.add_parser("apply", help="执行清除方案（默认 dry-run，--apply 才写入）")
    apply_parser.add_argument("plan_file", help="plan 生成的 JSON 文件")
    apply_parser.add_argument("site_url", help="https://<tenant>.sharepoint.com/sites/<site>")
    apply_parser.add_argument("--db", default=str(DEFAULT_DB))
    apply_parser.add_argument("--apply", action="store_true",
                              help="真正执行写操作（默认仅预览）")
    apply_parser.set_defaults(func=cmd_apply)

    verify_parser = sub.add_parser("verify", help="清除后复扫 + 零残留验证")
    verify_parser.add_argument("email")
    verify_parser.add_argument("site_url")
    verify_parser.add_argument("--db", default=str(DEFAULT_DB))
    verify_parser.set_defaults(func=cmd_verify)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
