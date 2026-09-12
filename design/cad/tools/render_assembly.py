"""整机装配出图（PNG）：目视检查**方向 / 穿模 / 未衔接**。

配合 `audit_assembly.py` 使用：体检脚本给数字，本脚本给"人眼一眼能看出问题"的图。

    .venv-cad/bin/python design/cad/tools/render_assembly.py            # 默认 4 视角
    .venv-cad/bin/python design/cad/tools/render_assembly.py --views iso,side
输出：design/cad/out/preview/assembly_<view>.png（out/ 已 gitignore）
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Sequence

CAD = Path(__file__).resolve().parent.parent  # design/cad/
HERE = CAD  # 产物仍写到 cad/out，不跟脚本下沉
sys.path.insert(0, str(CAD))
sys.path.insert(0, str(CAD / "tools"))

import assembly as A
import render3d as R

OUT = HERE / "out" / "preview"

VIEWS = {
    "iso": ((1.0, -1.1, 0.55), (0.0, 0.0, 1.0)),
    "front": ((0.0, -1.0, 0.0), (0.0, 0.0, 1.0)),
    "side": ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
    "head": ((0.35, -0.9, 0.9), (0.0, 0.0, 1.0)),
    "leg": ((1.0, -0.6, -0.35), (0.0, 0.0, 1.0)),
}


def main(argv: Sequence[str]) -> int:
    want = ["iso", "front", "side"]
    if "--views" in argv:
        want = argv[list(argv).index("--views") + 1].split(",")
    tol = float(argv[list(argv).index("--tol") + 1]) if "--tol" in argv else 0.5

    kin = A.Kin(A.DESIGN / "atri.urdf")
    placements = json.loads((A.DESIGN / "placements.json").read_text(encoding="utf-8"))
    items, log = A.build_assembly(kin, placements)
    bad = [l for l in log if not l.get("ok")]
    print(f"装配件 {len(items)} 个（失败 {len(bad)}）")

    OUT.mkdir(parents=True, exist_ok=True)
    meshes = R.tessellate(items, tol=tol)
    print(f"三角化完成：{len(meshes)} 个件")
    for v in want:
        cam, up = VIEWS[v]
        dst = OUT / f"assembly_{v}.png"
        R.render_png(meshes, cam, up, dst, width=1100, height=900)
        print(f"✓ {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
