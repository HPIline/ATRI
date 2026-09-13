"""把 ATRI-v2 CAD 光追渲染图加工成可直接摆放的 PPT 素材。

上游素材（`.upstream/renders/`，来自仓库 `design/v2/out/`）为 RGBA 4K/1600px 大图，
底色是一层近乎平坦的深灰蓝（约 #323A42，带极轻微渐变）。本脚本：
1. 把 RGBA 压到页面图版底色（design.DARK）上，避免 PPT 里出现透明边；
2. 按版面需要缩放（图版页最长边 2600 px 足够 13.3 in 宽下 ~195 dpi）；
3. 统一输出 JPEG（q=92）——渲染图偏照片质感，JPEG 能把交付体积压到一个量级。

用法： ./.venv-ppt/bin/python ppt-gen/prepare_v2_assets.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageChops

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SRC = ROOT / ".upstream" / "renders"
DST = HERE / "assets" / "v2"

# 目标名 ← 源文件名（按优先级取第一个存在的），最长边，说明
PLAN = [
    ("hero_front.png", ["r4k_front.png", "product_front.png"], 2600, "封面整机正视图"),
    ("product_iso.png", ["product_iso.png"], 1800, "整机等轴测"),
    ("product_front.png", ["product_front.png"], 1800, "整机正视图"),
    ("product_rear.png", ["product_rear.png"], 1800, "整机后视图"),
    ("exploded.png", ["r4k_exploded.png", "svc_exploded.png"], 2600, "爆炸视图"),
    ("service_exploded.png", ["svc_exploded.png"], 1800, "维护拆解示意"),
    ("detail_pelvis.png", ["detail_pelvis.png"], 1400, "髋腰双侧支承细节"),
    ("detail_gripper.png", ["detail_gripper.png"], 1400, "两指夹爪细节"),
    ("detail_waist.png", ["r4k_waist.png"], 2600, "腰-手-传感器细节"),
]

BG = (50, 58, 66)          # = design.DARK（#323A42），取自渲染图底色


def autocrop(im: Image.Image, tol: int = 16, pad_ratio: float = 0.03) -> Image.Image:
    """按背景色差裁掉渲染图四周的空底。

    渲染图是 16:9 大画布、机体只占中间一小块；不裁的话，贴进 4:3 或竖版画框后
    只会剩下一小截机体加一大片空底。判据是「与底色差值 > tol 的像素」的包围盒。
    """
    rgb = im.convert("RGB")
    bg = Image.new("RGB", rgb.size, BG)
    mask = ImageChops.difference(rgb, bg).convert("L").point(
        lambda v: 255 if v > tol else 0)
    box = mask.getbbox()
    if box is None:
        return im
    pad_x = int((box[2] - box[0]) * pad_ratio)
    pad_y = int((box[3] - box[1]) * pad_ratio)
    box = (max(0, box[0] - pad_x), max(0, box[1] - pad_y),
           min(rgb.width, box[2] + pad_x), min(rgb.height, box[3] + pad_y))
    return im.crop(box)


def main() -> int:
    DST.mkdir(parents=True, exist_ok=True)
    missing = []
    for name, candidates, max_side, why in PLAN:
        src = next((SRC / c for c in candidates if (SRC / c).exists()), None)
        if src is None:
            missing.append((name, candidates))
            continue
        with Image.open(src) as im:
            im = im.convert("RGBA")
            bg = Image.new("RGB", im.size, BG)
            bg.paste(im, mask=im.split()[-1])
            out = autocrop(bg)
            if max(out.size) > max_side:
                scale = max_side / max(out.size)
                out = out.resize((round(out.width * scale), round(out.height * scale)),
                                 Image.LANCZOS)
            target = DST / (Path(name).stem + ".jpg")
            out.save(target, "JPEG", quality=92, optimize=True)
            print(f"{target.name:26s} {out.width}x{out.height}  {why}")
    if missing:
        print("缺失（版面会自动退化为色块）：")
        for name, cands in missing:
            print(f"  {name} ← {' / '.join(cands)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
