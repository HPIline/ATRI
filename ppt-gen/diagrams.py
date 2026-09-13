"""自绘矢量图：结构运动学图、流程链等。

原则：**技术图全部矢量自绘，不用 AI 生图**。
理由：AI 生图会把文字画成乱码、把尺寸标错、把结构画得不成立——
这在一份要接受追问的答辩材料里是致命的。
"""
from __future__ import annotations

from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.util import Inches, Pt

from design import (BLUE, BLUE_300, GRAY, GRAPHITE, GREEN, INK, LINE, MIST,
                    MIST_2, ORANGE, PAPER, WHITE, P, R, rect, vline, hline, text)


# ═══════════════════ 20 DOF 结构运动学图（正视，带关节编号）═══════════════════
# 坐标：x 以身体中线为 0（左负右正），y 自头顶向下，整体高 104 单位。
# 采用机器人学惯用的运动学简图语言——连杆画线、关节画点、编号即 DOF 序号。
# 本构型不含髋偏航轴：每腿 4（髋滚转 / 髋俯仰 / 膝 / 踝），每臂 4（肩俯仰 / 肩滚转 / 肘 / 夹爪）。

# 中线关节：(编号, y, 标签侧)
_SPINE = [(1, 8, "l", "head"), (0, 17, "l", "head"),
          (3, 20, "r", "trunk"), (2, 26, "r", "trunk")]
# 成对关节：(左编号, 右编号, |x|, y, 组)
_PAIRS = [
    (12, 16, 11.0, 30, "arm"), (13, 17, 12.5, 33, "arm"),
    (14, 18, 14.0, 50, "arm"), (15, 19, 15.0, 64, "arm"),
    (4, 8, 7.0, 45, "leg"), (5, 9, 8.0, 49, "leg"),
    (6, 10, 8.5, 74, "leg"), (7, 11, 9.5, 93, "leg"),
]

# 同色系深浅区分四个关节组——单色渐变，不引入新色相
GROUP_COLOR = {"head": "0A2540", "trunk": "1264A3", "arm": "3D7EAE", "leg": "6FA3CB"}
GROUP_LABEL = [("头部 2", "head", 13.0), ("躯干 2", "trunk", 24.5),
               ("双臂 8", "arm", 42.0), ("双腿 8", "leg", 84.0)]


