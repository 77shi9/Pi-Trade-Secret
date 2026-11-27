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

(ts-governance) PS C:\Python_Projects\Pi\Pi-Trade-Secret> python cli.py scan https://danfoss.sharepoint.com/sites/TradeSecret
2026-11-27 12:50:26,165 INFO    [AUTH] Loading token cache: C:\Python_Projects\Pi\Pi-Trade-Secret\.cache\msal_cache.bin
2026-11-27 12:50:26,678 INFO    [AUTH] Attempting silent authentication (scopes=['Sites.Read.All'])...
2026-11-27 12:50:27,081 INFO    [AUTH] Token acquired (audience=00000003-0000-0000-c000-000000000000, user=yong.hu@danfoss.com).
2026-11-27 12:50:28,918 INFO    [AUTH] Attempting silent authentication (scopes=['https://danfoss.sharepoint.com/.default'])...
2026-11-27 12:50:29,335 INFO    [AUTH] Token acquired (audience=00000003-0000-0ff1-ce00-000000000000, user=yong.hu@danfoss.com).
2026-11-27 12:50:30,711 INFO    [SCAN] site=Trade Secret libraries=2
2026-11-27 12:50:32,707 INFO    [SCAN] library 'Documents' items=2 unique=False
2026-11-27 12:50:35,076 INFO    [SCAN] library 'Trade Secret Library' items=114 unique=True
2026-11-27 12:50:42,165 INFO    [SCAN] site groups=10
2026-11-27 12:50:43,322 INFO    [SCAN] delta map 'Documents': 3 entries
2026-11-27 12:50:44,190 INFO    [SCAN] delta map 'Trade Secret Library': 98 entries
2026-11-27 12:50:54,327 INFO    [SCAN] done run=20261127T045026_0e8630 status=success objects=119 unique=9 requests=32

