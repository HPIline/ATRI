"""文本框实际排版范围测量（与 render.py 同一套字距与行高口径）。

为什么单独抽出这个模块：PPTX 里文本框的 height 只是形状框，PowerPoint 不会裁剪
溢出文字——文字超出去照样画。所以"有没有越界/压盖"必须**按真实排版高度**算，
不能拿 shape.height 当依据。render.py 用它来画，check_layout.py 用它来体检，
两边共用同一份实现，避免"渲染不溢出、检查说溢出"这种自相矛盾的结论。
"""
from __future__ import annotations

from pathlib import Path

from PIL import ImageFont
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.oxml.ns import qn

SCALE = 150
_FONT_DIR = Path.home() / "Library" / "Fonts"
REG = str(_FONT_DIR / "SourceHanSansSC-Regular-2.otf")
HVY = str(_FONT_DIR / "SourceHanSansSC-Heavy-2.otf")

# 思源黑体默认行高约 1.45 em，PowerPoint 单倍行距即按此计算
LINE_FACTOR = 1.45

_font_cache: dict = {}

NO_LINE_START = set("，。、；：？！）》」』】…·%")
NO_LINE_END = set("（《「『【")


def font(heavy: bool, size_pt: float) -> ImageFont.FreeTypeFont:
    px = max(6, int(round(size_pt * SCALE / 72.0)))
    key = (heavy, px)
    if key not in _font_cache:
        _font_cache[key] = ImageFont.truetype(HVY if heavy else REG, px)
    return _font_cache[key]


def px(inches: float) -> int:
    return int(round(inches * SCALE))


def pt2px(points: float) -> int:
    return int(round(points * SCALE / 72.0))


def layout(shape) -> dict:
    """返回 {'w','h','blocks'}；w/h 是**实际排版尺寸**（像素）。"""
    tf = shape.text_frame
    ml = tf.margin_left.inches if tf.margin_left is not None else 0.1
    mr = tf.margin_right.inches if tf.margin_right is not None else 0.1
    mt = tf.margin_top.inches if tf.margin_top is not None else 0.05
    mb = tf.margin_bottom.inches if tf.margin_bottom is not None else 0.05
    iw = px(shape.width.inches) - px(ml + mr)

    blocks = []
    for p in tf.paragraphs:
        runs = []
        for r in p.runs:
            rPr = r._r.find(qn("a:rPr"))
            spc = int(rPr.get("spc")) / 100.0 if (rPr is not None and rPr.get("spc")) else 0.0
            runs.append({
                "t": r.text,
                "size": r.font.size.pt if r.font.size else 14,
                "heavy": "Heavy" in (r.font.name or ""),
                "spc": spc,
            })
        if not runs:
            blocks.append({"lines": [], "h": 0, "sb": 0, "sa": 0, "line_h": 0})
            continue
        base = max(r["size"] for r in runs)
        ls = p.line_spacing if p.line_spacing else 1.0
        if isinstance(ls, float):
            line_h = int(round(base * ls * LINE_FACTOR * SCALE / 72.0))
        else:
            line_h = px(ls.pt)

        stream = []
        for r in runs:
            f = font(r["heavy"], r["size"])
            for ch in r["t"]:
                stream.append((ch, r, f))
        lines, cur, cur_w = [], [], 0.0
        for ch, r, f in stream:
            if ch == "\n":
                lines.append(cur)
                cur, cur_w = [], 0.0
                continue
            cw = f.getlength(ch) + r["spc"] * SCALE / 72.0
            if cur_w + cw > iw and cur:
                if ch in NO_LINE_START:
                    cur.append((ch, r, f))
                    cur_w += cw
                    continue
                if cur[-1][0] in NO_LINE_END:
                    last = cur.pop()
                    lines.append(cur)
                    cur, cur_w = [last], last[2].getlength(last[0])
                else:
                    lines.append(cur)
                    cur, cur_w = [], 0.0
            cur.append((ch, r, f))
            cur_w += cw
        lines.append(cur)
        sb = pt2px(p.space_before.pt) if p.space_before else 0
        sa = pt2px(p.space_after.pt) if p.space_after else 0
        blocks.append({"lines": lines, "h": line_h * len(lines) + sb + sa,
                       "sb": sb, "sa": sa, "line_h": line_h,
                       "align": p.alignment})

    total = sum(b["h"] for b in blocks)
    return {"w": iw, "h": total, "blocks": blocks}


def text_extent(shape) -> tuple[float, float, float, float]:
    """文字实际占据的矩形（英寸）：左、上、右、下。"""
    lay = layout(shape)
    tf = shape.text_frame
    mt = tf.margin_top.inches if tf.margin_top is not None else 0.05
    anchor = tf.vertical_anchor
    box_h = px(shape.height.inches)
    ih = box_h - px(mt + (tf.margin_bottom.inches if tf.margin_bottom is not None else 0.05))
    top = px(shape.top.inches) + px(mt)
    if anchor == MSO_ANCHOR.MIDDLE:
        top += max(0, (ih - lay["h"]) // 2)
    elif anchor == MSO_ANCHOR.BOTTOM:
        top += max(0, ih - lay["h"])
    x0 = shape.left.inches + (tf.margin_left.inches if tf.margin_left is not None else 0.1)
    # 实际行宽：取最长一行的宽度
    max_w = 0
    for b in lay["blocks"]:
        for line in b["lines"]:
            if not line:
                continue
            max_w = max(max_w, sum(f.getlength(ch) + r["spc"] * SCALE / 72.0
                                   for ch, r, f in line))
    return (x0, top / SCALE, x0 + max_w / SCALE, (top + lay["h"]) / SCALE)
