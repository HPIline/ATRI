"""PPTX → PNG 离线渲染器（用于设计校验）。

为什么需要它：本机沙箱不允许调用 PowerPoint / QuickLook 导出，
而设计稿必须逐页目检。本渲染器直接读取生成的 .pptx，
按真实几何、真实颜色、真实字体（思源黑体 SC Regular/Heavy）绘制，
因此能忠实反映成品观感。

用法： ./.venv-ppt/bin/python ppt/render.py ppt/out/ATRI_样张.pptx ppt/out/preview
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE, MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.oxml.ns import qn

SCALE = 150                       # px per inch
REG = "/Users/hpi/Library/Fonts/SourceHanSansSC-Regular-2.otf"
HVY = "/Users/hpi/Library/Fonts/SourceHanSansSC-Heavy-2.otf"

_font_cache: dict = {}


def font(heavy: bool, size_pt: float):
    px = max(6, int(round(size_pt * SCALE / 72.0)))
    key = (heavy, px)
    if key not in _font_cache:
        _font_cache[key] = ImageFont.truetype(HVY if heavy else REG, px)
    return _font_cache[key]


def px(inches: float) -> int:
    return int(round(inches * SCALE))


def pt2px(points: float) -> int:
    return int(round(points * SCALE / 72.0))


# 思源黑体的默认行高约为 1.48 em（ascender 1160 + descender 320），
# PowerPoint 单倍行距即按此计算，渲染时必须跟随，否则会低估文本框高度。
LINE_FACTOR = 1.45


# 禁止出现在行首的标点
NO_LINE_START = set("，。、；：？！）》」』】…·%")
NO_LINE_END = set("（《「『【")


def split_lines(text: str, fnt, max_w: int) -> list[str]:
    """按字符贪心折行，带简单中文避头尾。"""
    if max_w <= 0:
        return [text]
    lines, cur = [], ""
    for ch in text:
        if ch == "\n":
            lines.append(cur)
            cur = ""
            continue
        trial = cur + ch
        if fnt.getlength(trial) <= max_w or not cur:
            cur = trial
            continue
        # 需要折行
        if ch in NO_LINE_START and cur:
            # 允许标点悬挂在行尾
            cur = trial
            continue
        if cur and cur[-1] in NO_LINE_END:
            lines.append(cur[:-1])
            cur = cur[-1] + ch
            continue
        lines.append(cur)
        cur = ch
    if cur:
        lines.append(cur)
    return lines or [""]


def draw_text_frame(dr: ImageDraw.ImageDraw, shape, box):
    tf = shape.text_frame
    x0, y0, w, h = box
    # 内边距（我们在生成时都置 0，这里读回以保持一致）
    ml = tf.margin_left.inches if tf.margin_left is not None else 0.1
    mr = tf.margin_right.inches if tf.margin_right is not None else 0.1
    mt = tf.margin_top.inches if tf.margin_top is not None else 0.05
    mb = tf.margin_bottom.inches if tf.margin_bottom is not None else 0.05
    ix, iy = x0 + px(ml), y0 + px(mt)
    iw, ih = w - px(ml + mr), h - px(mt + mb)

    # 先做一次排版，得到总高
    blocks = []
    for p in tf.paragraphs:
        runs = []
        for r in p.runs:
            rPr = r._r.find(qn("a:rPr"))
            spc = 0.0
            if rPr is not None and rPr.get("spc"):
                spc = int(rPr.get("spc")) / 100.0
            runs.append({
                "t": r.text,
                "size": r.font.size.pt if r.font.size else 14,
                "bold": bool(r.font.bold),
                "heavy": "Heavy" in (r.font.name or ""),
                "color": (str(r.font.color.rgb) if r.font.color and r.font.color.type
                          is not None else "1F2A37"),
                "spc": spc,
            })
        if not runs:
            blocks.append({"lines": [], "h": 0, "align": p.alignment,
                           "sb": 0, "sa": 0})
            continue
        base = max(r["size"] for r in runs)
        ls = p.line_spacing if p.line_spacing else 1.0
        if isinstance(ls, float):
            line_h = int(round(base * ls * LINE_FACTOR * SCALE / 72.0))
        else:
            line_h = px(ls.pt)
        # 逐 run 折行：把 runs 展开成带样式的字符流
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
                       "align": p.alignment, "sb": sb, "sa": sa,
                       "line_h": line_h})

    total = sum(b["h"] for b in blocks)
    anchor = tf.vertical_anchor
    cy = iy
    if anchor == MSO_ANCHOR.MIDDLE:
        cy = iy + (ih - total) / 2
    elif anchor == MSO_ANCHOR.BOTTOM:
        cy = iy + ih - total

    for b in blocks:
        cy += b["sb"]
        for line in b["lines"]:
            if not line:
                cy += b["line_h"]
                continue
            lw = sum(f.getlength(ch) + r["spc"] * SCALE / 72.0 for ch, r, f in line)
            al = b["align"]
            if al == PP_ALIGN.CENTER:
                lx = ix + (iw - lw) / 2
            elif al == PP_ALIGN.RIGHT:
                lx = ix + iw - lw
            else:
                lx = ix
            for ch, r, f in line:
                asc, desc = f.getmetrics()
                dr.text((lx, cy + (b["line_h"] - (asc + desc)) / 2),
                        ch, font=f, fill="#" + r["color"])
                lx += f.getlength(ch) + r["spc"] * SCALE / 72.0
            cy += b["line_h"]
        cy += b["sa"]


def shape_box(shape):
    return (px(shape.left.inches), px(shape.top.inches),
            px(shape.width.inches), px(shape.height.inches))


def solid_rgb(fill):
    try:
        if fill.type is not None and str(fill.type) == "MSO_FILL_TYPE.SOLID (1)":
            return "#" + str(fill.fore_color.rgb)
        from pptx.enum.dml import MSO_FILL
        if fill.type == MSO_FILL.SOLID:
            return "#" + str(fill.fore_color.rgb)
    except Exception:
        pass
    return None


def line_rgb(line):
    try:
        from pptx.enum.dml import MSO_FILL
        if line.fill.type == MSO_FILL.SOLID:
            return "#" + str(line.color.rgb)
    except Exception:
        pass
    return None


def render(pptx_path: str, outdir: str):
    prs = Presentation(pptx_path)
    W, H = px(prs.slide_width.inches), px(prs.slide_height.inches)
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    n = 0
    for idx, slide in enumerate(prs.slides, 1):
        bg = "#F7F9FB"
        try:
            if slide.background.fill.type is not None:
                from pptx.enum.dml import MSO_FILL
                if slide.background.fill.type == MSO_FILL.SOLID:
                    bg = "#" + str(slide.background.fill.fore_color.rgb)
        except Exception:
            pass
        img = Image.new("RGB", (W, H), bg)
        dr = ImageDraw.Draw(img)

        for shape in slide.shapes:
            st = shape.shape_type
            if st == MSO_SHAPE_TYPE.LINE or shape.shape_type == MSO_SHAPE_TYPE.LINE:
                pass
            if shape.shape_type == MSO_SHAPE_TYPE.LINE:
                lc = line_rgb(shape.line) or "#1264A3"
                lw = max(1, int(round((shape.line.width.pt if shape.line.width else 0.75)
                                      * SCALE / 72.0)))
                x1, y1 = px(shape.left.inches), px(shape.top.inches)
                x2, y2 = x1 + px(shape.width.inches), y1 + px(shape.height.inches)
                dr.line([x1, y1, x2, y2], fill=lc, width=lw)
                continue

            if shape.shape_type == MSO_SHAPE_TYPE.AUTO_SHAPE:
                x, y, w, h = shape_box(shape)
                f = solid_rgb(shape.fill)
                lc = line_rgb(shape.line)
                lw = max(1, int(round((shape.line.width.pt if shape.line.width else 0.75)
                                      * SCALE / 72.0)))
                auto = shape.auto_shape_type
                if auto == MSO_SHAPE.OVAL:
                    if f:
                        dr.ellipse([x, y, x + w, y + h], fill=f)
                    if lc:
                        dr.ellipse([x, y, x + w, y + h], outline=lc, width=lw)
                else:
                    if f:
                        dr.rectangle([x, y, x + w, y + h], fill=f)
                    if lc:
                        dr.rectangle([x, y, x + w, y + h], outline=lc, width=lw)

            if shape.has_text_frame and shape.text_frame.text.strip():
                draw_text_frame(dr, shape, shape_box(shape))

        p = out / f"p{idx:02d}.png"
        img.save(p)
        n += 1
        print("rendered", p)
    print(f"total {n} slides")


if __name__ == "__main__":
    render(sys.argv[1], sys.argv[2])