============================================================
站点        Trade Secret
对象        119 个 (站点 1 / 库 2 / 文件夹 36 / 文件 80)
独立作用域  9 个 (站点 1 / 库 1 / 文件夹 6 / 文件 1)  ← 例外权限
继承率      92.4%  (110 个对象未读取权限)
权限读取    9 次（仅独立作用域）
API 请求    32 次
授权        角色授权 63 行 / 共享链接 1 条 / 站点组 10 组 18 成员
数据库      C:\Python_Projects\Pi\Pi-Trade-Secret\data\governance.sqlite3
运行        20261127T045026_0e8630  状态 success  耗时 28.2s  错误 0
============================================================
(ts-governance) PS C:\Python_Projects\Pi\Pi-Trade-Secret> python m3_probe.py https://danfoss.sharepoint.com/sites/TradeSecret
2026-11-27 12:51:16,905 INFO    [AUTH] Loading token cache: C:\Python_Projects\Pi\Pi-Trade-Secret\.cache\msal_cache.bin
2026-11-27 12:51:17,318 INFO    [AUTH] Attempting silent authentication (scopes=['Sites.Read.All'])...
2026-11-27 12:51:17,323 INFO    [AUTH] Token acquired (audience=00000003-0000-0000-c000-000000000000, user=yong.hu@danfoss.com).
2026-11-27 12:51:17,324 INFO    [AUTH] Attempting silent authentication (scopes=['Sites.Read.All', 'Files.ReadWrite'])...
2026-11-27 12:51:17,904 INFO    [AUTH] Silent authentication failed; launching interactive login...
2026-11-27 12:51:17,908 INFO    Open a browser on this device to visit: https://login.microsoftonline.com/organizations/oauth2/v2.0/authorize?client_id=14d82eec-204b-4c2f-b7e8-296a70dab67e&response_type=code&redirect_uri=http%3A%2F%2Flocalhost%3A62510&scope=Files.ReadWrite+Sites.Read.All+offline_access+openid+profile&state=3_aQw2OpSlBAbHyhfqiJ9w&response_mode=form_post&code_challenge=81-bN6mIE5HyRcXkfqrF9gobMtbtrBBl8cZV1KRbv-k&code_challenge_method=S256&nonce=bc5b9be2687fb7de0f9a31eec0ef16d9442ea4f21c570d72170703733db4ea1f&client_info=1
2026-11-27 12:51:26,927 INFO    [FAIL] F0 Files.ReadWrite 用户级同意（无需管理员） | 
2026-11-27 12:51:27,574 INFO    [PASS] F0b 目标项路径寻址 | item id: 01S4KOHXL4JXZSUIQNHBHIZRCQQF5ADS4J
2026-11-27 12:51:28,706 INFO    [FAIL] F1 Graph DELETE 写权限探测（假 permission id） | HTTP 400 = 需人工判读
2026-11-27 12:51:28,706 INFO    [AUTH] Attempting silent authentication (scopes=['https://danfoss.sharepoint.com/.default'])...
2026-11-27 12:51:28,706 INFO    [AUTH] Token acquired (audience=00000003-0000-0ff1-ce00-000000000000, user=yong.hu@danfoss.com).
2026-11-27 12:51:28,706 INFO    [PASS] F2a-0 SP 站点资源令牌 | acquired
2026-11-27 12:51:29,463 INFO    [PASS] F2a REST contextinfo（request digest） | digest acquired
2026-11-27 12:51:30,244 INFO    [FAIL] F2 REST DELETE 写权限探测（假 principal id） | 403 = 无写权限（授权层拦截）
2026-11-27 12:51:30,904 INFO    [FAIL] F3 REST POST 移组成员写权限探测（假登录名） | 403 = 无写权限
2026-11-27 12:51:30,904 INFO    [PASS] F4 令牌 scp 证据 | {"graph": {"has_files_rw": false, "has_fullcontrol": false, "has_sites_read": true, "scp_excerpt": "AccessReview.Read.All AdministrativeUnit.Read.All Agreement.Read.All APIConnectors.Read.All APIConnectors.ReadWrite.All Application.Read.All Application.ReadWrite.All AppRoleAssignment.ReadWrite.All AuditLog.Read.All DelegatedPermissionGrant.ReadWrite.All Device.Read.All Device.ReadWrite.All DeviceM"}, "sharepoint": {"has_files_rw": false, "has_fullcontrol": false, "has_sites_read": true, "scp_excerpt": "AccessReview.Read.All AdministrativeUnit.Read.All Agreement.Read.All APIConnectors.Read.All APIConnectors.ReadWrite.All Application.Read.All Application.ReadWrite.All AppRoleAssignment.ReadWrite.All AuditLog.Read.All DelegatedPermissionGrant.ReadWrite.All Device.Read.All Device.ReadWrite.All DeviceM"}}

====================================================================
F0    FAIL   Files.ReadWrite 用户级同意（无需管理员）
             
F0b   PASS   目标项路径寻址
             item id: 01S4KOHXL4JXZSUIQNHBHIZRCQQF5ADS4J
F1    FAIL   Graph DELETE 写权限探测（假 permission id）
             HTTP 400 = 需人工判读
F2a-0 PASS   SP 站点资源令牌
             acquired
F2a   PASS   REST contextinfo（request digest）
             digest acquired
F2    FAIL   REST DELETE 写权限探测（假 principal id）
             403 = 无写权限（授权层拦截）
F3    FAIL   REST POST 移组成员写权限探测（假登录名）
             403 = 无写权限
F4    PASS   令牌 scp 证据
             {"graph": {"has_files_rw": false, "has_fullcontrol": false, "has_sites_read": true, "scp_excerpt": "AccessReview.Read.All AdministrativeUnit.Read.All Agreement.Read.All APIConnectors.Read.All APIConnectors.ReadWrite.All Application.Read.All Application.ReadWrite.All AppRoleAssignment.ReadWrite.All AuditLog.Read.All DelegatedPermissionGrant.ReadWrite.All Device.Read.All Device.ReadWrite.All DeviceM"}, "sharepoint": {"has_files_rw": false, "has_fullcontrol": false, "has_sites_read": true, "scp_excerpt": "AccessReview.Read.All AdministrativeUnit.Read.All Agreement.Read.All APIConnectors.Read.All APIConnectors.ReadWrite.All Application.Read.All Application.ReadWrite.All AppRoleAssignment.ReadWrite.All AuditLog.Read.All DelegatedPermissionGrant.ReadWrite.All Device.Read.All Device.ReadWrite.All DeviceM"}}
