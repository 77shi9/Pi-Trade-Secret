"""Build the management deck: s3scope permission-governance progress & decisions."""

from __future__ import annotations

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

# ---------------------------------------------------------------- palette ----
NAVY = RGBColor(0x1F, 0x38, 0x64)
INK = RGBColor(0x1F, 0x29, 0x37)
ACCENT = RGBColor(0x2E, 0x75, 0xB6)
GRAY = RGBColor(0x6B, 0x72, 0x80)
LIGHT = RGBColor(0xEE, 0xF3, 0xF9)
PALE = RGBColor(0xF7, 0xF9, 0xFC)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
GREEN = RGBColor(0x2E, 0x7D, 0x32)
AMBER = RGBColor(0xB4, 0x53, 0x09)
RULE = RGBColor(0xDD, 0xE3, 0xEA)

FONT = "微软雅黑"
SW, SH = 13.333, 7.5
ML = 0.7
CW = SW - 2 * ML

prs = Presentation()
prs.slide_width = Inches(SW)
prs.slide_height = Inches(SH)
BLANK = prs.slide_layouts[6]


# ---------------------------------------------------------------- helpers ----
def _font(run, size, bold=False, color=INK, font=FONT):
    run.font.name = font
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color
    rPr = run._r.get_or_add_rPr()
    for tag in ("a:ea", "a:cs"):
        el = rPr.find(qn(tag))
        if el is None:
            el = rPr.makeelement(qn(tag), {})
            rPr.append(el)
        el.set("typeface", font)


def textbox(slide, x, y, w, h, text, size=13, bold=False, color=INK,
            align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, spacing=1.0):
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame
    tf.word_wrap = True
    tf.margin_left = 0
    tf.margin_right = 0
    tf.margin_top = 0
    tf.margin_bottom = 0
    tf.vertical_anchor = anchor
    p = tf.paragraphs[0]
    p.alignment = align
    p.line_spacing = spacing
    run = p.add_run()
    run.text = text
    _font(run, size, bold, color)
    return box


def bullets(slide, x, y, w, h, items, size=13, gap=10, spacing=1.25):
    """items: list of (lead, rest) or plain strings."""
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame
    tf.word_wrap = True
    tf.margin_left = 0
    tf.margin_right = 0
    tf.margin_top = 0
    tf.margin_bottom = 0
    for i, item in enumerate(items):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.line_spacing = spacing
        p.space_before = Pt(0 if i == 0 else gap)
        dot = p.add_run()
        dot.text = "•  "
        _font(dot, size, True, ACCENT)
        lead, rest = (item if isinstance(item, tuple) else ("", item))
        if lead:
            r1 = p.add_run()
            r1.text = lead
            _font(r1, size, True, NAVY)
        if rest:
            r2 = p.add_run()
            r2.text = rest
            _font(r2, size, False, INK)
    return box


def rule(slide, y, color=RULE, width=0.012, x=ML, w=CW):
    shp = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y),
                                 Inches(w), Inches(width))
    shp.fill.solid()
    shp.fill.fore_color.rgb = color
    shp.line.fill.background()
    shp.shadow.inherit = False


def card(slide, x, y, w, h, fill=LIGHT, line=None):
    shp = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y),
                                 Inches(w), Inches(h))
    shp.adjustments[0] = 0.06
    shp.fill.solid()
    shp.fill.fore_color.rgb = fill
    if line is None:
        shp.line.fill.background()
    else:
        shp.line.color.rgb = line
        shp.line.width = Pt(1)
    shp.shadow.inherit = False
    return shp


def table(slide, data, x, y, col_widths, row_h=0.36, head_h=0.44,
          size=11, head_size=11):
    rows, cols = len(data), len(data[0])
    shp = slide.shapes.add_table(rows, cols, Inches(x), Inches(y),
                                 Inches(sum(col_widths)),
                                 Inches(head_h + row_h * (rows - 1)))
    tbl = shp.table
    tbl.first_row = True
    tbl.horz_banding = False
    for i, wd in enumerate(col_widths):
        tbl.columns[i].width = Inches(wd)
    for r in range(rows):
        tbl.rows[r].height = Inches(head_h if r == 0 else row_h)
        for c in range(cols):
            cell = tbl.cell(r, c)
            cell.margin_left = Inches(0.11)
            cell.margin_right = Inches(0.09)
            cell.margin_top = Inches(0.04)
            cell.margin_bottom = Inches(0.04)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            cell.fill.solid()
            cell.fill.fore_color.rgb = NAVY if r == 0 else (PALE if r % 2 else WHITE)
            tf = cell.text_frame
            tf.word_wrap = True
            for k, line in enumerate(str(data[r][c]).split("\n")):
                p = tf.paragraphs[0] if k == 0 else tf.add_paragraph()
                p.line_spacing = 1.0
                run = p.add_run()
                run.text = line
                if r == 0:
                    _font(run, head_size, True, WHITE)
                else:
                    _font(run, size, False, INK)
    return shp


