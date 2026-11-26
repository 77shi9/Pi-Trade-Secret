# s3scope — SharePoint Permission Scope Governance

Trade Secret Governance S3 的后继项目：以 `HasUniqueRoleAssignments` 为分界的
两阶段权限扫描与治理闭环（发现作用域 → 只展开独立权限对象 → 邮箱查询 →
一键剔除 → 零残留验证）。

前身 `Trade-Secret-TS-Governance-main` 保留为性能对照基准，不再演进。
迁移资产：TokenSession（多受众 MSAL 认证）、白名单 HTTP 客户端模式、
快照 diff 概念、`PRAGMA user_version` 增量迁移纪律。

目标、边界与验收标准见 **GOALS.md**。

## 当前状态：M0 — 骨架 + 租户端点验证

| 组件 | 状态 |
| --- | --- |
| `core/auth.py` TokenSession（Graph + 站点资源双受众、静默优先、一次交互回退） | 完成 |
| `core/http.py` ScHttpClient（白名单 / 401 续期 / 429 退避 / 分页 / 写动词） | 完成 |
| `store/schema.py` Scope 十二表 + `user_version` 增量迁移 | 完成 |
| `m0_validate.py` 租户端点验证（唯一需要登录的脚本） | 待运行 |
| `scan/` Phase 1 + Phase 2 扫描器 | M1（取决于 M0 结果） |
| `query/` `remediate/` | M2 / M3 |

## 快速开始

```powershell
conda activate s3scope

# 1. 一次真实登录（会打开浏览器），验证关键端点，写入 m0_results.json
python .\m0_validate.py https://<tenant>.sharepoint.com/sites/<site>

# 2. 离线测试（无需登录）
python -m unittest discover -s tests -v
```

## 依赖

`pip install -r requirements.txt`（msal 必需；pandas/openpyxl 自 M2 起使用）

## 版本约定

每次推送都是一个独立版本（Git tag），永不覆盖。检出任意历史版本：

```powershell
git fetch --tags
git tag -l              # 列出所有版本
git checkout v2.1        # 切换到指定版本
```

| 版本 | 内容 |
| --- | --- |
| v2.0 | M0 骨架：auth/http 核心、Scope 十二表、m0_validate |
| v2.1 | M0b 补测：真实库端点探针、minimalmetadata 分页修复 |

之后：大版本对应里程碑（v3.0 = M1 扫描器、v4.0 = M2 查询、v5.0 = M3 清除闭环、v6.0 = M4 对照），小版本（v2.2…）为里程碑内的增量推送。
