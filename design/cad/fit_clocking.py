"""舵机绕自身轴的"钟点位"求解：用 180° 翻转消除相邻舵机机体互咬。

背景：
    舵机两个轴向端面的 4×Φ2.5 安装孔是**方形 9.9×9.9**（4 重对称），
    所以舵机可以在自己的轴上转 0/90/180/270 而不影响拧螺钉。
    把机身 45.2 的长边（35.0 的实体在 −X 侧）转离相邻舵机，就能消掉互咬。
    在 `orient(shape, shaft, parent)` 里，等价于把 `parent` 取反（局部 +X = shaft×parent）。

本脚本不动零件、只**试四种钟点**并报告每种的总干涉体积，供人工选定后写回
`assembly.JOINT_SCHEME`（字段 `clock`）。

    .venv-cad/bin/python design/cad/fit_clocking.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import cadquery as cq

import assembly as A
from audit_assembly import boxes_overlap, common_volume
from kit import orient

OPP = A.OPP
PERP = {"+x": ("+y", "+z"), "-x": ("+y", "+z"),
        "+y": ("+x", "+z"), "-y": ("+x", "+z"),
        "+z": ("+x", "+y"), "-z": ("+x", "+y")}


def servo_solid(kin, jname: str, sc: Dict[str, str], par: str) -> cq.Workplane:
    body = orient(A.servo_placeholder(), sc["shaft"], par)
    return A._place(body, kin.joint_world(jname))


def main(argv: Sequence[str]) -> int:
    kin = A.Kin(A.DESIGN / "atri.urdf")
    order = [j for j in A.JOINT_SCHEME]          # 字典序≈创建序，够用
    placed: List[Tuple[str, cq.Workplane, Tuple[float, float, float]]] = []
    chosen: Dict[str, str] = {}

    print(f"{'关节':22s} {'方案 parent':12s} {'候选':28s} 干涉 mm³")
    print("-" * 78)
    for jname in order:
        sc = A.JOINT_SCHEME[jname]
        par0 = sc["parent"]
        # yaw 退化：轴与母端同轴时，用第一个垂直方向（与 assembly 同规则）
        if par0.strip("+-") == sc["shaft"].strip("+-"):
            par0 = next(d for d in ("+z", "-z", "+y", "-y", "+x", "-x")
                        if d.strip("+-") != sc["shaft"].strip("+-"))
        cands = [par0, OPP[par0]]
        results = []
        for par in cands:
            try:
                body = servo_solid(kin, jname, sc, par)
            except Exception as exc:                       # noqa: BLE001
                results.append((par, float("inf"), f"{type(exc).__name__}"))
                continue
            bb = body.val().BoundingBox()
            vol = 0.0
            for _, other, obb in placed:
                if boxes_overlap(bb, obb):
                    vol += common_volume(body, other)
            results.append((par, vol, ""))
        best = min(results, key=lambda r: r[1])
        chosen[jname] = best[0]
        solid = servo_solid(kin, jname, sc, best[0])
        placed.append((jname, solid, solid.val().BoundingBox()))
        detail = "  ".join(f"{p}:{v:.0f}" for p, v, _ in results)
        mark = "★" if best[0] != par0 else " "
        print(f"{jname:22s} {par0:12s} {detail:28s} {mark}")

    flips = [j for j in chosen
             if chosen[j] != A.JOINT_SCHEME[j]["parent"]]
    print(f"\n建议翻转（parent 取反）的关节 {len(flips)} 个：")
    for j in flips:
        print(f"  {j:24s} parent {A.JOINT_SCHEME[j]['parent']:3s} → {chosen[j]}")
    print("\n写回方式：把这些关节的 `clock` 置为 \"flip\"（见 assembly.JOINT_SCHEME）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