def slide_frame(title, kicker, page, total=10):
    s = prs.slides.add_slide(BLANK)
    textbox(s, ML, 0.34, CW, 0.3, kicker, 10.5, True, ACCENT)
    textbox(s, ML, 0.60, CW, 0.62, title, 26, True, NAVY)
    rule(s, 1.30)
    rule(s, 6.98, RGBColor(0xE8, 0xEC, 0xF1), 0.008)
    textbox(s, ML, 7.06, 8.0, 0.26, "s3scope · SharePoint 站点权限治理 · 内部使用",
            8.5, False, GRAY)
    textbox(s, SW - ML - 1.2, 7.06, 1.2, 0.26, f"{page} / {total}", 8.5, False,
            GRAY, align=PP_ALIGN.RIGHT)
    return s


def notes(slide, text):
    slide.notes_slide.notes_text_frame.text = text


# ------------------------------------------------------------------ 01 cover --
s = prs.slides.add_slide(BLANK)
bg = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, prs.slide_width, prs.slide_height)
bg.fill.solid()
bg.fill.fore_color.rgb = NAVY
bg.line.fill.background()
bg.shadow.inherit = False
accent = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(ML), Inches(2.30),
                            Inches(0.9), Inches(0.055))
accent.fill.solid()
accent.fill.fore_color.rgb = RGBColor(0x6E, 0xA8, 0xDC)
accent.line.fill.background()
accent.shadow.inherit = False
textbox(s, ML, 2.55, 11.0, 1.1, "SharePoint 站点权限治理", 42, True, WHITE)
textbox(s, ML, 3.62, 11.0, 0.7, "项目进展与授权决策汇报", 22, False,
        RGBColor(0xC7, 0xD8, 0xEC))
rule(s, 4.55, RGBColor(0x3E, 0x5A, 0x8C), 0.012, ML, 6.2)
textbox(s, ML, 4.78, 11.5, 1.2,
        "范围：danfoss.sharepoint.com /sites/TradeSecret（单站点）      版本：v5.2\n"
        "报告日期：2026-11-27      密级：内部",
        12, False, RGBColor(0xC7, 0xD8, 0xEC), spacing=1.5)
textbox(s, ML, 6.55, 11.5, 0.4,
        "本汇报聚焦“本轮讨论结论 + 当前进度”，不含凭据与个人明细。",
        10, False, RGBColor(0x8F, 0xA8, 0xC8))
notes(s, "开场：这是一份决策汇报，不是技术评审。三件事——查询已可用、清理需要一次最小授权、请拍板三件事。")

# ------------------------------------------------------------- 02 one page ----
s = slide_frame("一页结论", "EXECUTIVE SUMMARY", 2)
cards = [
    ("01", "查询已可用", GREEN, [
        "输入邮箱 → 所属组 / 独立权限 / 分享链接",
        "全站 119 个对象、9 个例外作用域，30 秒扫完，0 错误",
        "不需要 AllSites.FullControl",
    ]),
    ("02", "清理分两档", AMBER, [
        "文件与链接级：Files.ReadWrite 即可自动清理",
        "组成员与角色分配：才需 FullControl，可缩到单站点",
        "无新授权也能跑“清单 + 人工 + 验证”闭环",
    ]),
    ("03", "编排需自研", ACCENT, [
        "对标 8 个开源项目：均无“按人汇总 → 清理 → 零残留”",
        "自研部分已完成约 90%，剩 4 项准确性修复",
        "1–2 周内可交付阶段一",
    ]),
]
cw = (CW - 0.5) / 3
for i, (num, head, color, lines) in enumerate(cards):
    x = ML + i * (cw + 0.25)
    card(s, x, 1.55, cw, 3.55)
    textbox(s, x + 0.28, 1.78, 0.8, 0.5, num, 20, True, RGBColor(0xC9, 0xD6, 0xE6))
    textbox(s, x + 0.28, 2.18, cw - 0.5, 0.4, head, 17, True, NAVY)
    rule(s, 2.66, color, 0.035, x + 0.28, 0.7)
    bullets(s, x + 0.28, 2.86, cw - 0.56, 2.1, lines, 11.5, 8, 1.3)
