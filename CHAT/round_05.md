# Round 05 — 2026-11-27

## 你的三个问题（逐一验证后的答案）

### Q1：Site Owner + Full Control + 只管自己的站，能否仅靠 REST + 当前身份完成写操作？

**不能**。实证（m3_probe F2/F3）：你在 Owners 组、有 Full Control，但
REST DELETE/POST 仍 403。原因：**OAuth 承载令牌下，SharePoint 同时校验
「用户权限」AND「应用令牌作用域」**——你的令牌只带读作用域（Sites.Read.All
级别），写操作在令牌层就被拦截，用户身份再高也没用。

### Q2：REST 写操作按用户 Site 权限授权，还是按 OAuth Scope？

**两者都查，取交集。** 这解释了你观察到的全部现象：
- 浏览器操作成功 → Cookie 认证 → **只查用户权限**（你是 Owner ✓）
- 程序 REST 403 → OAuth 令牌 → 用户权限 ✓ 但作用域 ✗

这是微软刻意的安全设计：一个应用要行使"你本人的全部权力"，必须被
**显式授权**（管理员同意），防止任何程序拿到登录就能以你身份乱写。

### Q3：浏览器能做 → 是否存在"复用 Site Owner 权限模型"的 API 路径？

**"纯用户权限"的 API 路径不存在**——Cookie 会话是这种模型的唯一形态，
而程序化使用 Cookie 已被微软弃用并在现代租户禁用。支持的三条等效路径：

| 路径 | 权限边界 | 需要什么 |
| --- | --- | --- |
| 层1（你已选定） | 零 API 写权限 | 工具出清单+深链接，浏览器人工执行，verify 验证 |
| 层2（可选升级） | 你有权访问的文件 | 一次管理员同意 `Files.ReadWrite`（A档） |
| 层3（不做） | 单站点 | 管理员注册 App + `Sites.Selected` |

**你的判断正确的地方**：之前 probe 申请 FullControl/ReadWrite 确实是
"诊断探测"（探明哪些路径可用），不是必需品——已从代码中全部移除。
你的租户连用户级同意都禁用了（F0 access_denied），所以任何写授权都要
走一次管理员。层1 是零同意的最优解。

## Pi 做了什么（v6.0）

1. **项目结构重整**：根目录清理
   - `probes/`（m0/m0b/m3_probe 探测脚本，路径已修）
   - `results/`（全部探针结果 + 扫描转储 + 你的控制台日志，证据存档）
   - `tools/build_ppt.py`（你加的 PPT 生成器）
   - `CHAT/archive/`（历史轮次归档）
2. **plan 手动深链接**（推论 3 落地）：每项操作带可点击直达页——
   - 项/库/站点级授权 → `user.aspx` 经典权限页（obj={list},{item},LISTITEM）
   - 组成员移除 → `people.aspx?MembershipGroupId={gid}`
   - 共享链接 → item 页（打开后 Manage Access）
3. **运行模型定稿入 GOALS.md**：层1 只读闭环（今天可用）→ 层2 待管理员 →
   组手动。组成员读取正常，保留清单。
4. 39 个测试全过；`apply` 正确用法是
   `python cli.py apply plans\<文件>.json <site-url>`（上次你传了邮箱所以报缺文件）。

## 需要你（公司电脑）——第一次真实闭环演练

```powershell
git pull

# 1. 重新生成方案（这次每项都带"手动入口"链接）
python cli.py plan xuguifang@danfoss.com

# 2. 点开输出里的链接，验证直达页面是否正确
#    （user.aspx 应直接打开 Test_Permission.docx / 02_NPD 的权限页）

# 3. 在浏览器里按清单执行 1~2 项（建议：删 Test_Permission.docx 上
#    xuguifang 的 read 授权，或从 TS-L2 组移除他）

# 4. 验证零残留（只读复扫）
python cli.py verify xuguifang@danfoss.com https://danfoss.sharepoint.com/sites/TradeSecret

# 5. 推回结果
git add CHAT
git commit -m "round 05 回复"
git push
```

> 第 4 步的 verify 输出是 M4（论文闭环实证）的第一个真实数据点：
> "手动执行 N 项 → 复扫 → 残留清零"。

## 用户回复区

（在这行下面写结果/备注；写完保存，然后：
`git add CHAT` → `git commit -m "round 05 回复"` → `git push`）

从 TS-L2 组移除xuguifang@danfoss.com

(ts-governance) PS C:\Python_Projects\Pi\Pi-Trade-Secret> python cli.py verify xuguifang@danfoss.com https://danfoss.sharepoint.com/sites/TradeSecret
Traceback (most recent call last):
  File "C:\Python_Projects\Pi\Pi-Trade-Secret\cli.py", line 416, in <module>
    sys.exit(main())
             ^^^^^^
  File "C:\Python_Projects\Pi\Pi-Trade-Secret\cli.py", line 412, in main
    return args.func(args)
           ^^^^^^^^^^^^^^^
  File "C:\Python_Projects\Pi\Pi-Trade-Secret\cli.py", line 341, in cmd_verify
    result = verify_user(args.site_url, str(db_path), args.email)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Python_Projects\Pi\Pi-Trade-Secret\remediate\verify.py", line 53, in verify_user
    init_schema(conn)
    ^^^^^^^^^^^
NameError: name 'init_schema' is not defined