def joint_topology(slide, cx, top, h, labels=True, dim=False):
    """画一张 22 关节结构运动学图，整体高度 h（英寸），水平中心 cx。"""
    s = h / 104.0
    LK = BLUE_300 if not dim else LINE
    JT = BLUE if not dim else BLUE_300
    LB = GRAY if not dim else BLUE_300

    def X(x):
        return cx + x * s

    def Y(y):
        return top + y * s

    def link(x1, y1, x2, y2, w=2.8):
        ln = slide.shapes.add_connector(
            1, Inches(X(x1)), Inches(Y(y1)), Inches(X(x2)), Inches(Y(y2)))
        try:
            ln.shadow.inherit = False
        except Exception:
            pass
        ln.line.color.rgb = RGBColor.from_string(LK)
        ln.line.width = Pt(w)
        return ln

    def joint(x, y, group=None, r=0.078):
        c = GROUP_COLOR.get(group, JT) if not dim else JT
        rect(slide, X(x) - r / 2, Y(y) - r / 2, r, r,
             fill=c, shape=MSO_SHAPE.OVAL)

    def label(n, x, y, side):
        w, hh = 0.34, 0.18
        lx = X(x) + (0.09 if side == "r" else -0.09 - w)
        text(slide, lx, Y(y) - hh / 2, w, hh,
             [P([R(str(n), 7.5, LB, heavy=True)],
                align=PP_ALIGN.RIGHT if side == "l" else PP_ALIGN.LEFT)],
             anchor=MSO_ANCHOR.MIDDLE)

    # ── 头部（运动学简图惯例：圆）
    head_r = 7.2 * s
    rect(slide, X(0) - head_r, Y(8) - head_r, head_r * 2, head_r * 2,
         fill=WHITE, line=LK, line_w=1.5, shape=MSO_SHAPE.OVAL)

    # ── 地面参考线
    link(-13, 101.5, 13, 101.5, 1.0)

    # ── 躯干中线 + 肩/髋横杆
    link(0, 17, 0, 44)                       # 脊柱
    link(-11, 30, 11, 30)                    # 肩横杆
    link(-7, 44, 7, 44)                      # 髋横杆

    # ── 四肢连杆
    for g in (-1, 1):
        link(g * 11, 30, g * 12.5, 33)       # 上臂
        link(g * 12.5, 33, g * 14, 50)       # 前臂
        link(g * 14, 50, g * 15, 64)         # 末端
        link(g * 7, 44, g * 8, 49)           # 髋
        link(g * 8, 49, g * 8.5, 52)         # 大腿根
        link(g * 8.5, 52, g * 8.5, 74)       # 大腿
        link(g * 8.5, 74, g * 9.5, 93)       # 小腿
        link(g * 9.5, 93, g * 10.5, 101, 2.6)  # 足

    # ── 关节 + 编号
    for jid, y, side, grp in _SPINE:
        joint(0, y, grp)
        if labels:
            label(jid, 0, y, side)
    for jl, jr, ax, y, grp in _PAIRS:
        for g in (-1, 1):
            joint(g * ax, y, grp)
            if labels:
                label(jl if g < 0 else jr, g * ax, y, "l" if g < 0 else "r")

    # ── 四组自由度的分组标注（让配色可读，而不是纯装饰）
    if labels:
        for name, grp, gy in GROUP_LABEL:
            # 右边缘固定在关节编号外侧 0.10in，避免与编号相撞
            text(slide, cx - 1.58, Y(gy) - 0.11, 0.75, 0.22,
                 [P([R(name, 8, GROUP_COLOR[grp], heavy=True)],
                    align=PP_ALIGN.RIGHT)], anchor=MSO_ANCHOR.MIDDLE)
    return s


def joint_topology_legend(slide, x, y, w):
    """结构图图例：四组自由度的颜色/数量说明。"""
    rows = [
        ("双臂 8", "每臂 肩俯仰 · 肩滚转 · 肘俯仰 · 夹爪开合"),
        ("双腿 8", "每腿 髋滚转 · 髋俯仰 · 膝俯仰 · 踝俯仰"),
        ("躯干 2", "俯仰 pitch · 横滚 roll"),
        ("头部 2", "偏航 yaw · 俯仰 pitch"),
    ]
    yy = y
    for name, desc in rows:
        text(slide, x, yy, 1.10, 0.24,
             [P([R(name, 11, INK, heavy=True)])])
        text(slide, x + 1.16, yy, w - 1.16, 0.24,
             [P([R(desc, 10, GRAPHITE)])])
        yy += 0.30


# ═══════════════════════ 通用绘图工具 ═══════════════════════
def _seg(slide, x1, y1, x2, y2, color, w_pt):
    from pptx.dml.color import RGBColor
    ln = slide.shapes.add_connector(1, Inches(x1), Inches(y1), Inches(x2), Inches(y2))
    try:
        ln.shadow.inherit = False
    except Exception:
        pass
    ln.line.color.rgb = RGBColor.from_string(color)
    ln.line.width = Pt(w_pt)
    return ln


def _box(slide, x, y, w, h, label, size=11, fill=WHITE, line=BLUE_300,
         color=INK, heavy=True, radius=False):
    rect(slide, x, y, w, h, fill=fill, line=line, line_w=0.75)
    text(slide, x + 0.06, y, w - 0.12, h,
         [P([R(label, size, color, heavy=heavy)], align=PP_ALIGN.CENTER)],
         anchor=MSO_ANCHOR.MIDDLE)