card(s, ML, 5.42, CW, 0.95, NAVY)
textbox(s, ML + 0.32, 5.62, CW - 0.64, 0.6,
        "需管理层拍板：① 是否申请 A 档授权    ② 是否推进 B 档    ③ 是否确认“组清理保持人工”的边界",
        13.5, True, WHITE)
textbox(s, ML, 6.52, CW, 0.3,
        "注：A 档 = delegated Files.ReadWrite（文件级）；B 档 = 单站点 Sites.Selected + fullcontrol（组与角色分配）",
        9.5, False, GRAY)
notes(s, "三条结论对应三种现状：已经能用的、差一次授权的、没人做过所以要自研的。最后那条横条是今天要拍板的三件事。")

# ------------------------------------------------------- 03 goal & boundary ---
s = slide_frame("目标与边界：先把范围钉死", "SCOPE", 3)
textbox(s, ML, 1.52, 5.6, 0.35, "目标（4 项能力）", 14, True, NAVY)
rule(s, 1.92, ACCENT, 0.03, ML, 0.55)
bullets(s, ML, 2.08, 5.6, 3.9, [
    ("①  ", "输入一个成员邮箱，列出他在本站点的全部访问来源"),
    ("②  ", "区分“组继承”与“文件级独立授权”，后者是主要风险来源"),
    ("③  ", "输出他所有的分享链接与收件人身份"),
    ("④  ", "一键清理，并复扫证明零残留"),
], 13, 14, 1.35)
textbox(s, 6.95, 1.52, 5.6, 0.35, "边界（已确认不做）", 14, True, NAVY)
rule(s, 1.92, AMBER, 0.03, 6.95, 0.55)
bullets(s, 6.95, 2.08, 5.6, 3.9, [
    ("仅单站点　", "只针对 TradeSecret，不申请任何租户级权限"),
    ("链接　", "全组织 / 匿名链接无法按人剔除，标记为人工决策"),
    ("组　", "M365 / Entra 组成员 → 输出建议，人工执行"),
    ("范围　", "不做实时监控、不做跨站点并发"),
], 13, 14, 1.35)
card(s, ML, 6.02, CW, 0.72, PALE)
textbox(s, ML + 0.28, 6.18, CW - 0.56, 0.4,
        "一句话：把“一个人在这个站点还能看到什么”讲清楚，并把能自动清掉的清掉——范围严格限制在一个站点内。",
        11.5, False, NAVY)
notes(s, "边界是这份方案能不能获批的关键：我们不碰别的站点、不碰租户配置。")

# ------------------------------------------------------------- 04 progress ----
s = slide_frame("目前进度：能力矩阵", "PROGRESS", 4)
data = [
    ["你需要的能力", "状态", "当前实现", "剩余工作"],
    ["输入邮箱 → 所属组", "已实现", "站点组 10 个 / 成员 18 人已入库", "无（M365 组不采，已确认可接受）"],
    ["文件级独立权限清单", "已实现", "只展开 9 个例外作用域，92.4% 对象零读取", "4 项准确性修复，约 4 个工作日"],
    ["被分享的链接", "部分", "特定人员链接可查收件人", "继承中对象上的链接需只读探针验证"],
    ["一键清理", "待授权", "方案生成与 dry-run 已完成", "授权到位后联调，3 个对象试点"],
]
table(s, data, ML, 1.55, [3.05, 1.35, 4.45, 3.08], 0.62, 0.46, 11, 11)
textbox(s, ML, 4.62, CW, 0.32,
        "已交付的工程基础（v2.0 → v5.2，11 个版本，38 个离线测试）", 11.5, True, NAVY)
chips = ["两阶段扫描模型", "SQLite 单一事实源", "dry-run 默认", "全量审计日志",
         "增量 schema 迁移", "只读复扫验证"]
x = ML
for chip in chips:
    w = 0.145 * len(chip) + 0.5
    card(s, x, 5.02, w, 0.42, LIGHT)
    textbox(s, x, 5.12, w, 0.26, chip, 9, False, NAVY, align=PP_ALIGN.CENTER)
    x += w + 0.12
