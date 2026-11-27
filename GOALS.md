# S3 Scope Governance — 目标与方向（对齐文档）

## 最终目标

输入一个成员的邮箱 → 系统给出他在 TradeSecret 站点文档库中的全部访问来源
（站点组 / 单独授权 / 分享链接）→ 一键剔除 → 自动验证零残留。

两层价值：

- **治理**：离职/调岗人员清权闭环（查询 → 剔除 → 验证）
- **研究**：证明基于 Permission Scope 的两阶段扫描模型优于全对象遍历模型。
  旧项目 `Trade-Secret-TS-Governance-main` 保留为性能对照基准。

## 技术路线（已锁定）

1. **权限模型**：以 `HasUniqueRoleAssignments` 为分界。Phase 1 只发现作用域
   （ObjectId / Path / Type / UniqueFlag），Phase 2 只对独立权限对象展开
   People / Groups / Links。不再逐文件读权限。
2. **技术栈**：Python 3.11 + msal + stdlib urllib + SQLite；后期 FastAPI + Vue3。
3. **API 分工**：REST 负责作用域发现、roleassignments 展开、组管理、清除写操作；
   Graph 负责共享链接、用户画像、M365 组成员。
4. **工程形态**：CLI 先行出数据；**dry-run 是默认，`--apply` 才执行写操作**；
   一切写操作入审计日志。

## 交付物

1. **治理系统**：scan → query → plan → apply → verify 闭环
2. **研究数据**：新旧模型同站对照（API 请求数 / 墙钟时间 / 权限读取数）
3. **Web 界面**（M5/M6）：FastAPI 读 SQLite + Vue3/Element Plus + ECharts

## 验收标准

1. 输入邮箱，10 秒内返回三类授权完整清单（离线查 SQLite，不调 API）
2. `apply` 后 `verify` 显示该用户站点内零残留（组 / 直接授权 / 指定人链接）
3. 新扫描器请求数显著低于旧 FullAudit（具体倍数 = 站点实测继承率）
4. SQLite 是唯一事实源；报告可离线复现；写操作可回溯审计

## 边界（不做）

- Entra 全局身份治理、全租户访问体系
- Anyone 链接的单人剔除（技术不可行，标记人工决策）
- M365/Entra 组成员自动移除 → 输出建议清单，人工执行（已确认）
- 实时监控、告警、多站点并发（Schema 留 `site_id` 可扩展）

## 里程碑

| 阶段 | 内容 | 状态 |
| --- | --- | --- |
| M0 | 骨架 + 租户端点验证（唯一需要登录的节点） | ✅ 完成（m0 + m0b） |
| M1 | 两阶段扫描器 + Scope 数据库 | ✅ 完成（v3.0，待真实租户验证） |
| M2 | 邮箱 → 授权清单查询 | ✅ 完成（v4.0，待真实数据验证） |
| M3 | plan / apply / verify 清除闭环 | 待开工 |
| M4 | 新旧模型对照（论文数据） | |
| M5/M6 | FastAPI + Vue3 前端（数据稳定后） | |

已确认（2026-11-26）：最终目标一、M365 组按建议输出二、前端后置三。