====================================================================
Results written to C:\Python_Projects\Pi\Pi-Trade-Secret\m3_probe_results.json
判读: F1/F2 的 404 = 有写权限; 403 = 无写权限。F3 非403 = 有写权限。
(ts-governance) PS C:\Python_Projects\Pi\Pi-Trade-Secret> python cli.py plan yong.hu@danfoss.com
================================================================
清除方案    yong.hu@danfoss.com  (20261127T045142_27ee11)
数据源      扫描 20261127T045026_0e8630
操作        10 项，其中可自动执行 7 项
    1. delete_role_assignment             [graph ] /sites/TradeSecret/Trade Secret Library/Confidential/Test_Permission.docx read
    2. remove_site_group_member           [rest  ] Trade Secret Owners 
    3. remove_site_group_member           [rest  ] TS-L1 Group 
    4. remove_site_group_member           [rest  ] TS-L2 Group 
    5. remove_site_group_member           [rest  ] TS-L3 Group 
    6. remove_site_group_member           [rest  ] TS-L3Plus Group 
    7. skip_system_group                  [-     ] SharingLinks.ad5161b1-081a-403e-9819-b726cee977c9.Flexible.09ce0264-a0ca-4890-8497-838c3c021684 系统管理组，不可手动移除
    8. skip_system_group                  [-     ] Limited Access System Group For List 66d491e7-961a-4103-bf06-f9fa351f66cb 系统管理组，不可手动移除
    9. skip_system_group                  [-     ] Limited Access System Group For Web 59b88f73-04fc-4796-ba10-7da00955d81d 系统管理组，不可手动移除
   10. update_sharing_link_recipients     [graph ] /sites/TradeSecret/Trade Secret Library/Automatic File Categorization ['read']
================================================================
提示: python cli.py apply <plan.json> 预览执行；加 --apply 才真正写入
方案已写入 plans\20261127T045142_27ee11.json
(ts-governance) PS C:\Python_Projects\Pi\Pi-Trade-Secret> python cli.py plan xuguifang@danfoss.com
================================================================
清除方案    xuguifang@danfoss.com  (20261127T045203_d975ab)
数据源      扫描 20261127T045026_0e8630
操作        8 项，其中可自动执行 5 项
    1. delete_role_assignment             [graph ] /sites/TradeSecret/Trade Secret Library/02_NPD write
    2. delete_role_assignment             [graph ] /sites/TradeSecret/Trade Secret Library/Automatic File Categorization write
    3. delete_role_assignment             [graph ] /sites/TradeSecret/Trade Secret Library/Confidential/Test_Permission.docx read
    4. remove_site_group_member           [rest  ] TS-L2 Group 
    5. skip_system_group                  [-     ] SharingLinks.ad5161b1-081a-403e-9819-b726cee977c9.Flexible.09ce0264-a0ca-4890-8497-838c3c021684 系统管理组，不可手动移除
    6. skip_system_group                  [-     ] Limited Access System Group For List 66d491e7-961a-4103-bf06-f9fa351f66cb 系统管理组，不可手动移除
    7. skip_system_group                  [-     ] Limited Access System Group For Web 59b88f73-04fc-4796-ba10-7da00955d81d 系统管理组，不可手动移除
    8. update_sharing_link_recipients     [graph ] /sites/TradeSecret/Trade Secret Library/Automatic File Categorization ['read']
================================================================
提示: python cli.py apply <plan.json> 预览执行；加 --apply 才真正写入
方案已写入 plans\20261127T045203_d975ab.json
(ts-governance) PS C:\Python_Projects\Pi\Pi-Trade-Secret> python cli.py apply  plan yong.hu@danfoss.com
缺少文件: C:\Python_Projects\Pi\Pi-Trade-Secret\data\governance.sqlite3 / plan
(ts-governance) PS C:\Python_Projects\Pi\Pi-Trade-Secret>       


同样的2要求管理员审批，奇怪，为什么会触发？你应该要求了特别的命令，记住yong.hu@danfoss.com是site创建者，也就是我，所以我有较高的权限，但是只能管理我的这个trade secret