def _rarrow(slide, x, y, w, color=BLUE, w_pt=1.0):
    from pptx.dml.color import RGBColor
    from pptx.oxml.ns import qn
    from lxml import etree
    ln = slide.shapes.add_connector(1, Inches(x), Inches(y), Inches(x + w), Inches(y))
    try:
        ln.shadow.inherit = False
    except Exception:
        pass
    ln.line.color.rgb = RGBColor.from_string(color)
    ln.line.width = Pt(w_pt)
    lnEl = ln.line._get_or_add_ln()
    tail = etree.SubElement(lnEl, qn("a:tailEnd"))
    tail.set("type", "triangle"); tail.set("w", "med"); tail.set("len", "med")
    return ln


# ═══════════════════════ 五项任务流程链 ═══════════════════════
def task_flow(slide, x, y, w, steps, h=0.50):
    return flow_chain(slide, x, y, w, steps, h=h)


# ═══════════════════════ FSM 状态转移图 ═══════════════════════
def fsm_diagram(slide, x, y, w, h):
    """STANDBY → ENTERING → EXECUTING → FEEDBACK → DONE，异常入 ERROR。"""
    states = ["STANDBY", "ENTERING", "EXECUTING", "FEEDBACK", "DONE"]
    cn = ["待机", "任务进入", "技能执行", "结果反馈", "完成"]
    n = len(states)
    gap = 0.24
    bw = (w - (n - 1) * gap) / n
    bh = 0.62
    by = y + (h - bh - 0.72) / 2

    for i, (st, c) in enumerate(zip(states, cn)):
        bx = x + i * (bw + gap)
        fill = MIST if i < n - 1 else WHITE
        line = BLUE_300 if i < n - 1 else GREEN
        rect(slide, bx, by, bw, bh, fill=fill, line=line, line_w=0.75)
        text(slide, bx + 0.04, by, bw - 0.08, bh,
             [P([R(st, 9.5, INK, heavy=True)], align=PP_ALIGN.CENTER),
              P([R(c, 8.5, GRAY)], align=PP_ALIGN.CENTER, space_before=2)],
             anchor=MSO_ANCHOR.MIDDLE)
        if i < n - 1:
            _rarrow(slide, bx + bw + 0.03, by + bh / 2, gap - 0.06)

    # 异常分支
    ey = by + bh + 0.34
    ew = 1.30
    ex = x + w - ew
    rect(slide, ex, ey, ew, 0.36, fill=None, line=ORANGE, line_w=1.0)
    text(slide, ex, ey, ew, 0.36,
         [P([R("ERROR", 9.5, ORANGE, heavy=True)], align=PP_ALIGN.CENTER)],
         anchor=MSO_ANCHOR.MIDDLE)
    for i in (1, 2, 3):
        bx = x + i * (bw + gap) + bw / 2
        _seg(slide, bx, by + bh, bx, ey + 0.18, ORANGE, 0.75)
    _seg(slide, x + 3 * (bw + gap) + bw / 2, ey + 0.18, ex, ey + 0.18, ORANGE, 0.75)
    # 说明文字放在异常总线下方：放在同一高度会被 ENTERING 的下引线穿过
    text(slide, x, ey + 0.26, 3.6, 0.34,
         [P([R("任一环节异常 → ERROR（保留完整状态历史）", 9, GRAY)])])


# ═══════════════════════ 双足步态相位图 ═══════════════════════
def gait_phase(slide, x, y, w, h, period_s=0.8, samples=120):
    """左右腿正弦步态相位图，标出摆动相 / 支撑相。"""
    import math
    left_y = y + h * 0.30
    right_y = y + h * 0.72
    _seg(slide, x, left_y, x + w, left_y, LINE, 0.75)
    _seg(slide, x, right_y, x + w, right_y, LINE, 0.75)

    for lab, ly, col in (("左腿", left_y, BLUE), ("右腿", right_y, BLUE_300)):
        text(slide, x - 0.60, ly - 0.11, 0.54, 0.22,
             [P([R(lab, 9, col, heavy=True)], align=PP_ALIGN.RIGHT)],
             anchor=MSO_ANCHOR.MIDDLE)

    amp = h * 0.19
    prev = None
    for i in range(samples + 1):
        t = i / samples
        px_ = x + w * t
        for ly, ph in ((left_y, 0.0), (right_y, math.pi)):
            v = math.sin(2 * math.pi * t + ph)
            py = ly - v * amp
            if prev is not None:
                _seg(slide, prev[0], prev[1], px_, py,
                     BLUE if ph == 0.0 else BLUE_300, 1.6)
            prev = (px_, py)
        # 摆动相着色
        if math.sin(2 * math.pi * t) > 0:
            rect(slide, px_, left_y - amp, w / samples + 0.004, amp * 2,
                 fill=MIST)
    return


