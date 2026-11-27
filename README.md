# s3scope — SharePoint Permission Scope Governance

Trade Secret Governance S3 的后继项目：以 `HasUniqueRoleAssignments` 为分界的
两阶段权限扫描与治理闭环（发现作用域 → 只展开独立权限对象 → 邮箱查询 →
一键剔除 → 零残留验证）。

前身 `Trade-Secret-TS-Governance-main` 保留为性能对照基准，不再演进。
迁移资产：TokenSession（多受众 MSAL 认证）、白名单 HTTP 客户端模式、
快照 diff 概念、`PRAGMA user_version` 增量迁移纪律。

目标、边界与验收标准见 **GOALS.md**。

## 项目结构

```
s3scope/
├── cli.py                  # scan / query / plan / apply / verify / status / dump
├── core/                   # auth (TokenSession) + http (ScHttpClient) + parse
├── scan/                   # Phase 1 作用域发现 + Phase 2 独立对象展开 + 落库
├── query/                  # 邮箱 → 授权清单
├── remediate/              # plan（含手动深链接）/ apply / verify
├── store/                  # SQLite schema v2（增量迁移）
├── probes/                 # 租户端点/写权限探测脚本（m0 / m0b / m3_probe）
├── results/                # 探针结果与扫描转储（证据存档）
├── plans/                  # 生成的清除方案 JSON
├── tools/                  # 辅助工具（build_ppt.py）
├── CHAT/                   # Pi 协作通道（round_NN.md + archive/）
└── tests/                  # 39 个离线测试
```

运行模型（三层，详见 GOALS.md）：层 1 只读闭环今天可用；层 2 文件/链接级
自动清除待一次管理员同意；组移除手动（深链接直达）。

## 当前状态：v6.0 — 分层执行模型定稿

| 组件 | 状态 |
| --- | --- |
| `core/auth.py` TokenSession（Graph + 站点资源双受众、静默优先、一次交互回退） | 完成 |
| `core/http.py` ScHttpClient（白名单 / 401 续期 / 429 退避 / 分页 / 写动词） | 完成 |
| `store/schema.py` Scope 十二表 + `user_version` 增量迁移 | 完成 |
| m0 / m0b 端点验证（真实租户已确认） | 完成 |
| `scan/` Phase 1 作用域发现 + Phase 2 独立对象展开 + 落库 | 完成（v3.0） |
| `cli.py` scan / status | 完成 |
| `query/` 邮箱 → 授权清单 | 完成（v4.0） |
| `remediate/` plan / apply / verify | M3 |

## 快速开始

```powershell
conda activate s3scope

# 1. 扫描（首次会打开浏览器登录；生成 data/governance.sqlite3）
python .\cli.py scan https://<tenant>.sharepoint.com/sites/<site>

# 2. 数据库概况（离线，只读）
python .\cli.py status

# 3. 离线测试（无需登录）
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
| v3.0 | M1 两阶段扫描器：scan/ + cli.py + parse（见 RELEASE_LOG.txt） |
| v3.1 | cli.py dump：数据库转结构化文本（便于粘贴分享） |
| v4.0 | M2 查询：cli.py query <email> 授权清单+清除建议（见 RELEASE_LOG.txt） |

之后：大版本对应里程碑（v3.0 = M1 扫描器、v4.0 = M2 查询、v5.0 = M3 清除闭环、v6.0 = M4 对照），小版本（v2.2…）为里程碑内的增量推送。
