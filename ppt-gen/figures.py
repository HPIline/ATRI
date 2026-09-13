"""数据图形构件：把实测数字画成图，而不是堆成表。

设计约束沿用 design.py：直角、细线、无阴影、无渐变；颜色只用设计系统里的
墨蓝 / 结构蓝 / 蓝雾 / 朱橙 / 验证绿 / 中性灰。朱橙是唯一强调色，一股数据里
只用它标「超限」或「当前值」，不做彩虹配色。

图表全部靠矩形与连线自绘，不引入 matplotlib 图片——那样会带进来一套独立配色，
和设计系统打架。
"""
from __future__ import annotations

from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.util import Inches, Pt

from design import (BLUE, BLUE_300, GRAY, GRAPHITE, GREEN, INK, LINE, MIST,
                    MIST_2, ORANGE, PAPER, WHITE, P, R, hline, rect, text,
                    vline)


# ═══════════════════ 横向条形：扭矩负载占额定百分比 ═══════════════════
def torque_bars(slide, x, y, w, rows, *, rated=100.0, max_pct=160.0,
                label_w=1.55, bar_h=0.235, gap=0.115):
    """rows = [(关节名, 百分比, 说明), ...]，按给定顺序自上而下画。

    100% 处画一条额定参考线；超限的条用朱橙，未超的用结构蓝。
    """
    bx = x + label_w + 0.12
    bw = w - label_w - 1.30
    scale = bw / max_pct

    # 参考线
    vline(slide, bx + rated * scale, y - 0.10, len(rows) * (bar_h + gap) + 0.06,
          color=ORANGE, width=1.0)
    text(slide, bx + rated * scale - 1.10, y - 0.36, 2.20, 0.22,
         [P([R(f"官方连续额定 {rated:.0f}%", 8.5, ORANGE, heavy=True)],
            align=PP_ALIGN.CENTER)])

    yy = y
    for name, pct, note in rows:
        over = pct > rated
        text(slide, x, yy, label_w, bar_h,
             [P([R(name, 10, INK, heavy=True)])], anchor=MSO_ANCHOR.MIDDLE)
        rect(slide, bx, yy + 0.035, max(pct * scale, 0.02), bar_h - 0.07,
             fill=ORANGE if over else BLUE)
        text(slide, bx + pct * scale + 0.10, yy, 1.30, bar_h,
             [P([R(f"{pct:.1f}%", 9.5, ORANGE if over else GRAY, heavy=over)])],
             anchor=MSO_ANCHOR.MIDDLE)
        if note:
            text(slide, x, yy + bar_h * 0.82, label_w + 0.10, 0.20,
                 [P([R(note, 7.5, GRAY)])])
        yy += bar_h + gap
    return yy - y


# ═══════════════════ 横向区间条：包络 / 范围对照 ═══════════════════
def range_bars(slide, x, y, w, rows, *, label_w=1.30, bar_h=0.30,
               gap=0.34, unit="mm"):
    """rows = [(名称, 当前值, 上限值, 颜色, 右侧注), ...]，画「当前 vs 上限」。"""
    bx = x + label_w
    bw = w - label_w - 1.90
    vmax = max(r[2] for r in rows) * 1.06
    scale = bw / vmax
    for name, cur, cap, col, note in rows:
        text(slide, x, yy_row := y, label_w - 0.10, bar_h,
             [P([R(name, 10, INK, heavy=True)])], anchor=MSO_ANCHOR.MIDDLE)
        rect(slide, bx, y + 0.03, cap * scale, bar_h - 0.06, fill=MIST_2)
        rect(slide, bx, y + 0.03, max(cur * scale, 0.02), bar_h - 0.06, fill=col)
        text(slide, bx + cap * scale + 0.12, y, 1.80, bar_h,
             [P([R(f"{cur:g} / {cap:g} {unit}", 9, GRAY)])],
             anchor=MSO_ANCHOR.MIDDLE)
        if note:
            text(slide, bx + cap * scale + 0.12, y + bar_h - 0.02, 2.60, 0.20,
                 [P([R(note, 7.5, GRAY)])])
        y += bar_h + gap
    return y - yy_row - gap


# ═══════════════════ 堆叠条：质量构成 ═══════════════════
def stacked_mass(slide, x, y, w, h, parts, *, total_label=None, vmax=None):
    """parts = [(名称, 克数, 颜色), ...]，横向堆叠；留 vmax 做刻度量程。"""
    total = sum(p[1] for p in parts)
    vmax = vmax or total * 1.02
    scale = w / vmax
    cx = x
    for name, grams, col in parts:
        seg = grams * scale
        rect(slide, cx, y, seg, h, fill=col)
        cx += seg
    # 刻度
    step = 1000
    tick = 0
    while tick <= vmax:
        gx = x + tick * scale
        text(slide, gx - 0.30, y + h + 0.06, 0.60, 0.20,
             [P([R(f"{tick}", 8, GRAY)], align=PP_ALIGN.CENTER)])
        tick += step
    # 图例
    lx = x
    ly = y + h + 0.34
    for name, grams, col in parts:
        rect(slide, lx, ly + 0.055, 0.115, 0.115, fill=col)
        text(slide, lx + 0.20, ly - 0.01, 3.4, 0.24,
             [P([R(f"{name} {grams:g} g", 9, GRAPHITE)])])
        lx += 2.62
        if lx > x + w - 1.6:
            lx = x
            ly += 0.30
    if total_label:
        text(slide, x, y - 0.36, w, 0.28,
             [P([R(total_label, 12, INK, heavy=True)])])
    return h + 0.34 + (ly - (y + h + 0.34)) + 0.30


