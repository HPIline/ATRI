"""舵机"钟点位"全局求解：用 180° 翻转最小化**舵机之间**的干涉。

原理：
    舵机两个轴向端面的 4×Φ2.5 是**方形 9.9×9.9（4 重对称）**，
    所以舵机可以绕自身轴转 180° 而不影响拧螺钉；但机身 45.2 的长边会调头
    （轴心距一端 10.2、另一端 35.0），于是能把"伸进邻居空间"的那一段转开。
    在 `orient(shape, shaft, parent)` 里等价于把 `parent` 取反（局部 +X = shaft×parent）。

    注意：翻转**只对舵机自身**做，不动笼/叉——笼的座口与安装孔阵都是 4 重对称的，
    翻转后仍对得上（由 `assembly.build_assembly` 里 `JOINT_SCHEME[*]["clock"]` 生效）。

做法：全放置 → 逐个试翻转 → 只保留能降低总干涉的翻转 → 迭代到不动点。
输出：建议写入 `JOINT_SCHEME` 的 `clock` 值 + 翻转前后的总干涉。

    .venv-cad/bin/python design/cad/fit_clocking.py [--passes 4]
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import cadquery as cq

import assembly as A
from fitcheck import bbox_of, boxes_overlap, common_volume
from kit import orient

OPP = A.OPP


def par_for(jname: str, sc: Dict[str, str], flip: bool) -> str:
    """该关节舵机的"母端参考方向"（含 yaw 退化替换与 180° 翻转）。"""
    par = sc["parent"]
    if par.strip("+-") == sc["shaft"].strip("+-"):
        par = next(d for d in ("+z", "-z", "+y", "-y", "+x", "-x")
                   if d.strip("+-") != sc["shaft"].strip("+-"))
    return OPP[par] if flip else par


def place_servo(kin: A.Kin, jname: str, flip: bool) -> cq.Workplane:
    sc = A.JOINT_SCHEME[jname]
    body = orient(A.servo_placeholder(), sc["shaft"], par_for(jname, sc, flip))
    return A._place(body, kin.joint_world(jname))


def pair_sum(solids: Dict[str, cq.Workplane], names: Sequence[str],
             pairs: Sequence[Tuple[str, str]], only: str | None = None) -> float:
    total = 0.0
    for a, b in pairs:
        if only is not None and only not in (a, b):
            continue
        total += common_volume(solids[a], solids[b])
    return total


def main(argv: Sequence[str]) -> int:
    passes = 4
    if "--passes" in argv:
        passes = int(argv[list(argv).index("--passes") + 1])

    kin = A.Kin(A.DESIGN / "atri.urdf")
    names = list(A.JOINT_SCHEME)
    flips: Dict[str, bool] = {j: False for j in names}

    solids = {j: place_servo(kin, j, False) for j in names}
    boxes = {j: bbox_of(s) for j, s in solids.items()}
    pairs = [(a, b) for i, a in enumerate(names) for b in names[i + 1:]
             if boxes_overlap(boxes[a], boxes[b])]

    start = pair_sum(solids, names, pairs)
    print(f"初始（全不翻转）：舵机间干涉合计 **{start:.0f} mm³**，"
          f"包围盒相交 {len(pairs)} 对\n")

    cur = start
    for p in range(1, passes + 1):
        changed = 0
        for j in names:
            base = pair_sum(solids, names, pairs, only=j)
            trial = place_servo(kin, j, not flips[j])
            tb = bbox_of(trial)
            saved_solid, saved_box = solids[j], boxes[j]
            solids[j], boxes[j] = trial, tb
            score = pair_sum(solids, names, pairs, only=j)
            if score < base - 1e-6:
                flips[j] = not flips[j]
                cur += score - base
                changed += 1
            else:
                solids[j], boxes[j] = saved_solid, saved_box
        print(f"第 {p} 轮：采纳翻转 {changed} 处，当前合计 {cur:.0f} mm³")
        if not changed:
            break

    pairs2 = [(a, b) for i, a in enumerate(names) for b in names[i + 1:]
              if boxes_overlap(boxes[a], boxes[b])]
    final = pair_sum(solids, names, pairs2)

    print(f"\n结果：**{start:.0f} → {final:.0f} mm³**"
          f"（降 {100 * (start - final) / max(start, 1e-9):.0f}%），"
          f"包围盒相交 {len(pairs)} → {len(pairs2)} 对")
    print(f"\n建议写入 `assembly.JOINT_SCHEME`（共 {sum(flips.values())} 个关节翻转）：\n")
    for j in names:
        if flips[j]:
            print(f'    "{j}": {{..., "clock": "flip"}},')
    if not any(flips.values()):
        print("    （无需翻转）")
    print("\n提示：翻转只作用于舵机自身，笼/叉不用动"
          "（安装孔阵 4 重对称，座口仍对得上）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
