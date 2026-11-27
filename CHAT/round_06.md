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

(ts-governance) PS C:\Python_Projects\Pi\Pi-Trade-Secret> python cli.py verify xuguifang@danfoss.com https://danfoss.sharepoint.com/sites/TradeSecret
2026-11-27 15:14:14,584 INFO    [AUTH] Loading token cache: C:\Python_Projects\Pi\Pi-Trade-Secret\.cache\msal_cache.bin
2026-11-27 15:14:15,136 INFO    [AUTH] Attempting silent authentication (scopes=['Sites.Read.All'])...
2026-11-27 15:14:15,629 INFO    [AUTH] Token acquired (audience=00000003-0000-0000-c000-000000000000, user=yong.hu@danfoss.com).
2026-11-27 15:14:16,345 INFO    [AUTH] Attempting silent authentication (scopes=['https://danfoss.sharepoint.com/.default'])...
2026-11-27 15:14:16,814 INFO    [AUTH] Token acquired (audience=00000003-0000-0ff1-ce00-000000000000, user=yong.hu@danfoss.com).
2026-11-27 15:14:18,678 INFO    [SCAN] site=Trade Secret libraries=2
2026-11-27 15:14:21,095 INFO    [SCAN] library 'Documents' items=2 unique=False
2026-11-27 15:14:23,439 INFO    [SCAN] library 'Trade Secret Library' items=114 unique=True
2026-11-27 15:14:30,485 INFO    [SCAN] site groups=10
2026-11-27 15:14:31,483 INFO    [SCAN] delta map 'Documents': 3 entries
2026-11-27 15:14:32,481 INFO    [SCAN] delta map 'Trade Secret Library': 98 entries
2026-11-27 15:14:42,702 INFO    [SCAN] done run=20261127T071414_e7e912 status=success objects=119 unique=9 requests=32
2026-11-27 15:14:42,707 INFO    [VERIFY] xuguifang@danfoss.com residual=True after={'direct_grants': 3, 'real_group_memberships': 0, 'link_recipient': 1, 'link_owner': 0}
================================================================
验证        xuguifang@danfoss.com
清除前      {'direct_grants': 3, 'real_group_memberships': 1, 'link_recipient': 1, 'link_owner': 0}
清除后      {'direct_grants': 3, 'real_group_memberships': 0, 'link_recipient': 1, 'link_owner': 0}
复扫        20261127T071414_e7e912 (success, 32 请求)
结论        仍有残留：
  [直接授权] folder:/sites/TradeSecret/Trade Secret Library/02_NPD (write)
  [直接授权] folder:/sites/TradeSecret/Trade Secret Library/Automatic File Categorization (write)
  [直接授权] file:/sites/TradeSecret/Trade Secret Library/Confidential/Test_Permission.docx (read)
  [组成员]   SharingLinks.ad5161b1-081a-403e-9819-b726cee977c9.Flexible.09ce0264-a0ca-4890-8497-838c3c021684
  [组成员]   Limited Access System Group For List 66d491e7-961a-4103-bf06-f9fa351f66cb
  [组成员]   Limited Access System Group For Web 59b88f73-04fc-4796-ba10-7da00955d81d
  [链接]     /sites/TradeSecret/Trade Secret Library/Automatic File Categorization view/users
================================================================
(ts-governance) PS C:\Python_Projects\Pi\Pi-Trade-Secret>   扫描结果没有问题验证后确实还存在{'direct_grants': 3, 'real_group_memberships': 0, 'link_recipient': 1, 'link_owner': 0}，组成员如果没有权限你可以不管，我手动就是，但是为什么直接授权和链接你不清理，还是你在实验？现在我认为确实应该创建数据库，便于后续开发前端查询某个成员权限，显示清理前后变化，或者你有更好的想法也可以讲出来

