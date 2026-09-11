"""A.T.R.I. 答辩 PPT 设计系统。

设计语言：「工程蓝图 × 关节节点」
- 结构蓝承担 80% 视觉，朱橙只用于真正需要看的地方（每页不超过 2 处）
- 直角、细线、大留白；无圆角、无阴影、无渐变
- 每页固定构件：页眉 / 判断句标题 / 导语 / 正文 / 状态标签条 / 页脚

所有长度为英寸（inch）。
"""
from __future__ import annotations

from lxml import etree
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE, MSO_CONNECTOR
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt, Emu

# ────────────────────────────── 画布 ──────────────────────────────
SLIDE_W = 13.3333
SLIDE_H = 7.5

MARGIN_L = 0.833
MARGIN_R = 0.833
CONTENT_W = SLIDE_W - MARGIN_L - MARGIN_R          # 11.667
CONTENT_X = MARGIN_L

# 页眉基线 / 标题区 / 内容区 / 页脚
Y_HEADER = 0.40
Y_TITLE = 0.78
Y_LEAD = 1.62                                       # 导语基线
Y_RULE = 2.02                                       # 标题下分隔线
Y_BODY = 2.24                                       # 正文起始
Y_STATUSBAR = 6.58                                  # 状态标签条
Y_FOOTER = 7.02

# ────────────────────────────── 颜色 ──────────────────────────────
INK = "0A2540"        # 墨蓝  章节页底 / 主标题 / 大数字
BLUE = "1264A3"       # 结构蓝 主色
MIST = "E8F0F7"       # 蓝雾  卡片底
MIST_2 = "DCE9F4"     # 深一档蓝雾
BLUE_300 = "9CC0DC"   # 浅蓝  次级线条
PAPER = "F7F9FB"      # 纸白  页面底
WHITE = "FFFFFF"
GRAPHITE = "1F2A37"   # 石墨  正文
GRAY = "6B7A8C"       # 中性灰 次要说明
LINE = "D8E2EC"       # 卡片描边
ORANGE = "E4572E"     # 朱橙  唯一强调色
GREEN = "2E9E7B"      # 验证绿 状态语义色

# ────────────────────────────── 字体 ──────────────────────────────
FONT = "Source Han Sans SC"           # 正文 / 常规
FONT_HEAVY = "Source Han Sans SC Heavy"  # 标题 / 大数字 / 强调

# ────────────────────────────── 状态标签 ──────────────────────────────
STATUS = {
    "done": ("●", "已完成", GREEN),
    "doing": ("◐", "进行中", ORANGE),
    "plan": ("○", "规划中", GRAY),
    "design": ("◇", "设计目标", BLUE),
}


# ═══════════════════════════ 基础图元 ═══════════════════════════
def new_deck() -> Presentation:
    prs = Presentation()
    prs.slide_width = Inches(SLIDE_W)
    prs.slide_height = Inches(SLIDE_H)
    return prs


def add_slide(prs: Presentation, bg: str = PAPER):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = RGBColor.from_string(bg)
    return slide


def _no_shadow(shape) -> None:
    try:
        shape.shadow.inherit = False
    except Exception:
        pass


def rect(slide, x, y, w, h, fill=None, line=None, line_w=0.75,
         shape=MSO_SHAPE.RECTANGLE, dash=None):
    sp = slide.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
    _no_shadow(sp)
    if fill:
        sp.fill.solid()
        sp.fill.fore_color.rgb = RGBColor.from_string(fill)
    else:
        sp.fill.background()
    if line:
        sp.line.color.rgb = RGBColor.from_string(line)
        sp.line.width = Pt(line_w)
        if dash:
            sp.line.dash_style = dash
    else:
        sp.line.fill.background()
    sp.text_frame.word_wrap = True
    return sp


def hline(slide, x, y, w, color=LINE, width=0.75, dash=None):
    ln = slide.shapes.add_connector(
        MSO_CONNECTOR.STRAIGHT, Inches(x), Inches(y), Inches(x + w), Inches(y))
    _no_shadow(ln)
    ln.line.color.rgb = RGBColor.from_string(color)
    ln.line.width = Pt(width)
    if dash:
        ln.line.dash_style = dash
    return ln


def vline(slide, x, y, h, color=LINE, width=0.75, dash=None):
    ln = slide.shapes.add_connector(
        MSO_CONNECTOR.STRAIGHT, Inches(x), Inches(y), Inches(x), Inches(y + h))
    _no_shadow(ln)
    ln.line.color.rgb = RGBColor.from_string(color)
    ln.line.width = Pt(width)
    if dash:
        ln.line.dash_style = dash
    return ln


