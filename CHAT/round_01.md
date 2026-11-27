# Round 01 — 2026-11-27

## Pi 做了什么（累计到 v4.0）

- **v3.0 / v3.1（M1 完成）**：两阶段作用域扫描器 + dump 命令。
  你的真实扫描已成功：119 对象 / 9 独立作用域 / **92.4% 继承率** /
  8 次权限读取（旧模型需 119+ 次）/ 30 次 API 请求 / 52 条授权 / 1 条共享链接。
- **v4.0（M2 完成）**：`python cli.py query <email>` 离线查询授权清单，
  含清除建议预览（M3 前置）。29 个离线测试通过。

## 需要你（公司电脑）

```powershell
git pull
python cli.py query yong.hu@danfoss.com
python cli.py query xuguifang@danfoss.com
python cli.py status
```

把三个命令的输出粘贴到下面的回复区。

> `status` 是关键：你的扫描状态是 **partial**，权限读取 8 次而不是 9 次
> （`Test_Permission.docx` 的授权疑似没读到），我需要错误详情来修复。

## 用户回复区

（在这行下面直接粘贴输出；写完保存，然后：
`git add CHAT` → `git commit -m "round 01 回复"` → `git push`）

(ts-governance) PS C:\Python_Projects\Pi\Pi-Trade-Secret> python cli.py query yong.hu@danfoss.com
================================================================
查询        yong.hu@danfoss.com
直接授权    0 处
站点组成员  8 个
  Trade Secret Owners (3) [默认组]
  TS-L1 Group (12)
  TS-L2 Group (13)
  TS-L3 Group (14)
  TS-L3Plus Group (15)
  SharingLinks.ad5161b1-081a-403e-9819-b726cee977c9.Flexible.09ce0264-a0ca-4890-8497-838c3c021684 (25) [系统组]
  Limited Access System Group For List 66d491e7-961a-4103-bf06-f9fa351f66cb (26) [系统组]
  Limited Access System Group For Web 59b88f73-04fc-4796-ba10-7da00955d81d (27) [系统组]
共享链接    1 处
  [folder ] /sites/TradeSecret/Trade Secret Library/Automatic File Categorization  view/users  收件人(多人)
通过组访问  34 个作用域（来自 5 个组）
  Trade Secret Owners -> owner 于 8 个作用域（覆盖 110 个对象）
  TS-L3Plus Group -> read 于 8 个作用域（覆盖 110 个对象）
  TS-L3 Group -> read 于 7 个作用域（覆盖 103 个对象）
  TS-L2 Group -> read 于 6 个作用域（覆盖 99 个对象）
  TS-L1 Group -> read 于 5 个作用域（覆盖 96 个对象）

清除建议（M3 预览，共 9 项）
   1. remove_site_group_member         Trade Secret Owners
   2. remove_site_group_member         TS-L1 Group
   3. remove_site_group_member         TS-L2 Group
   4. remove_site_group_member         TS-L3 Group
   5. remove_site_group_member         TS-L3Plus Group
   6. skip_system_group                SharingLinks.ad5161b1-081a-403e-9819-b726cee977c9.Flexible.09ce0264-a0ca-4890-8497-838c3c021684  系统管理组，不可手动移除
   7. skip_system_group                Limited Access System Group For List 66d491e7-961a-4103-bf06-f9fa351f66cb  系统管理组，不可手动移除
   8. skip_system_group                Limited Access System Group For Web 59b88f73-04fc-4796-ba10-7da00955d81d  系统管理组，不可手动移除
   9. update_sharing_link_recipients   /sites/TradeSecret/Trade Secret Library/Automatic File Categorization  多人链接：仅移除该用户，保留链接

   ================================================================
   (ts-governance) PS C:\Python_Projects\Pi\Pi-Trade-Secret> python cli.py query xuguifang@danfoss.com
================================================================
查询        xuguifang@danfoss.com
直接授权    2 处
  [folder ] /sites/TradeSecret/Trade Secret Library/02_NPD  write
  [folder ] /sites/TradeSecret/Trade Secret Library/Automatic File Categorization  write
站点组成员  4 个
  TS-L2 Group (13)
  SharingLinks.ad5161b1-081a-403e-9819-b726cee977c9.Flexible.09ce0264-a0ca-4890-8497-838c3c021684 (25) [系统组]
  Limited Access System Group For List 66d491e7-961a-4103-bf06-f9fa351f66cb (26) [系统组]
  Limited Access System Group For Web 59b88f73-04fc-4796-ba10-7da00955d81d (27) [系统组]
共享链接    1 处
  [folder ] /sites/TradeSecret/Trade Secret Library/Automatic File Categorization  view/users  收件人(多人)
通过组访问  6 个作用域（来自 1 个组）
  TS-L2 Group -> read 于 6 个作用域（覆盖 99 个对象）

清除建议（M3 预览，共 7 项）
   1. delete_role_assignment           /sites/TradeSecret/Trade Secret Library/02_NPD  write
   2. delete_role_assignment           /sites/TradeSecret/Trade Secret Library/Automatic File Categorization  write
   3. remove_site_group_member         TS-L2 Group
   4. skip_system_group                SharingLinks.ad5161b1-081a-403e-9819-b726cee977c9.Flexible.09ce0264-a0ca-4890-8497-838c3c021684  系统管理组，不可手动移除
   5. skip_system_group                Limited Access System Group For List 66d491e7-961a-4103-bf06-f9fa351f66cb  系统管理组，不可手动移除
   6. skip_system_group                Limited Access System Group For Web 59b88f73-04fc-4796-ba10-7da00955d81d  系统管理组，不可手动移除
   7. update_sharing_link_recipients   /sites/TradeSecret/Trade Secret Library/Automatic File Categorization  多人链接：仅移除该用户，保留链接
================================================================
(ts-governance) PS C:\Python_Projects\Pi\Pi-Trade-Secret> python cli.py status
数据库      C:\Python_Projects\Pi\Pi-Trade-Secret\data\governance.sqlite3  (schema v1)
最近运行    20261127T014900_c6e0fb  partial  2026-11-27T01:49:00+00:00 -> 2026-11-27T01:49:30+00:00
对象/作用域 119 / 9  (继承率 92.4%)
API 请求    30 次 (权限读取 8 次)
  [错误] phase2: /sites/TradeSecret/Trade Secret Library/Confidential/Test_Permission.docx — no Graph id for unique item path='/sites/TradeSecret/Trade Secret Library/Confidential/Test_Permission.docx'
存储        作用域 9 / 对象 119 / 角色授权 52 / 共享链接 1 / 主体 14 / 站点组 10
最大作用域 (inheriting_count):
  folder      75  /sites/TradeSecret/Trade Secret Library/02_NPD
  library     13  /sites/TradeSecret/Trade Secret Library
  folder       7  /sites/TradeSecret/Trade Secret Library/Trade Secret/TS-L3+
  folder       5  /sites/TradeSecret/Trade Secret Library/Trade Secret/TS-L1
  folder       4  /sites/TradeSecret/Trade Secret Library/Trade Secret/TS-L3
  site         3  /sites/TradeSecret
  folder       3  /sites/TradeSecret/Trade Secret Library/Trade Secret/TS-L2
  folder       0  /sites/TradeSecret/Trade Secret Library/Automatic File Categorization
  file         0  /sites/TradeSecret/Trade Secret Library/Confidential/Test_Permission.docx