# ═══════════════════════ 视觉伺服闭环图 ═══════════════════════
def servo_loop(slide, x, y, w, h):
    """检测 → 算误差 → 判据 → 调整 / 执行 的闭环框图。"""
    bw, bh = 1.85, 0.62
    cx = x + w / 2
    # 上排：检测 → 计算误差 → 判据
    r1y = y + 0.10
    _box(slide, x, r1y, bw, bh, "相机检测目标", 10.5)
    _rarrow(slide, x + bw + 0.04, r1y + bh / 2, 0.28)
    _box(slide, x + bw + 0.36, r1y, bw, bh, "计算横向误差 x (cm)", 10.5)
    _rarrow(slide, x + 2 * bw + 0.40, r1y + bh / 2, 0.28)
    _box(slide, x + 2 * bw + 0.72, r1y, bw * 0.78, bh, "|x| > 1.0 cm ?",
         10.5, fill=MIST, line=ORANGE, color=ORANGE)

    # 下行：是 → 调整朝向
    dy = r1y + bh + 0.34
    _box(slide, x + 2 * bw + 0.72, dy, bw * 0.78, bh,
         "调整朝向 yaw = clamp(x/2, ±10°)", 9.5, line=ORANGE, color=GRAPHITE)

    # 否 → 执行
    ey = dy + bh + 0.30
    _box(slide, x + 2 * bw + 0.72, ey, bw * 0.78, bh,
         "执行抓取 / 踢球", 10.5, fill=MIST, line=GREEN, color=INK)

    # 回环箭头（调整后回到检测）
    lx = x - 0.02
    _seg(slide, x + 2 * bw + 0.72, dy + bh / 2, lx, dy + bh / 2, BLUE, 1.0)
    _seg(slide, lx, dy + bh / 2, lx, r1y + bh / 2, BLUE, 1.0)
    _rarrow(slide, lx - 0.26, r1y + bh / 2, 0.26)
    text(slide, x + 0.05, dy + bh / 2 - 0.34, 2.6, 0.24,
         [P([R("再检测（回到起点）", 9, BLUE, heavy=True)])])
    text(slide, x + 2 * bw + 1.05, dy + bh + 0.04, 1.6, 0.22,
         [P([R("否", 9, GREEN, heavy=True)])])
    return


# ═══════════════════════ 章节页 ═══════════════════════
def chapter_page(slide, num, title, sub=None):
    """墨蓝满版章节页：大号章节号 + 判断句标题 + 关节节点链装饰。"""
    from design import BLUE_300, PAPER
    rect(slide, 0, 0, 13.3333, 7.5, fill=INK)
    # 淡网格
    for i in range(1, 24):
        _seg(slide, i * 0.58, 0, i * 0.58, 7.5, "14304F", 0.5)
    for j in range(1, 13):
        _seg(slide, 0, j * 0.58, 13.3333, j * 0.58, "14304F", 0.5)
    text(slide, 1.10, 2.30, 9.0, 1.40,
         [P([R(num, 120, "1B3A5C", heavy=True)])])
    rect(slide, 1.14, 3.92, 0.80, 0.05, fill=ORANGE)
    text(slide, 1.10, 4.24, 9.6, 1.00,
         [P([R(title, 32, WHITE, heavy=True)], line_spacing=1.18)])
    if sub:
        text(slide, 1.10, 5.42, 9.6, 0.40,
             [P([R(sub, 13.5, BLUE_300)])])
    # 右侧关节链
    for i in range(20):
        y = 1.55 + i * 0.21
        c = ORANGE if i == 0 else "2E5A82"
        rect(slide, 11.85, y, 0.10, 0.10, fill=c, shape=MSO_SHAPE.OVAL)
        if i < 19:
            _seg(slide, 11.90, y + 0.05, 11.90, y + 0.21, "2E5A82", 1.0)