def arrow(slide, x, y, w, color=BLUE, width=1.0):
    """水平右向箭头：细线 + 三角头。"""
    ln = slide.shapes.add_connector(
        MSO_CONNECTOR.STRAIGHT, Inches(x), Inches(y), Inches(x + w), Inches(y))
    _no_shadow(ln)
    ln.line.color.rgb = RGBColor.from_string(color)
    ln.line.width = Pt(width)
    lnEl = ln.line._get_or_add_ln()
    tail = etree.SubElement(lnEl, qn("a:tailEnd"))
    tail.set("type", "triangle")
    tail.set("w", "med")
    tail.set("len", "med")
    return ln


# ═══════════════════════════ 文本 ═══════════════════════════
def _style_run(run, name, size, bold, color, spc=None, italic=False):
    f = run.font
    f.size = Pt(size)
    f.bold = bold
    f.italic = italic
    f.color.rgb = RGBColor.from_string(color)
    f.name = name                       # a:latin
    rPr = run._r.get_or_add_rPr()
    for tag in ("a:ea", "a:cs"):
        el = rPr.find(qn(tag))
        if el is None:
            el = etree.SubElement(rPr, qn(tag))
        el.set("typeface", name)
    if spc is not None:
        rPr.set("spc", str(int(spc * 100)))


def text(slide, x, y, w, h, paras, anchor=MSO_ANCHOR.TOP, wrap=True):
    """paras: [ {runs:[{t,size,color,heavy,spc,italic}], align, space_before,
                 space_after, line_spacing} ]"""
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = wrap
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = anchor
    for i, spec in enumerate(paras):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = spec.get("align", PP_ALIGN.LEFT)
        if spec.get("space_before") is not None:
            p.space_before = Pt(spec["space_before"])
        if spec.get("space_after") is not None:
            p.space_after = Pt(spec["space_after"])
        if spec.get("line_spacing") is not None:
            p.line_spacing = spec["line_spacing"]
        for r in spec["runs"]:
            run = p.add_run()
            run.text = r["t"]
            _style_run(
                run,
                FONT_HEAVY if r.get("heavy") else FONT,
                r.get("size", 14),
                r.get("bold", False),
                r.get("color", GRAPHITE),
                spc=r.get("spc"),
                italic=r.get("italic", False),
            )
    return tb


def P(runs, align=PP_ALIGN.LEFT, space_before=None, space_after=None,
      line_spacing=None):
    if isinstance(runs, dict):
        runs = [runs]
    return {"runs": runs, "align": align, "space_before": space_before,
            "space_after": space_after, "line_spacing": line_spacing}


def R(t, size=14, color=GRAPHITE, heavy=False, bold=False, spc=None, italic=False):
    return {"t": t, "size": size, "color": color, "heavy": heavy,
            "bold": bold, "spc": spc, "italic": italic}


# ═══════════════════════════ 页面构件 ═══════════════════════════
def page_frame(slide, chapter_no, chapter_name, page_no, total=24, dark=False,
               right_label=None):
    """页眉 + 页脚。right_label 缺省显示「第 N 章」；概要/结尾页可传其他文案。"""
    if right_label is None:
        right_label = f"第 {int(chapter_no)} 章"
    fg = BLUE_300 if dark else BLUE
    muted = BLUE_300 if dark else GRAY
    text(slide, CONTENT_X, Y_HEADER, 6.0, 0.24,
         [P([R(f"{chapter_no}", 10, fg, heavy=True),
             R(f"  {chapter_name}", 10, muted)])])
    text(slide, CONTENT_X + 6.0, Y_HEADER, CONTENT_W - 6.0, 0.24,
         [P([R(right_label, 9, muted)], align=PP_ALIGN.RIGHT)])
    hline(slide, CONTENT_X, Y_FOOTER - 0.22, CONTENT_W,
          color=BLUE_300 if dark else LINE, width=0.75)
    text(slide, CONTENT_X, Y_FOOTER, 6.0, 0.22,
         [P([R("A.T.R.I. 桌面自主人形智能", 9, muted)])])
    text(slide, CONTENT_X + 6.0, Y_FOOTER, CONTENT_W - 6.0, 0.22,
         [P([R(f"{page_no:02d} / {total}", 9, muted)], align=PP_ALIGN.RIGHT)])


