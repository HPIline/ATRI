"""把厂商 STEP/STL 渲染成多视角 PNG，用于**目视核验接口语义**。

T1 的经验：光看"Φ2.5 × 4 @ 9.9 方形"这样的数字，无法判断它是舵盘孔、
机身固定孔还是模具特征；出一张图，3 秒就能判定。

    .venv-cad/bin/python design/cad/render_vendor.py \
        design/cad/vendor/so-arm100/STS3215_03a.step
输出：design/cad/out/vendor_render/<零件名>_<视角>.png（out/ 已 gitignore）
"""
from __future__ import annotations

import sys
from pathlib import Path

import cadquery as cq

sys.path.insert(0, str(Path(__file__).parent))
import render3d as R  # noqa: E402

VIEWS = {
    "iso": ((1.0, -1.1, 0.75), (0.0, 0.0, 1.0)),
    "iso2": ((-1.0, 1.1, -0.75), (0.0, 0.0, 1.0)),
    "top": ((0.0, 0.0, 1.0), (0.0, 1.0, 0.0)),
    "bottom": ((0.0, 0.0, -1.0), (0.0, 1.0, 0.0)),
    "front": ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
    "side": ((0.0, -1.0, 0.0), (0.0, 0.0, 1.0)),
}


def load(path: Path):
    if path.suffix.lower() in (".stp", ".step"):
        return cq.importers.importStep(str(path))
    return cq.importers.importStl(str(path))


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    out_dir = Path(__file__).parent / "out" / "vendor_render"
    out_dir.mkdir(parents=True, exist_ok=True)

    for arg in argv[1:]:
        p = Path(arg)
        if not p.exists():
            print(f"✗ 找不到 {p}", file=sys.stderr)
            return 1
        wp = load(p)
        meshes = R.tessellate([(p.stem, wp)], tol=0.15)
        if not meshes:
            print(f"✗ {p.name} 三角化失败", file=sys.stderr)
            continue
        for view, (cam, up) in VIEWS.items():
            dst = out_dir / f"{p.stem}_{view}.png"
            R.render_png(meshes, cam, up, dst, width=900, height=760)
            print(f"✓ {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
