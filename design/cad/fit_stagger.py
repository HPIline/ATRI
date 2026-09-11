"""髋/肩簇「错轴」布局实验：只动舵机占位体，沿自身输出轴平移。

轴距 19.6 mm 只给「输出轴 + 薄支架」住，不给「机身 35 mm」住。

        轴 A (yaw)                    轴 B (roll)
           │                             │
           │  ← 19.6 mm →                │
     ┌─────┴──────┐                 ┌────┴──────┐
     │  机体 A     │                 │  机体 B     │
     │  沿轴 A 向外│                 │  沿轴 B 向外│
     └────────────┘                 └────────────┘
           ▲ 输出                       ▲ 输出

约束（本脚本不许破）：
    - 关节轴位置不动（`kin.joint_world` 原点不变）；
    - 只动舵机占位体，不动笼/叉（本步是布局可行性）；
    - 偏置上限 ±40 mm。

成功线：下列关节对的舵机-舵机干涉 < 500 mm³ 或重合率 < 5%。

    .venv-cad/bin/python design/cad/fit_stagger.py
    .venv-cad/bin/python design/cad/fit_stagger.py --step 5 --limit 40
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
from fitcheck import bbox_of, boxes_overlap, common_volume, verdict
from kit import DIRS, orient

CLUSTER_PAIRS: List[Tuple[str, str]] = [
    ("left_hip_yaw", "left_hip_roll"),
    ("left_hip_roll", "left_hip_pitch"),
    ("right_hip_yaw", "right_hip_roll"),
    ("right_hip_roll", "right_hip_pitch"),
    ("left_shoulder_pitch", "left_shoulder_roll"),
    ("right_shoulder_pitch", "right_shoulder_roll"),
]

CLUSTER_JOINTS = sorted({j for pair in CLUSTER_PAIRS for j in pair})


def par_for(sc: Dict[str, str]) -> str:
    par = sc["parent"]
    if par.strip("+-") == sc["shaft"].strip("+-"):
        par = next(d for d in ("+z", "-z", "+y", "-y", "+x", "-x")
                   if d.strip("+-") != sc["shaft"].strip("+-"))
    if sc.get("clock") == "flip":
        par = A.OPP[par]
    return par


def place_servo(kin: A.Kin, jname: str, stagger_mm: float) -> cq.Workplane:
    """关节原点不动；机体沿自身输出轴平移 stagger_mm（正 = 沿 shaft 方向）。"""
    sc = A.JOINT_SCHEME[jname]
    body = orient(A.servo_placeholder(), sc["shaft"], par_for(sc))
    dx, dy, dz = DIRS[sc["shaft"]]
    shifted = A.mat_mul(kin.joint_world(jname),
                        A.mat_trans(dx * stagger_mm, dy * stagger_mm, dz * stagger_mm))
    return A._place(body, shifted)


def envelope_of(solids: Dict[str, cq.Workplane]):
    bb = None
    for s in solids.values():
        b = bbox_of(s)
        bb = b if bb is None else bb.add(b)
    return bb


def pair_vol(solids: Dict[str, cq.Workplane], a: str, b: str) -> float:
    if not boxes_overlap(bbox_of(solids[a]), bbox_of(solids[b])):
        return 0.0
    return common_volume(solids[a], solids[b])


def score_pairs(solids: Dict[str, cq.Workplane]) -> Dict[Tuple[str, str], float]:
    return {pair: pair_vol(solids, *pair) for pair in CLUSTER_PAIRS}


def total_of(vols: Dict[Tuple[str, str], float]) -> float:
    return sum(vols.values())


def main(argv: Sequence[str]) -> int:
    step = 5.0
    limit = 40.0
    if "--step" in argv:
        step = float(argv[list(argv).index("--step") + 1])
    if "--limit" in argv:
        limit = float(argv[list(argv).index("--limit") + 1])

    kin = A.Kin(A.DESIGN / "atri.urdf")
    candidates = []
    v = 0.0
    while v <= limit + 1e-9:
        candidates.append(round(v, 3))
        if v > 0:
            candidates.append(round(-v, 3))
        v += step
    # 0 先、再由小到大的正负，贪心更稳
    candidates = sorted(set(candidates), key=lambda x: (abs(x), -x))

    stagger: Dict[str, float] = {j: 0.0 for j in CLUSTER_JOINTS}
    solids = {j: place_servo(kin, j, 0.0) for j in CLUSTER_JOINTS}
    vols = score_pairs(solids)
    start = total_of(vols)
    start_bb = envelope_of(solids)

    print("## 髋/肩簇错轴实验（只动舵机占位，URDF 轴距不动）\n")
    print(f"扫描 stagger ∈ [{-limit:.0f}, {limit:.0f}] mm，步长 {step:.0f} mm，"
          f"候选 {len(candidates)} 档 × {len(CLUSTER_JOINTS)} 关节\n")
    print(f"初始舵机-舵机干涉合计 **{start:.0f} mm³**\n")
    print("| 关节对 | 当前 mm³ |")
    print("|---|---|")
    for a, b in CLUSTER_PAIRS:
        print(f"| `{a}` ↔ `{b}` | {vols[(a, b)]:.0f} |")

    # 坐标下降：每次只动一只，取能把「它参与的对」总和降最多的档
    print("\n## 贪心搜索\n")
    for p in range(1, 8):
        changed = 0
        for j in CLUSTER_JOINTS:
            involved = [pair for pair in CLUSTER_PAIRS if j in pair]
            base = sum(vols[pair] for pair in involved)
            best_s, best_score, best_solid = stagger[j], base, solids[j]
            saved = solids[j]
            for s in candidates:
                if abs(s - stagger[j]) < 1e-9:
                    continue
                trial = place_servo(kin, j, s)
                solids[j] = trial
                score = sum(pair_vol(solids, *pair) for pair in involved)
                if score < best_score - 1.0:
                    best_s, best_score, best_solid = s, score, trial
            solids[j] = best_solid
            if abs(best_s - stagger[j]) > 1e-9:
                stagger[j] = best_s
                changed += 1
            else:
                solids[j] = saved
            vols = score_pairs(solids)
        cur = total_of(vols)
        print(f"第 {p} 轮：改 {changed} 处，合计 {cur:.0f} mm³")
        if not changed:
            break

    # 再做一次联合微调：每对两只同时取当前最优
    vols = score_pairs(solids)
    final = total_of(vols)
    final_bb = envelope_of(solids)

    print(f"\n## 结果：{start:.0f} → {final:.0f} mm³"
          f"（降 {100 * (start - final) / max(start, 1e-9):.0f}%）\n")
    zero = {j: place_servo(kin, j, 0.0) for j in CLUSTER_JOINTS}
    zero_vols = score_pairs(zero)
    servo_vol = 40018.0
    n_clear = 0
    print("| 关节对 | 基线 mm³ | stagger A | stagger B | 结果 mm³ | 判定 |")
    print("|---|---|---|---|---|---|")
    for a, b in CLUSTER_PAIRS:
        v = vols[(a, b)]
        frac = v / servo_vol
        ok = v < 500.0 or frac < 0.05
        n_clear += int(ok)
        mark = "✅" if ok else verdict(v, frac)
        print(f"| `{a}` ↔ `{b}` | {zero_vols[(a, b)]:.0f} | "
              f"{stagger[a]:+.0f} | {stagger[b]:+.0f} | {v:.0f} | {mark} |")

    dx = (final_bb.xlen - start_bb.xlen) if (final_bb and start_bb) else 0.0
    dy = (final_bb.ylen - start_bb.ylen) if (final_bb and start_bb) else 0.0
    dz = (final_bb.zlen - start_bb.zlen) if (final_bb and start_bb) else 0.0
    print(f"\n簇内舵机包络增量（仅这 {len(CLUSTER_JOINTS)} 只）："
          f"深 {dx:+.0f} / 宽 {dy:+.0f} / 高 {dz:+.0f} mm")
    if start_bb and final_bb:
        print(f"  基线包络 {start_bb.xlen:.0f}×{start_bb.ylen:.0f}×{start_bb.zlen:.0f} → "
              f"{final_bb.xlen:.0f}×{final_bb.ylen:.0f}×{final_bb.zlen:.0f}")

    print(f"\n成功线：{n_clear}/{len(CLUSTER_PAIRS)} 对 <500 mm³ 或重合率 <5%")
    print("\n建议写入 `assembly.JOINT_SCHEME[*][\"stagger\"]`（单位 mm，沿自身 shaft）：\n")
    for j in CLUSTER_JOINTS:
        if abs(stagger[j]) > 0.5:
            print(f'    "{j}": {{..., "stagger": {stagger[j]:.1f}}},')
        else:
            print(f'    "{j}": {{..., "stagger": 0.0}},  # 不动')

    out = {
        "pairs": [
            {"a": a, "b": b,
             "baseline_mm3": zero_vols[(a, b)],
             "stagger_a": stagger[a], "stagger_b": stagger[b],
             "result_mm3": vols[(a, b)]}
            for a, b in CLUSTER_PAIRS
        ],
        "stagger": stagger,
        "start_mm3": start,
        "final_mm3": final,
        "n_clear": n_clear,
        "envelope_delta_mm": [dx, dy, dz],
    }
    path = HERE / "out" / "stagger_report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    print(f"\n已写出 {path.relative_to(A.REPO)}")
    return 0 if n_clear == len(CLUSTER_PAIRS) else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