card(s, ML, 5.72, CW, 1.0, PALE)
textbox(s, ML + 0.28, 5.92, CW - 0.56, 0.65,
        "可信度依据：所有写操作默认 dry-run；每一步落到审计表；清理后自动复扫比对——不是“跑一次看结果”，是“可复现、可回溯”。",
        11.5, False, INK, spacing=1.3)
notes(s, "进度不是“做了个原型”，而是能力矩阵里四行已有三行落地。只有最后一行在等授权。")

# ----------------------------------------------------------------- 05 facts ----
s = slide_frame("真实站点实测：成本与覆盖", "EVIDENCE · 2026-11-27 扫描", 5)
kpis = [("119", "站点对象", "站点 1 / 库 2 /\n文件夹 36 / 文件 80"),
        ("9", "例外作用域", "站点 1 / 库 1 /\n文件夹 6 / 文件 1"),
        ("92.4%", "继承率", "110 个对象\n无需读取权限"),
        ("30 s", "扫描耗时", "30–32 次\nAPI 请求"),
        ("0", "错误", "两次连续扫描\n均成功")]
kwd = (CW - 4 * 0.18) / 5
for i, (num, label, sub) in enumerate(kpis):
    x = ML + i * (kwd + 0.18)
    card(s, x, 1.55, kwd, 1.72, PALE)
    textbox(s, x + 0.2, 1.72, kwd - 0.4, 0.62, num, 30, True, NAVY)
    textbox(s, x + 0.2, 2.34, kwd - 0.4, 0.3, label, 11, True, INK)
    textbox(s, x + 0.2, 2.66, kwd - 0.4, 0.55, sub, 9, False, GRAY, spacing=1.15)
textbox(s, ML, 3.52, CW, 0.34, "为什么这套模型便宜", 14, True, NAVY)
rule(s, 3.92, ACCENT, 0.03, ML, 0.55)
bullets(s, ML, 4.06, 5.9, 2.4, [
    ("权限读取 9 次", "，而全量遍历模型需要对 119 个对象逐个读取（≈13 倍差距）"),
    ("只读 9 个例外", "，其余 110 个对象完全跳过"),
    ("请求数稳定", "，站点变大的主要成本在项枚举，而非权限读取"),
], 12, 10, 1.35)
card(s, 6.85, 3.98, 5.75, 2.55, LIGHT)
textbox(s, 7.12, 4.16, 5.25, 0.32, "已入库的授权事实", 11.5, True, NAVY)
bullets(s, 7.12, 4.58, 5.25, 1.9, [
    ("63 行角色授权", "（站点 / 库 / 文件夹 / 文件）"),
    ("1 条分享链接", "（特定人员，2 名收件人）"),
    ("10 个站点组 / 18 名成员", "，含系统组标记"),
], 11, 8, 1.3)
textbox(s, ML, 6.55, CW, 0.3,
        "数据来源：run 20261127T045026（重扫后 success）。此前一次为 partial，已定位并修复 delta 缺项。",
        9, False, GRAY)
notes(s, "这页是给管理者的“性价比”证据：同样的结论，成本只有全量遍历的 1/13。")

# ------------------------------------------------------------------ 06 403 ----
s = slide_frame("为什么“我是站点 Owner 还是被拒绝”", "KEY FINDING", 6)
card(s, ML, 1.52, CW, 1.02, NAVY)
textbox(s, ML + 0.3, 1.72, CW - 0.6, 0.7,
        "实际可执行操作 ＝ 令牌中的应用权限  ∩  用户自身的 SharePoint 权限",
        17, True, WHITE)
textbox(s, ML, 2.80, 6.2, 0.34, "四项实测（零真实改动）", 13, True, NAVY)
data = [
    ["探测", "结果", "解读"],
    ["REST 取请求摘要", "200 通过", "认证与读权限正常"],
    ["REST 删除角色分配", "403", "应用无 Manage Permissions"],
    ["REST 移出组成员", "403", "同上，需 Full Control"],
    ["Graph 申请文件写权限", "access_denied", "租户禁止用户级同意"],
]
table(s, data, ML, 3.16, [2.35, 1.55, 2.55], 0.44, 0.42, 10, 10)
card(s, 7.05, 2.80, 5.55, 2.95, LIGHT)
textbox(s, 7.32, 3.00, 5.0, 0.34, "三条推论", 12.5, True, NAVY)
bullets(s, 7.32, 3.44, 5.0, 2.2, [
    ("不是权限不足：", "Owner 身份只满足“用户侧”，无法替代应用权限"),
    ("不是代码缺陷：", "换任何工具都一样，社区口径同样要求 Full Control"),
    ("但可以分级：", "文件级操作并不需要 Full Control，见下页"),
], 11, 9, 1.32)
textbox(s, ML, 6.30, CW, 0.45,
        "结论：这是“授权范围”问题，不是“权限不够”问题——因此可以用比“全租户完全控制”更小的授权解决。",
        11.5, True, NAVY, spacing=1.25)
