"""版面体检：扫描 PPTX，找出文本框互相压盖、或越过状态条/页脚安全线的页。"""
from __future__ import annotations
import sys
from pptx import Presentation

SAFE_BOTTOM = 6.52      # 状态标签条上沿
STATUS_Y = 6.58
FOOTER_Y = 7.02

def boxes(slide):
    out = []
    for sh in slide.shapes:
        if sh.has_text_frame and sh.text_frame.text.strip():
            out.append((sh.left.inches, sh.top.inches,
                        sh.left.inches + sh.width.inches,
                        sh.top.inches + sh.height.inches,
                        sh.text_frame.text.replace("\n", " ")[:34]))
    return out

def overlap(a, b):
    ix = min(a[2], b[2]) - max(a[0], b[0])
    iy = min(a[3], b[3]) - max(a[1], b[1])
    return ix > 0.05 and iy > 0.05

def main(path):
    prs = Presentation(path)
    problems = 0
    for i, slide in enumerate(prs.slides, 1):
        bs = boxes(slide)
        # 空白章节页跳过
        if len(bs) <= 4:
            continue
        issues = []
        for a in bs:
            if a[3] > SAFE_BOTTOM + 0.4 and a[1] < STATUS_Y:
                issues.append(f"越界: 「{a[4]}」底部 {a[3]:.2f}in > {SAFE_BOTTOM}in")
            elif a[3] > FOOTER_Y + 0.3:
                issues.append(f"越界: 「{a[4]}」底部 {a[3]:.2f}in")
        for x in range(len(bs)):
            for y in range(x + 1, len(bs)):
                if overlap(bs[x], bs[y]):
                    issues.append(f"压盖: 「{bs[x][4]}」× 「{bs[y][4]}」")
        if issues:
            problems += 1
            print(f"\n--- P{i:02d} ---")
            for s in issues[:4]:
                print("   ", s)
    print(f"\n共 {problems} 页有问题")

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1
         else "ppt/out/ATRI-答辩PPT-定稿.pptx")