def page_title(slide, title, lead=None, dark=False, title_size=30,
               rule=True, sub=None):
    """判断句标题 + 导语 + 标题下细线。"""
    tcolor = WHITE if dark else INK
    lcolor = BLUE_300 if dark else GRAY
    paras = [P([R(title, title_size, tcolor, heavy=True)], line_spacing=1.12)]
    if sub:
        paras.append(P([R(sub, 13, BLUE if not dark else BLUE_300, spc=0.6)],
                       space_before=8, line_spacing=1.15))
    text(slide, CONTENT_X, Y_TITLE, CONTENT_W, Y_LEAD - Y_TITLE - 0.06, paras)
    if lead:
        text(slide, CONTENT_X, Y_LEAD, CONTENT_W, Y_RULE - Y_LEAD - 0.06,
             [P([R(lead, 13.5, lcolor)], line_spacing=1.25)])
    if rule:
        hline(slide, CONTENT_X, Y_RULE, CONTENT_W,
              color=BLUE_300 if dark else LINE, width=0.75)


def status_chip(slide, x, y, kind, w=None, h=0.26, size=10.5):
    """单个状态标签：● 已完成"""
    sym, label, color = STATUS[kind]
    if w is None:
        # 宽度 = 左内边距 + (符号 1 字 + 半角空格 + 标签汉字数) × 字号 + 右内边距
        w = 0.12 + (len(label) + 1) * size / 72.0 + 0.14
    rect(slide, x, y, w, h, fill=MIST if kind != "done" else MIST,
         line=None)
    text(slide, x + 0.10, y, w - 0.16, h,
         [P([R(sym, size, color, heavy=True), R(" " + label, size, color)])],
         anchor=MSO_ANCHOR.MIDDLE)
    return w


def status_chip_inline(slide, x, y, kind, size=10.5):
    """无底色状态标签（用于正文行内）。"""
    sym, label, color = STATUS[kind]
    tb = text(slide, x, y, 1.6, 0.22,
              [P([R(sym, size, color, heavy=True), R(" " + label, size, color)])])
    return tb


def status_bar(slide, kinds, dark=False):
    """页脚上方的状态标签条（本页声明的状态范围）。"""
    if not kinds:
        return
    x = CONTENT_X
    y = Y_STATUSBAR
    text(slide, x, y, 0.78, 0.26,
         [P([R("本页状态", 10, BLUE_300 if dark else GRAY)])],
         anchor=MSO_ANCHOR.MIDDLE)
    x += 0.84
    for k in kinds:
        w = status_chip(slide, x, y, k)
        x += w + 0.16


def card(slide, x, y, w, h, fill=WHITE, line=LINE, accent=None, accent_h=0.045):
    """标准卡片：直角 + 细描边；accent 为顶部强调条颜色。"""
    rect(slide, x, y, w, h, fill=fill, line=line, line_w=0.75)
    if accent:
        rect(slide, x, y, w, accent_h, fill=accent)
    return (x, y, w, h)


def num_card(slide, x, y, w, h, number, unit, caption, color=INK, unit_size=15,
             num_size=40, caption_size=10.5):
    rect(slide, x, y, w, h, fill=WHITE, line=LINE, line_w=0.75)
    rect(slide, x, y, 0.045, h, fill=BLUE)
    text(slide, x + 0.24, y + 0.14, w - 0.40, 0.66,
         [P([R(number, num_size, color, heavy=True),
             R(" " + unit, unit_size, color, heavy=True)])])
    text(slide, x + 0.24, y + 0.84, w - 0.40, h - 0.94,
         [P([R(caption, caption_size, GRAY)], line_spacing=1.28)])


def picture_cover(slide, x, y, w, h, path, focus_x=0.5, focus_y=0.5):
    """把图片按「填满并裁切」方式放进 x,y,w,h（等价 CSS object-fit: cover）。

    focus_x / focus_y 决定裁切偏向：0.0 = 保留左边/上边，1.0 = 保留右边/下边。
    """
    from PIL import Image

    with Image.open(path) as im:
        iw, ih = im.size
    img_ar, box_ar = iw / ih, w / h
    pic = slide.shapes.add_picture(path, Inches(x), Inches(y), Inches(w), Inches(h))
    if img_ar > box_ar:                      # 图更宽 → 裁左右
        extra = 1.0 - box_ar / img_ar
        left = extra * focus_x
        pic.crop_left, pic.crop_right = left, extra - left
    elif img_ar < box_ar:                    # 图更高 → 裁上下
        extra = 1.0 - img_ar / box_ar
        top = extra * focus_y
        pic.crop_top, pic.crop_bottom = top, extra - top
    return pic