notes(s, "这页专门回答管理层最可能问的问题：为什么一个站点所有者还要额外授权。关键在于应用权限与用户权限取交集。")

# ------------------------------------------------------------ 07 two tiers ----
s = slide_frame("两档授权方案：把申请降到最小", "OPTIONS", 7)
data = [
    ["档位", "申请内容", "解锁能力", "影响范围", "审批难度"],
    ["A 档", "Graph delegated\nFiles.ReadWrite",
     "删除文件 / 文件夹直接授权；\n分享链接移除单人 / 撤销", "仅操作者本来\n可写的文件", "低"],
    ["B 档", "SharePoint Sites.Selected\n+ 单站点 fullcontrol",
     "移出站点组；删除站点 /\n库 / 项级角色分配", "仅\n/sites/TradeSecret", "中"],
    ["兜底", "无需新增授权",
     "清单 + 深链接人工处理\n+ 只读验证零残留", "无", "无需审批"],
]
table(s, data, ML, 1.52, [1.15, 3.45, 3.55, 2.3, 1.48], 0.92, 0.44, 10.5, 10.5)
card(s, ML, 4.72, CW, 1.28, PALE)
textbox(s, ML + 0.3, 4.88, CW - 0.6, 0.3, "推荐路径", 11, True, ACCENT)
textbox(s, ML + 0.3, 5.18, CW - 0.6, 0.78,
        "先批 A 档：文件级散落授权 100% 自动清理，且数据边界就是操作者本人可访问的文件；"
        "B 档可同时申报但不阻塞交付，组成员继续“工具出清单、网页处理”。",
        11.5, False, INK, spacing=1.3)
textbox(s, ML, 6.18, CW, 0.55,
        "行业印证：CLI for Microsoft 365 的 roleassignment 命令在文档中同样要求 SharePoint AllSites.FullControl；"
        "PnP 系列亦无更小档位——这不是我们实现的问题。",
        9.5, False, GRAY, spacing=1.3)
notes(s, "关键点：A 档小、快、可解释。B 档如果想要全自动就一起申报，但不要因此推迟交付。")

# ----------------------------------------------------------- 08 open risks ----
s = slide_frame("待修项：4 个工作日，全部可离线完成", "REMAINING WORK", 8)
data = [
    ["风险项", "影响", "处置", "工期"],
    ["底账不“退休”已撤销的授权", "清单出现假阳性；\n验证永远无法归零", "每次扫描后对账，\n标记失效行", "1 天"],
    ["链接可能漏采\n（继承中对象上的链接）", "“被分享的链接”\n清单不完整", "只读探针验证 +\n扩展采集通道", "1 天"],
    ["仅覆盖 Graph 认定的文档库", "其他库 / 列表项上的\n例外不可见", "补 REST 列表\n枚举通道", "1 天"],
    ["无“最后一位所有者”保护", "可能移除唯一管理员，\n造成管理中断", "增加保护规则\n（跳过本人 / 最后所有者）", "0.5 天"],
    ["多人链接移除端点用错", "该清理动作会失败", "改用 revokeGrants", "0.5 天"],
]
table(s, data, ML, 1.52, [4.05, 3.35, 3.55, 0.98], 0.82, 0.44, 10, 10)
textbox(s, ML, 6.28, CW, 0.34,
        "以上均为离线可开发、可用现有 38 个测试体系覆盖；不影响“查询 + 人工清理 + 验证”先上线。",
        10.5, False, GRAY)
notes(s, "主动暴露问题比被问出来好。这五项都是我们自己在评审里发现的，并且都有明确修法。")