# ═══════════════════════ 价格带对比 ═══════════════════════
def price_bands(slide, x, y, w, h, bands):
    """bands = [(名称, 低位元, 高位元, 颜色, 备注), ...]；对数横轴。"""
    import math
    lo_exp, hi_exp = 3.0, 5.5                      # 10^3 元 ~ 10^5.5 元
    def px_of(v):
        return x + (math.log10(v) - lo_exp) / (hi_exp - lo_exp) * w
    _seg(slide, x, y + h - 0.30, x + w, y + h - 0.30, LINE, 1.0)
    for e in (3, 4, 5):
        gx = px_of(10 ** e)
        _seg(slide, gx, y + h - 0.30, gx, y + h - 0.24, LINE, 1.0)
        text(slide, gx - 0.30, y + h - 0.22, 0.60, 0.22,
             [P([R(f"¥10^{e}", 8.5, GRAY)], align=PP_ALIGN.CENTER)])
    bh = (h - 0.55) / len(bands) - 0.12
    for i, (name, lo, hi, col, note) in enumerate(bands):
        by = y + i * (bh + 0.12)
        text(slide, x - 0.02, by - 0.24, 3.2, 0.22,
             [P([R(name, 10, GRAPHITE, heavy=True)])])
        bx1, bx2 = px_of(lo), px_of(hi)
        rect(slide, bx1, by, max(bx2 - bx1, 0.06), bh, fill=col)
        text(slide, bx2 + 0.10, by, w - (bx2 - x) - 0.10, bh,
             [P([R(note, 9, GRAY)])], anchor=MSO_ANCHOR.MIDDLE)


# ═══════════════════════ 二维定位图 ═══════════════════════
def positioning_map(slide, x, y, w, h, points):
    """points = [(名称, 价格 0..1, 开放度 0..1, 颜色, 标签侧), ...]"""
    _seg(slide, x, y + h, x + w, y + h, LINE, 1.0)
    _seg(slide, x, y, x, y + h, LINE, 1.0)
    text(slide, x + w - 2.6, y + h + 0.10, 2.6, 0.22,
         [P([R("整机价格 →", 9, GRAY)], align=PP_ALIGN.RIGHT)])
    text(slide, x - 0.10, y - 0.30, 3.0, 0.22,
         [P([R("软件开放度 ↑", 9, GRAY)])])
    # 空白区
    rect(slide, x + 0.02, y + h * 0.62, w * 0.34, h * 0.36,
         fill=MIST, line=None)
    text(slide, x + 0.10, y + h * 0.62 + 0.06, w * 0.34, 0.22,
         [P([R("当前空白区", 8.5, BLUE)])])
    for name, px_, py_, col, side in points:
        cx_, cy_ = x + px_ * w, y + h - py_ * h
        rect(slide, cx_ - 0.055, cy_ - 0.055, 0.11, 0.11, fill=col,
             shape=MSO_SHAPE.OVAL)
        if side == "r":
            text(slide, cx_ + 0.12, cy_ - 0.11, 2.6, 0.22,
                 [P([R(name, 9.5, GRAPHITE, heavy=True)])])
        else:
            text(slide, cx_ - 2.72, cy_ - 0.11, 2.6, 0.22,
                 [P([R(name, 9.5, GRAPHITE, heavy=True)],
                    align=PP_ALIGN.RIGHT)])


# ═══════════════════════ 收敛漏斗 ═══════════════════════
def funnel(slide, x, y, w, h, levels):
    """levels = [(标签, 说明, 宽度比例), ...] 自上而下收窄。"""
    n = len(levels)
    rh = h / n
    for i, (lab, desc, ratio) in enumerate(levels):
        by = y + i * rh
        bw = w * ratio
        rect(slide, x + (w - bw) / 2, by + 0.05, bw, rh - 0.16, fill=MIST)
        text(slide, x + (w - bw) / 2 + 0.16, by + 0.05, bw - 0.32, rh - 0.16,
             [P([R(lab, 11, INK, heavy=True), R("　" + desc, 9.5, GRAPHITE)])],
             anchor=MSO_ANCHOR.MIDDLE)


