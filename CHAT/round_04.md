# Round 04 — 2026-11-27

## 你的两个问题（详细解答）

### 1. 为什么需要管理员权限？是否必须？

**不是必须的。** 之前弹的 `Sites.FullControl.All` 是微软 Graph 的**租户级**
权限（"对所有站点集合完全控制"——覆盖 Danfoss 全部站点），所以微软强制
要求管理员审批。你拒绝是对的。

M3 真正需要的写操作只有三类，逐类的**免管理员**方案：

| 操作 | 方案 | 管理员 |
| --- | --- | --- |
| 删直接授权/撤链接（Graph） | `Files.ReadWrite`——微软文档的最小权限，**用户自己同意即可**，范围仅限你有权访问的文件（你是 Owner，TradeSecret 内全部可写） | ❌ |
| 站点组成员移除（REST） | 若 REST 写被 403 → **降级手动清单**（工具输出组名，网页上移除，和 M365 组边界一致） | ❌ |
| REST roleassignments 删除 | 同上；文件/文件夹级已被 Graph 路径覆盖 | ❌ |

长期最优解（有管理员支持时再考虑）：注册自己的 App + `Sites.Selected`，
权限只授予 TradeSecret 单个站点。

**新的 m3_probe 已按此重写**：只申请 `Files.ReadWrite`（用户级同意），
并用"删除不存在的 ID"验证写权限——**404=有写权限 / 403=没有**，
对租户零真实改动。

### 2. yong.hu / xuguifang 权限被清理过一次

**不是这次报错的原因**——报错是：① 同意页要求管理员（权限范围问题，
与账号状态无关）② `plan` 崩溃 = 我的 bug（旧库没自动跑 v2 迁移，**已修复**）。
但它意味着**数据库底账已过时**——所以本轮第一件事是重扫。

## Pi 做了什么（v5.1）

1. 修复：所有读库命令（query/plan/apply/dump/status/verify）打开数据库时
   自动执行 v1→v2 增量迁移（旧数据不丢，旧授权行正确降级为 manual 路径）
2. 重写 m3_probe：Files.ReadWrite 用户级同意 + 三个零改动写权限探测
   （F1 Graph DELETE 假 id / F2 REST DELETE 假 principal / F3 REST POST 假登录名）
3. 38 个离线测试全过

## 需要你（公司电脑）

```powershell
git pull

# 1. 重扫（刷新底账：反映你们已清理的现状 + 自动迁移 schema v2 + 记录 Graph id）
python cli.py scan https://danfoss.sharepoint.com/sites/TradeSecret

# 2. 写权限探测（会弹 Files.ReadWrite 用户级同意页 → 点"接受"，不需要管理员；
#    若你还是不想同意，取消也可以，探测会照常记录 403 结果）
python m3_probe.py https://danfoss.sharepoint.com/sites/TradeSecret

# 3. 重新生成两人的清除方案（基于新底账）
python cli.py plan yong.hu@danfoss.com
python cli.py plan xuguifang@danfoss.com

# 4. 提交回复
git add CHAT m3_probe_results.json plans
git commit -m "round 04 回复"
git push
```

## 用户回复区

（在这行下面写结果/备注；写完保存，然后：
`git add CHAT` → `git commit -m "round 04 回复"` → `git push`）

