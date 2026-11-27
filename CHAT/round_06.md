# Round 06 — 2026-11-27

## Pi 做了什么（v6.1）

1. **修复 verify 崩溃**（`init_schema` 忘记导入——你的报错原因）
2. **修复两个更深的验证缺陷**（修复过程中发现）：
   - 重扫后旧授权行不会自动消失（upsert 只更新不删除），verify 之前对比的是
     "历史累计"而非"当前状态" → 现在所有查询按 **最新一次扫描** 过滤
     （`last_seen_run_id`），反映真实的当前权限状态
   - 同秒两次扫描的排序歧义 → 用插入顺序稳定排序
3. 端到端验证：模拟"授权被移除后复扫" → verify 正确显示
   before=1 → after=0 → residual=False。**闭环语义正确**。

## 你的演练状态

你已完成：从 TS-L2 组移除 xuguifang ✓
（他还有 3 处直接授权 + 1 条链接未处理，属预期——一次演练做一项即可）

## 需要你（公司电脑）

```powershell
git pull

# 重新验证（会复扫一次，然后对比前后状态）
python cli.py verify xuguifang@danfoss.com https://danfoss.sharepoint.com/sites/TradeSecret

# 预期结果：
#   清除前 real_group_memberships: 1 (TS-L2) / direct_grants: 3 / link: 1
#   清除后 real_group_memberships: 0        ← TS-L2 移除被检测到！
#   结论"仍有残留"是正确的（直接授权和链接还在）
#   把输出贴到下面推回来

git add CHAT
git commit -m "round 06 回复"
git push
```

> 这个输出是论文闭环实证的第一个真实数据：**手动移除 → 复扫 → 状态变化
> 被系统检测**。之后可以继续把 3 处直接授权和链接也清掉，跑出
> "零残留"的完整案例。

## 用户回复区

（在这行下面写结果/备注；写完保存，然后：
`git add CHAT` → `git commit -m "round 06 回复"` → `git push`）

