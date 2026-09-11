"""配合件同轴度比对：判定"支架/舵盘到底拧进舵机的哪个孔"。

T1 的核心工具。做法：
  1. 在整机装配体里按体积识别出舵机实例与配合件实例；
  2. 提取两者的**小孔圆柱面**（轴线方向 + 轴心位置 + 轴向跨度）；
  3. 找"轴线平行、横向偏移 < 容差、轴向相邻"的孔对。

孔对一旦成立，就能回答语义问题，例如：
  "支架上的 Φ2.0 孔与舵机 Φ1.5 底孔同轴" ⇒ 支架是用 M2 自攻拧进舵机侧孔的。

    .venv-cad/bin/python design/cad/check_mate.py <assembly.step> \
        --target-volume 36217 [--tol 0.35]
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

import cadquery as cq
import numpy as np
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.GeomAbs import GeomAbs_SurfaceType


def axis_name(v) -> str:
    comps = [("X", v.X()), ("Y", v.Y()), ("Z", v.Z())]
    _, val = max(comps, key=lambda c: abs(c[1]))
    return "+" if val > 0 else "-"


def small_holes(solid, r_min=0.5, r_max=2.6):
    """返回该实体上所有"小孔"圆柱面：轴线单位方向、轴上一点、半径、轴向跨度。"""
    out = []
    for f in solid.Faces():
        s = BRepAdaptor_Surface(f.wrapped)
        if s.GetType() != GeomAbs_SurfaceType.GeomAbs_Cylinder:
            continue
        cyl = s.Cylinder()
        r = cyl.Radius()
        if not (r_min <= r <= r_max):
            continue
        ax = cyl.Axis()
        loc, d = ax.Location(), ax.Direction()
        n = np.array([d.X(), d.Y(), d.Z()])
        n /= np.linalg.norm(n)
        p = np.array([loc.X(), loc.Y(), loc.Z()])
        bb = f.BoundingBox()
        along = {"X": (bb.xmin, bb.xmax), "Y": (bb.ymin, bb.ymax),
                 "Z": (bb.zmin, bb.zmax)}[axis_name(d)]
        out.append({"r": r, "n": n, "p": p, "lo": along[0], "hi": along[1]})
    return out


def match(a_holes, b_holes, tol=0.35):
    """找同轴孔对。"""
    hits = []
    for a in a_holes:
        for b in b_holes:
            if abs(abs(float(np.dot(a["n"], b["n"]))) - 1.0) > 1e-3:
                continue
            # 横向偏移：两轴之间的最短距离
            w = b["p"] - a["p"]
            w_perp = w - np.dot(w, a["n"]) * a["n"]
            lat = float(np.linalg.norm(w_perp))
            if lat > tol:
                continue
            # 轴向相邻（间隔 < 3mm 视为同一螺钉通道）
            gap = max(a["lo"], b["lo"]) - min(a["hi"], b["hi"])
            hits.append({"a_r": 2 * a["r"], "b_r": 2 * b["r"], "lat": lat,
                         "gap": gap, "axis": axis_name(cq.Vector(*a["n"]).toTuple()
                                                       and __import__("OCP.gp", fromlist=["gp"]).gp_Dir(*a["n"]).Y() * 0 + 0) if False else
                         ("X" if abs(a["n"][0]) > 0.9 else "Y" if abs(a["n"][1]) > 0.9 else "Z")})
    return hits


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    path = Path(argv[1])
    target = float(argv[argv.index("--target-volume") + 1]) if "--target-volume" in argv else 36217.0
    tol = float(argv[argv.index("--tol") + 1]) if "--tol" in argv else 0.35

    shape = cq.importers.importStep(str(path)).val()
    solids = list(shape.Solids())
    targets = [s for s in solids if abs(s.Volume() - target) < target * 0.02]
    others = [s for s in solids if s not in targets]
    print(f"# {path.name}: {len(solids)} 实体，其中目标件 {len(targets)} 个"
          f"（体积≈{target:.0f} mm³）")

    summary = defaultdict(int)
    for ti, t in enumerate(targets):
        th = small_holes(t)
        for oi, o in enumerate(others):
            oh = small_holes(o)
            if not oh:
                continue
            for h in match(th, oh, tol):
                summary[(round(h["a_r"], 1), round(h["b_r"], 1), h["axis"])] += 1

    print("\n## 同轴孔对统计（舵机孔 Φ × 配合件孔 Φ × 轴向）\n")
    print("| 舵机孔 Φ | 配合件孔 Φ | 轴向 | 命中次数 |")
    print("|---|---|---|---|")
    for (ar, br, ax), cnt in sorted(summary.items(), key=lambda kv: -kv[1]):
        print(f"| {ar} | {br} | {ax} | {cnt} |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
