"""版面体检：按**真实排版高度**扫描每一页的越界与压盖。

要点：PPTX 的文本框不会裁剪溢出文字，shape.height 只是形状框。所以这里调用
textmetrics 按真实字距与行高算文字实际占的矩形，再判断：

- 越界：文字底部越过状态标签条上沿（Y_STATUSBAR）或页脚线；
- 越界：文字溢出画布（左右边距 0.40 in、底部 7.34 in）；
- 压盖：两个文本框的实际矩形相交超过 0.06 in × 0.06 in。

用法： ./.venv-ppt/bin/python ppt-gen/check_layout.py <pptx>
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pptx import Presentation

from textmetrics import text_extent

SAFE_BOTTOM = 6.52       # 状态标签条上沿
FOOTER_Y = 7.02
PAGE_H = 7.5
PAGE_W = 13.3333
SIDE_MIN = 0.40


def boxes(slide):
    out = []
    for sh in slide.shapes:
        if not sh.has_text_frame or not sh.text_frame.text.strip():
            continue
        x0, y0, x1, y1 = text_extent(sh)
        out.append((x0, y0, x1, y1,
                    sh.text_frame.text.replace("\n", " ")[:34]))
    return out


def overlap(a, b):
    ix = min(a[2], b[2]) - max(a[0], b[0])
    iy = min(a[3], b[3]) - max(a[1], b[1])
    return ix > 0.06 and iy > 0.06


def main(path: str) -> int:
    prs = Presentation(path)
    total = len(prs.slides._sldIdLst)
    bad_pages = 0
    for i, slide in enumerate(prs.slides, 1):
        bs = boxes(slide)
        if len(bs) <= 4:                     # 章节页 / 封面跳过
            continue
        issues = []
        for a in bs:
            if a[3] > PAGE_H - 0.16:
                issues.append(f"出画布: 「{a[4]}」底部 {a[3]:.2f}in")
            elif a[3] > SAFE_BOTTOM and a[1] < SAFE_BOTTOM:
                issues.append(f"压状态条: 「{a[4]}」底部 {a[3]:.2f}in")
            elif a[3] > FOOTER_Y + 0.02 and a[1] < FOOTER_Y:
                issues.append(f"压页脚线: 「{a[4]}」底部 {a[3]:.2f}in")
            if a[0] < SIDE_MIN - 0.02 or a[2] > PAGE_W - SIDE_MIN + 0.02:
                issues.append(f"出边距: 「{a[4]}」x {a[0]:.2f}–{a[2]:.2f}in")
        for x in range(len(bs)):
            for y in range(x + 1, len(bs)):
                if overlap(bs[x], bs[y]):
                    issues.append(f"压盖: 「{bs[x][4]}」× 「{bs[y][4]}」")
        if issues:
            bad_pages += 1
            print(f"\n--- P{i:02d} ---")
            for s in issues[:6]:
                print("   ", s)
    print(f"\n共 {bad_pages} 页有问题 / 共 {total} 页")
    return bad_pages


if __name__ == "__main__":
    p = sys.argv[1] if len(sys.argv) > 1 else "ppt/out/ATRI-答辩PPT-v5.pptx"
    sys.exit(1 if main(p) else 0)