def joint_chain(slide, x, y, h, n=22, color=BLUE_300, dot=0.055, gap_ratio=0.62):
    """关节节点装饰：n 个圆点连成竖向拓扑链（每个点 = 一个自由度）。"""
    step = h / (n - 1)
    vline(slide, x + dot / 2, y + dot / 2, h - dot, color=color, width=1.0)
    for i in range(n):
        cy = y + i * step
        rect(slide, x, cy, dot, dot, fill=color, shape=MSO_SHAPE.OVAL)


def joint_chain_h(slide, x, y, w, n=22, color=BLUE_300, dot=0.085,
                  first_color=None):
    """横向关节节点链：n 个圆点 = n 个自由度。第一个点可单独着色。"""
    step = (w - dot) / (n - 1)
    hline(slide, x + dot / 2, y + dot / 2, w - dot, color=color, width=1.0)
    for i in range(n):
        cx = x + i * step
        c = first_color if (i == 0 and first_color) else color
        rect(slide, cx, y, dot, dot, fill=c, shape=MSO_SHAPE.OVAL)


# ═══════════════════════════ 版面构件 ═══════════════════════════
def flow_chain(slide, x, y, w, steps, h=0.50, size=10.5, gap=0.30,
               fill=WHITE, line=BLUE_300, txt=INK, heavy=True):
    """横向流程链：n 个方框 + n-1 个箭头。返回总高。"""
    n = len(steps)
    bw = (w - (n - 1) * gap) / n
    for i, t in enumerate(steps):
        bx = x + i * (bw + gap)
        rect(slide, bx, y, bw, h, fill=fill, line=line, line_w=0.75)
        text(slide, bx + 0.06, y, bw - 0.12, h,
             [P([R(t, size, txt, heavy=heavy)], align=PP_ALIGN.CENTER)],
             anchor=MSO_ANCHOR.MIDDLE)
        if i < n - 1:
            arrow(slide, bx + bw + 0.05, y + h / 2, gap - 0.10)
    return h


def bullets(slide, x, y, w, items, gap=0.52, name_size=11, desc_size=10.5,
            indent=0.20, dot=True):
    """要点列表：朱橙圆点 + 加粗名称 + 正文描述。items = [(名称, 描述), ...]"""
    yy = y
    for name, desc in items:
        if dot:
            rect(slide, x, yy + 0.055, 0.055, 0.055, fill=ORANGE,
                 shape=MSO_SHAPE.OVAL)
        runs = [R(name + "　", name_size, INK, heavy=True)]
        if desc:
            runs.append(R(desc, desc_size, GRAPHITE))
        text(slide, x + indent, yy - 0.02, w - indent, 0.30, [P(runs)])
        yy += gap
    return yy - y


def code_block(slide, x, y, w, lines, size=9, lh=0.185, fill=MIST, pad=0.14,
               color=GRAPHITE):
    """代码 / 终端输出块：等宽、蓝雾底、直角。"""
    h = len(lines) * lh + pad * 2
    rect(slide, x, y, w, h, fill=fill)
    rect(slide, x, y, 0.035, h, fill=BLUE_300)
    paras = [P([R(t, size, color)], line_spacing=lh / (size / 72.0) / 1.45)
             for t in lines]
    text(slide, x + 0.18, y + pad, w - 0.30, h - pad * 2, paras)
    return h


def table(slide, x, y, w, headers, rows, col_w=None, row_h=0.36,
          head_h=0.34, size=10, head_size=10):
    """极简表格：蓝雾表头 + 细线行。col_w 为各列宽度（不传则等分）。"""
    n = len(headers)
    if col_w is None:
        col_w = [w / n] * n
    rect(slide, x, y, w, head_h, fill=MIST)
    cx = x
    for i, htxt in enumerate(headers):
        text(slide, cx + 0.10, y, col_w[i] - 0.20, head_h,
             [P([R(htxt, head_size, BLUE, heavy=True)])],
             anchor=MSO_ANCHOR.MIDDLE)
        cx += col_w[i]
    yy = y + head_h
    for r in rows:
        cx = x
        for i, cell in enumerate(r):
            text(slide, cx + 0.10, yy, col_w[i] - 0.20, row_h,
                 [P([R(cell, size, GRAPHITE)])], anchor=MSO_ANCHOR.MIDDLE)
            cx += col_w[i]
        hline(slide, x, yy + row_h, w, color=LINE, width=0.5)
        yy += row_h
    return yy + head_h - y
