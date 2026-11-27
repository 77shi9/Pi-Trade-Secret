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

(ts-governance) PS C:\Python_Projects\Pi\Pi-Trade-Secret> python cli.py scan https://danfoss.sharepoint.com/sites/TradeSecret
2026-11-27 10:19:33,127 INFO    [AUTH] Loading token cache: C:\Python_Projects\Pi\Pi-Trade-Secret\.cache\msal_cache.bin
2026-11-27 10:19:33,634 INFO    [AUTH] Attempting silent authentication (scopes=['Sites.Read.All'])...
2026-11-27 10:19:33,638 INFO    [AUTH] Token acquired (audience=00000003-0000-0000-c000-000000000000, user=yong.hu@danfoss.com).
2026-11-27 10:19:34,762 INFO    [AUTH] Attempting silent authentication (scopes=['https://danfoss.sharepoint.com/.default'])...
2026-11-27 10:19:35,280 INFO    [AUTH] Token acquired (audience=00000003-0000-0ff1-ce00-000000000000, user=yong.hu@danfoss.com).
2026-11-27 10:19:37,990 INFO    [SCAN] site=Trade Secret libraries=2
2026-11-27 10:19:39,936 INFO    [SCAN] library 'Documents' items=2 unique=False
2026-11-27 10:19:42,648 INFO    [SCAN] library 'Trade Secret Library' items=114 unique=True
2026-11-27 10:19:50,361 INFO    [SCAN] site groups=10
2026-11-27 10:19:51,727 INFO    [SCAN] delta map 'Documents': 3 entries
2026-11-27 10:19:52,698 INFO    [SCAN] delta map 'Trade Secret Library': 98 entries
2026-11-27 10:20:01,893 INFO    [SCAN] done run=20261127T021933_f657fb status=success objects=119 unique=9 requests=32

============================================================
站点        Trade Secret
对象        119 个 (站点 1 / 库 2 / 文件夹 36 / 文件 80)
独立作用域  9 个 (站点 1 / 库 1 / 文件夹 6 / 文件 1)  ← 例外权限
继承率      92.4%  (110 个对象未读取权限)
权限读取    9 次（仅独立作用域）
API 请求    32 次
授权        角色授权 63 行 / 共享链接 1 条 / 站点组 10 组 18 成员
数据库      C:\Python_Projects\Pi\Pi-Trade-Secret\data\governance.sqlite3
运行        20261127T021933_f657fb  状态 success  耗时 28.8s  错误 0
============================================================

(ts-governance) PS C:\Python_Projects\Pi\Pi-Trade-Secret> python m3_probe.py https://danfoss.sharepoint.com/sites/TradeSecret
Traceback (most recent call last):
  File "C:\Python_Projects\Pi\Pi-Trade-Secret\m3_probe.py", line 35, in <module>
    from core.parse import _excerpt, _first_entry  # noqa: E402
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
ImportError: cannot import name '_excerpt' from 'core.parse' (C:\Python_Projects\Pi\Pi-Trade-Secret\core\parse.py)