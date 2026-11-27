# Round 02 — 2026-11-27

## Pi 做了什么（v4.2）

1. **修复扫描 bug**：你上次扫描是 partial（8/9 权限读取），原因是
   `Test_Permission.docx` 不在 Graph delta 的 id 映射里。现在 delta 缺项时
   自动回退到路径寻址端点补读（离线测试已模拟这个场景，29 个测试全过）。
2. **M2 已确认工作正常**：你贴的 yong.hu / xuguifang 两个查询结果完全正确
   （系统组排除、多人链接判断、通过组覆盖统计都对）。
3. **新增 `m3_probe.py`**：M3 清除闭环的前置探测——申请 FullControl 授权、
   复测之前 403 的 REST roleassignments 端点。**只读，无任何写操作。**

## 需要你（公司电脑）

```powershell
git pull

# 1. 重扫（应显示 success 而不是 partial；权限读取应为 9 次）
python cli.py scan https://danfoss.sharepoint.com/sites/TradeSecret

# 2. 转储结果到 CHAT 文件夹
python cli.py dump > CHAT\round_02_reply_scan.txt

# 3. M3 前置探测（可能弹一次浏览器授权页 → 点"接受"）
python m3_probe.py https://danfoss.sharepoint.com/sites/TradeSecret

# 4. 提交回复
git add CHAT m3_probe_results.json
git commit -m "round 02 回复"
git push
```

> 第 3 步如果弹出授权页面，勾选/接受即可；如果提示需要管理员同意而被拒，
> 也照常提交——探测脚本会记录失败情况，M3 会改走纯 Graph 清除路线。

## 用户回复区

（在这行下面写结果/备注；写完保存，然后：
`git add CHAT` → `git commit -m "round 02 回复"` → `git push`）

