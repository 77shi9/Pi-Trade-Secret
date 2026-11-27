# Round 03 — 2026-11-27

## Pi 做了什么（v5.0 = M3 清除闭环）

1. **修复扫描 bug 已确认**：你上次重扫 success / 9 次权限读取 / 63 行授权 /
   0 错误，`Test_Permission.docx` 上 4 个直接用户授权已入库。
2. **M3 完成**：清除闭环三件套
   - `python cli.py plan <email>` → 生成操作清单 JSON（离线，含 Graph/REST
     双路径所需的全部 ID）
   - `python cli.py apply <plan.json> <site-url>` → **默认 dry-run 零写操作**；
     加 `--apply` 才真正执行（REST 写自动取 request digest，每步写审计日志）
   - `python cli.py verify <email> <site-url>` → 复扫 + 重查 + diff → 零残留报告
3. Schema v2 增量迁移（旧库自动升级，数据不丢）；m3_probe 修复 + 备用同意路径。
   38 个离线测试全过。

## 需要你（公司电脑）

```powershell
git pull

# 1. M3 前置探测（上次的导入错误已修复；可能弹授权页 → 接受）
python m3_probe.py https://danfoss.sharepoint.com/sites/TradeSecret

# 2. 生成清除方案（dry-run 源，纯离线，安全）
python cli.py plan xuguifang@danfoss.com
python cli.py plan yong.hu@danfoss.com

# 3. 提交回复（包含 probe 结果和两个方案的输出）
git add CHAT m3_probe_results.json plans
git commit -m "round 03 回复"
git push
```

> **先不要跑 apply --apply**。等你把 probe 结果和方案贴回来，我确认
> Graph/REST 写路径的可行性后，下一轮再设计一次真实的小规模清除演练
> （建议目标：一个测试账号或 Test_Permission.docx 上的某个授权）。

## 用户回复区

（在这行下面写结果/备注；写完保存，然后：
`git add CHAT` → `git commit -m "round 03 回复"` → `git push`）