# ═══════════════════════ 甘特图 ═══════════════════════
def gantt(slide, x, y, w, h, rows, cols=4):
    """rows = [(阶段名, 起始列 0..cols-1, 跨列数, 颜色, 状态标签), ...]"""
    colw = w / cols
    rh = (h - 0.30) / len(rows)
    for c in range(cols):
        text(slide, x + c * colw, y, colw, 0.24,
             [P([R(f"阶段 {c+1}", 9, GRAY)], align=PP_ALIGN.CENTER)])
        _seg(slide, x + c * colw, y + 0.26, x + c * colw, y + h, LINE, 0.5)
    for i, (name, st, span, col, tag) in enumerate(rows):
        by = y + 0.34 + i * rh
        rect(slide, x + st * colw + 0.05, by + 0.04, span * colw - 0.10, rh - 0.20,
             fill=col)
        text(slide, x + st * colw + 0.14, by + 0.04, span * colw - 0.28, rh - 0.20,
             [P([R(name, 9.5, WHITE, heavy=True)])], anchor=MSO_ANCHOR.MIDDLE)
        text(slide, x - 0.05, by + 0.04, 0.0, rh - 0.20, [P([R("")])])


# ═══════════════════════ 简单流程链（横向 N 步 + 说明）═══════════════════════
def pipeline_strip(slide, x, y, w, steps, h=0.40, size=9.5, color=BLUE):
    """一行紧凑流程条：A → B → C，用文字 + 箭头，不画方框。"""
    n = len(steps)
    seg = w / n
    for i, s in enumerate(steps):
        text(slide, x + i * seg, y, seg - 0.24, h,
             [P([R(s, size, GRAPHITE, heavy=True)],
                align=PP_ALIGN.CENTER)], anchor=MSO_ANCHOR.MIDDLE)
        if i < n - 1:
            text(slide, x + (i + 1) * seg - 0.26, y, 0.24, h,
                 [P([R("→", size, color, heavy=True)],
                    align=PP_ALIGN.CENTER)], anchor=MSO_ANCHOR.MIDDLE)


# ═══════════════════════ 已实现/待开发 双列状态块 ═══════════════════════
def impl_status(slide, x, y, w, done, todo):
    """done/todo = [(文字), ...]，两栏对照。"""
    colw = (w - 0.40) / 2
    rect(slide, x, y, colw, 0.32, fill=GREEN)
    text(slide, x + 0.12, y, colw - 0.24, 0.32,
         [P([R("● 已实现", 10, WHITE, heavy=True)])], anchor=MSO_ANCHOR.MIDDLE)
    rect(slide, x + colw + 0.40, y, colw, 0.32, fill=GRAY)
    text(slide, x + colw + 0.52, y, colw - 0.24, 0.32,
         [P([R("○ 待开发", 10, WHITE, heavy=True)])], anchor=MSO_ANCHOR.MIDDLE)
    yy = y + 0.42
    for t in done:
        rect(slide, x, yy + 0.055, 0.05, 0.05, fill=GREEN, shape=MSO_SHAPE.OVAL)
        text(slide, x + 0.16, yy - 0.02, colw - 0.16, 0.62,
             [P([R(t, 9.5, GRAPHITE)], line_spacing=1.30)])
        # 行距按实际折行数自适应：每行约 24 个汉字宽
        yy += 0.22 + 0.20 * max(1, -(-len(t) // 24))
    yy = y + 0.42
    for t in todo:
        rect(slide, x + colw + 0.40, yy + 0.055, 0.05, 0.05, fill=GRAY,
             shape=MSO_SHAPE.OVAL)
        text(slide, x + colw + 0.56, yy - 0.02, colw - 0.16, 0.62,
             [P([R(t, 9.5, GRAPHITE)], line_spacing=1.30)])
        yy += 0.22 + 0.20 * max(1, -(-len(t) // 24))