# --------------------------------------------------------------- 09 roadmap ---
s = slide_frame("后续计划与验收标准", "ROADMAP", 9)
stages = [
    ("阶段 0", "本周", "清单 + 人工清理\n+ 只读验证", "无需新授权", GREEN),
    ("阶段 1", "1–2 周", "准确性修复 + 一键命令\n+ 报告导出", "无需新授权", ACCENT),
    ("阶段 2", "A 档到位", "文件级自动清理\n3 个对象试点", "依赖审批", AMBER),
    ("阶段 3", "B 档到位", "组成员自动化\n新旧模型对照数据", "依赖审批", GRAY),
]
sw = (CW - 3 * 0.2) / 4
for i, (name, when, what, need, color) in enumerate(stages):
    x = ML + i * (sw + 0.2)
    card(s, x, 1.55, sw, 2.28, PALE)
    bar = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(1.55),
                             Inches(sw), Inches(0.1))
    bar.fill.solid()
    bar.fill.fore_color.rgb = color
    bar.line.fill.background()
    bar.shadow.inherit = False
    textbox(s, x + 0.22, 1.80, sw - 0.44, 0.3, name, 12.5, True, NAVY)
    textbox(s, x + 0.22, 2.12, sw - 0.44, 0.26, when, 9.5, False, color)
    textbox(s, x + 0.22, 2.46, sw - 0.44, 0.9, what, 10, False, INK, spacing=1.3)
    textbox(s, x + 0.22, 3.46, sw - 0.44, 0.26, need, 8.5, False, GRAY)
textbox(s, ML, 4.18, CW, 0.32, "验收标准（可量化）", 13, True, NAVY)
rule(s, 4.56, ACCENT, 0.03, ML, 0.55)
bullets(s, ML, 4.72, CW, 1.6, [
    ("响应时间　", "输入邮箱后 10 秒内返回三类授权完整清单（离线查库，不调 API）"),
    ("零残留　", "清理后复扫显示：直接授权 0、组成员 0、链接收件人 0"),
    ("可回溯　", "每一次写操作都有审计记录（操作人 / 时间 / 请求 / 响应 / 结果）"),
], 12, 12, 1.35)
notes(s, "阶段 0 和 1 不等授权就能做，这是本周就能给管理层的第一个交付物。")

# ------------------------------------------------------------- 10 decisions ---
s = slide_frame("请管理层决策", "DECISIONS", 10)
decisions = [
    ("D1", "批准 A 档授权",
     "delegated Files.ReadWrite：文件级散落授权自动清理。\n影响面最小，属于“以你本人身份操作你有权写的文件”。", GREEN),
    ("D2", "是否推进 B 档",
     "单站点 Sites.Selected + fullcontrol：组成员与角色分配自动化。\n若认为“组清理可人工”，则本期可不申请。", AMBER),
    ("D3", "确认治理边界",
     "全组织 / 匿名链接、M365 组：保持“输出建议、人工执行”。\n与既有安全边界一致，避免过度授权。", ACCENT),
]
for i, (tag, head, body, color) in enumerate(decisions):
    y = 1.52 + i * 1.30
    card(s, ML, y, CW, 1.14, PALE)
    tagbox = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(ML + 0.22),
                                Inches(y + 0.29), Inches(0.62), Inches(0.56))
    tagbox.fill.solid()
    tagbox.fill.fore_color.rgb = color
    tagbox.line.fill.background()
    tagbox.shadow.inherit = False
    textbox(s, ML + 0.22, y + 0.44, 0.62, 0.28, tag, 11, True, WHITE,
            align=PP_ALIGN.CENTER)
    textbox(s, ML + 1.02, y + 0.18, 4.2, 0.34, head, 14, True, NAVY)
    textbox(s, ML + 1.02, y + 0.56, CW - 1.34, 0.52, body, 10.5, False, INK, spacing=1.3)
card(s, ML, 5.48, CW, 1.16, NAVY)
textbox(s, ML + 0.3, 5.62, CW - 0.6, 0.3, "如果今天只能批一件事",
        10, True, RGBColor(0x9D, 0xBC, 0xE0))
textbox(s, ML + 0.3, 5.90, CW - 0.6, 0.64,
        "批 A 档。它把“文件级散落授权”从人工变成自动，是当前最高价值、最低风险的一步；其余两项不阻塞本周交付。",
        12, True, WHITE, spacing=1.25)
textbox(s, ML, 6.76, CW, 0.28,
        "本周承诺：不等授权，先交付“清单 + 人工清理 + 只读验证”闭环。",
        9.5, False, GRAY)
notes(s, "收尾给一个明确建议：先批 A 档。B 档可以并行申报，但不要卡住本周交付。")

OUT = "s3scope_权限治理_汇报_20261127.pptx"
prs.save(OUT)
print("saved", OUT, "slides=", len(prs.slides))