# ═══════════════════ 百分比对比条（两两一组） ═══════════════════
def pct_pairs(slide, x, y, w, groups, *, label_w=2.05, bar_h=0.20,
              gap=0.10, group_gap=0.30, max_pct=100.0, legend=None):
    """groups = [(组名, [(子标签, 百分比, 颜色), ...]), ...]"""
    bx = x + label_w
    bw = w - label_w - 0.90
    scale = bw / max_pct
    yy = y
    if legend:
        lx = bx
        for lab, col in legend:
            rect(slide, lx, y - 0.30, 0.115, 0.115, fill=col)
            text(slide, lx + 0.20, y - 0.36, 2.2, 0.24,
                 [P([R(lab, 8.5, GRAY)])])
            lx += 2.30
        yy = y
    for gname, subs in groups:
        g0 = yy
        for i, (sub, pct, col) in enumerate(subs):
            rect(slide, bx, yy + 0.02, max(pct * scale, 0.02), bar_h, fill=col)
            text(slide, bx + pct * scale + 0.10, yy - 0.02, 0.90, bar_h,
                 [P([R(f"{pct:g}%", 8.5, GRAY)])], anchor=MSO_ANCHOR.MIDDLE)
            if i == 0:
                text(slide, x, yy - 0.06, label_w - 0.10, 0.50,
                     [P([R(sub, 9, GRAPHITE)], line_spacing=1.15)])
            else:
                text(slide, x + 0.14, yy - 0.09, label_w - 0.14, 0.20,
                     [P([R(sub, 8.5, GRAY)])])
            yy += bar_h + gap
        text(slide, x, g0 - 0.30, label_w + 2.0, 0.24,
             [P([R(gname, 10, INK, heavy=True)])])
        yy += group_gap
    return yy - y


# ═══════════════════ 刻度尺：一维距离 / 尺寸示意 ═══════════════════
def scale_ruler(slide, x, y, w, items, *, unit="cm", note=None):
    """items = [(位置值, 标签, 颜色, 是否强调), ...]；画一条真实比例的刻度尺。"""
    vmax = max(i[0] for i in items) * 1.12
    scale = w / vmax
    hline(slide, x, y, w, color=BLUE_300, width=1.0)
    for i in range(0, int(vmax) + 1, max(1, int(vmax // 8))):
        gx = x + i * scale
        vline(slide, gx, y - 0.05, 0.10, color=BLUE_300, width=0.75)
        text(slide, gx - 0.25, y + 0.08, 0.50, 0.20,
             [P([R(f"{i}", 7.5, GRAY)], align=PP_ALIGN.CENTER)])
    # 刻度尺下方的段
    for pos, label, col, strong in items:
        cx = x + pos * scale
        rect(slide, cx - 0.045, y - 0.045, 0.09, 0.09, fill=col,
             shape=MSO_SHAPE.OVAL)
        if strong:
            rect(slide, cx - 0.018, y - 0.30, 0.036, 0.26, fill=col)
            text(slide, cx - 1.05, y - 0.60, 2.10, 0.28,
                 [P([R(label, 9, col, heavy=True)], align=PP_ALIGN.CENTER)])
        else:
            vline(slide, cx, y + 0.24, 0.12, color=col, width=0.75)
            text(slide, cx - 1.05, y + 0.38, 2.10, 0.24,
                 [P([R(label, 8.5, col)], align=PP_ALIGN.CENTER)])
    if note:
        text(slide, x, y + 0.72, w, 0.24,
             [P([R(note, 8.5, GRAY)])])


# ═══════════════════ 阶梯图：参数扫描的收敛阶梯 ═══════════════════
def step_ladder(slide, x, y, w, h, steps, *, note=None):
    """steps = [(标签, 说明, 达成比例 0..1), ...] 自上而下递减，画成阶梯。"""
    n = len(steps)
    rh = h / n
    for i, (lab, desc, ratio) in enumerate(steps):
        by = y + i * rh
        rect(slide, x, by + 0.06, w * ratio, rh - 0.18, fill=MIST_2)
        rect(slide, x, by + 0.06, 0.045, rh - 0.18,
             fill=ORANGE if i == 0 else BLUE)
        text(slide, x + 0.20, by + 0.06, w - 0.40, rh - 0.18,
             [P([R(lab, 10.5, INK, heavy=True),
                 R("　" + desc, 9.5, GRAPHITE)])],
             anchor=MSO_ANCHOR.MIDDLE)
    if note:
        text(slide, x, y + h + 0.05, w, 0.24, [P([R(note, 8.5, GRAY)])])


# ═══════════════════ 三视图并排（图 + 图注） ═══════════════════
def view_triptych(slide, x, y, w, h, items, *, caption_h=0.30, gap=0.22):
    """items = [(图片路径, 标题, 图注), ...]，按统一高度并排，底部对齐。"""
    n = len(items)
    cell = (w - (n - 1) * gap) / n
    for i, (path, title, note) in enumerate(items):
        cx = x + i * (cell + gap)
        text(slide, cx, y, cell, 0.24,
             [P([R(title, 10.5, INK, heavy=True)])])
        from design import picture_fit
        picture_fit(slide, cx, y + 0.28, cell, h - caption_h - 0.28, path)
        text(slide, cx, y + h - caption_h + 0.02, cell, caption_h - 0.02,
             [P([R(note, 8.5, GRAY)], line_spacing=1.18)])
