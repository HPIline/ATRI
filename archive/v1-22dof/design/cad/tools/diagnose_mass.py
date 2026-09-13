#!/usr/bin/env python3
"""质量分解诊断：把重件按"特征"拆开量体积，找出材料堆在哪。

用途：减重迭代时**不靠猜**。比如关节笼 27.9 g，到底是侧板、底板、插接芯棒
还是螺钉柱吃掉的？本脚本用同一套建模代码逐特征单独成体、量体积、折算质量。

用法：
    .venv-cad/bin/python design/cad/tools/diagnose_mass.py
    .venv-cad/bin/python design/cad/tools/diagnose_mass.py --part joint_cage
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

CAD = Path(__file__).resolve().parent.parent  # design/cad/
HERE = CAD  # 产物仍写到 cad/out，不跟脚本下沉
sys.path.insert(0, str(CAD))
sys.path.insert(0, str(CAD / "tools"))

import cadquery as cq

import skeleton as sk
from kit import MATERIALS

PETG = MATERIALS["PETG"]["density_g_cm3"]


def mass(vol_mm3: float, material: str = "PETG") -> float:
    return vol_mm3 * MATERIALS[material]["density_g_cm3"] / 1000.0


def measure(name: str, shape: cq.Workplane) -> Tuple[float, float]:
    v = shape.val().Volume()
    return v, mass(v)


def breakdown_joint_cage() -> List[Dict[str, Any]]:
    """按特征拆关节笼（标准姿态，未旋转）。"""
    from kit import FDM, IF, bolt_circle, box, cyl, drill, fastener, bearing
    # ⚠️ 2026-09-12 修：原 import 含 `AXIS_DZ`，该常量在第 6–10 轮骨架重构里已删除，
    #    导致本工具 ImportError（工具随重构一起坏了，没人发现）。该名字在本函数里
    #    本来就没被用到，直接去掉。
    from skeleton import (GAP, PLATE_T, PLATE_Y, SERVO_NAME, SPAN_X,
                          SPIGOT_BORE, SPIGOT_D, SPIGOT_H, X_HALF, Y_HALF,
                          Z_BOT, Z_TOP, S)
    rows = []
    z_floor_bot = Z_BOT - PLATE_T
    z_cap_bot = Z_TOP + 2.0
    z_cap_top = z_cap_bot + PLATE_T + 2.0

    # 单块侧板（含减重窗与孔）
    plate_h = z_cap_top - z_floor_bot
    p = box(SPAN_X, PLATE_T, plate_h, at=(0, PLATE_Y, z_floor_bot))
    for dx in (-13.0, 0.0, 13.0):
        p = p.cut(box(11.0, PLATE_T * 4, 30.0, at=(dx, PLATE_Y, z_floor_bot + 8.0)))
    p = p.cut(cyl(21.0, PLATE_T * 4, at=(0, PLATE_Y - PLATE_T * 2, 0), axis="Y"))
    b = bearing(IF["secondary_shaft"]["bearing"])
    p = p.cut(cyl(b["od_mm"] + FDM["bearing_bore_interference_mm"], PLATE_T * 4,
                  at=(0, -PLATE_Y - PLATE_T * 2, 0), axis="Y"))
    rows.append({"feature": "侧板 ×1（含窗/舵盘孔/轴承孔）", "shape": p, "count": 2})

    rows.append({"feature": "底板", "count": 1,
                 "shape": box(SPAN_X, GAP + 2 * PLATE_T, PLATE_T,
                              at=(0, 0, z_floor_bot))})
    rows.append({"feature": "顶板", "count": 1,
                 "shape": box(SPAN_X, GAP + 2 * PLATE_T, PLATE_T,
                              at=(0, 0, z_cap_bot))})
    sp = cyl(SPIGOT_D, SPIGOT_H, at=(0, 0, z_cap_top))
    sp = sp.cut(cyl(SPIGOT_BORE, SPIGOT_H + 2, at=(0, 0, z_cap_top - 1)))
    rows.append({"feature": "母端插接芯棒（Ø34×14，内孔 Ø24）",
                 "shape": sp, "count": 1})
    return rows


def breakdown_torso() -> List[Dict[str, Any]]:
    from kit import FDM, IF, box, cyl
    from skeleton import PLATE_T, SPIGOT_D
    tl, tw, th, z_lift = 96.0, 86.0, 54.0, 17.0
    rows = []
    posts = cq.Workplane("XY")
    for sx in (-1, 1):
        for sy in (-1, 1):
            posts = posts.union(box(11.0, 11.0, th,
                                    at=(sx * (tl / 2 - 5.5), sy * (tw / 2 - 5.5),
                                        z_lift), centered_z=True))
    rows.append({"feature": "主舱 4 立柱", "shape": posts, "count": 1})
    rows.append({"feature": "主舱上环", "count": 1,
                 "shape": box(tl, tw, PLATE_T, at=(0, 0, z_lift + th / 2 - PLATE_T))})
    rails = cq.Workplane("XY")
    for sx in (-1, 1):
        rails = rails.union(box(PLATE_T, tw, 12.0, at=(sx * (tl / 2 - PLATE_T), 0,
                                                      z_lift), centered_z=True))
    rows.append({"feature": "主舱侧横梁", "shape": rails, "count": 1})
    rows.append({"feature": "树莓派托盘 64×88×2.6", "count": 1,
                 "shape": box(64.0, 88.0, 2.6, at=(0, 0, z_lift - 8.0 - 2.6))})
    rows.append({"feature": "电控托盘 88×68×2.6", "count": 1,
                 "shape": box(88.0, 68.0, 2.6, at=(0, 0, z_lift + 14.0))})
    bat = cq.Workplane("XY")
    bat = bat.union(box(40.0, 92.0, 2.6, at=(0, 0, z_lift - 29.0)))
    for sx in (-1, 1):
        bat = bat.union(box(28.0, 92.0, 2.6, at=(sx * 31.0, 0, z_lift - 29.0)))
    for sy in (-1, 1):
        bat = bat.union(box(40.0, 2.6, 22.0, at=(0, sy * 45.0, z_lift - 17.0)))
    bat = bat.union(box(2.6, 92.0, 22.0, at=(19.0, 0, z_lift - 17.0)))
    rows.append({"feature": "电池框（底+侧梁+壁）", "shape": bat, "count": 1})
    pyl = cq.Workplane("XY")
    for sign in (-1, 1):
        pyl = pyl.union(box(40.0, 26.0, 34.0, at=(0, sign * 54.0, z_lift + 11.8),
                            centered_z=True))
        pyl = pyl.cut(box(22.0, 20.0, 22.0, at=(0, sign * 54.0, z_lift + 11.8),
                          centered_z=True))
    rows.append({"feature": "双肩 pylon（实心盒挖空）", "shape": pyl, "count": 1})
    chest = cq.Workplane("XY")
    chest = chest.union(box(70.0, 58.0, 6.0, at=(0, 0, z_lift + th / 2 - 3.0)))
    for sx in (-1, 1):
        for sy in (-1, 1):
            chest = chest.union(box(9.0, 9.0, 52.0,
                                    at=(sx * 29.0, sy * 22.0, z_lift + th / 2 + 25.0),
                                    centered_z=True))
    chest = chest.union(box(70.0, 52.0, PLATE_T, at=(0, 0, z_lift + th / 2 + 48.0)))
    chest = chest.union(cyl(SPIGOT_D, 10.0, at=(0, 0, z_lift + th / 2 + 48.0 + PLATE_T)))
    rows.append({"feature": "胸段 + 颈柱", "shape": chest, "count": 1})
    return rows


def breakdown_fork() -> List[Dict[str, Any]]:
    from kit import IF, box, bearing
    from skeleton import (PLATE_T, SPIGOT_BORE, SPIGOT_D, SPIGOT_H, S, Y_HALF,
                          Z_BOT, Z_TOP)
    b = bearing(IF["secondary_shaft"]["bearing"])
    horn_face = Y_HALF + S["horn_disc_thickness_mm"]
    arm_out = horn_face + 0.05
    arm_t = PLATE_T
    z_top = Z_TOP + 2.0
    z_base_top = Z_BOT - 12.0
    z_base_bot = z_base_top - arm_t
    arm_b_out = -(Y_HALF + b["width_mm"] + 0.4 + arm_t)
    rows = []
    rows.append({"feature": "臂 A（锁舵盘侧）34×40×3", "count": 1,
                 "shape": box(34.0, arm_t, z_top - z_base_bot,
                              at=(0, arm_out + arm_t / 2.0, z_base_bot))})
    rows.append({"feature": "臂 B（轴承侧）34×40×3", "count": 1,
                 "shape": box(34.0, arm_t, z_top - z_base_bot,
                              at=(0, arm_b_out + arm_t / 2.0, z_base_bot))})
    rows.append({"feature": "底座 + Ø34 芯棒", "count": 1,
                 "shape": box(38.0, abs(arm_out + arm_t - arm_b_out), arm_t,
                              at=(0, (arm_out + arm_t + arm_b_out) / 2.0,
                                  z_base_bot))})
    return rows


BUILDERS = {
    "joint_cage": breakdown_joint_cage,
    "torso_frame": breakdown_torso,
    "limb_fork": breakdown_fork,
}


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="质量分解诊断")
    ap.add_argument("--part", default=None, choices=sorted(BUILDERS))
    args = ap.parse_args(argv)
    names = [args.part] if args.part else sorted(BUILDERS)

    for name in names:
        print("=" * 74)
        print(f"{name}")
        print("=" * 74)
        try:
            full = sk.build(name)
            fv, fm = measure(name, full)
            print(f"  实测整件          {fv:>9.0f} mm³   {fm:>6.1f} g")
        except Exception as exc:  # noqa: BLE001
            print(f"  [ERR] 整件构建失败: {exc}")
            continue
        total = 0.0
        for row in BUILDERS[name]():
            try:
                v, m = measure(row["feature"], row["shape"])
            except Exception as exc:  # noqa: BLE001
                print(f"  {row['feature']:<34} 测量失败 {exc}")
                continue
            cnt = row.get("count", 1)
            total += m * cnt
            print(f"  {row['feature']:<34} ×{cnt}  {v:>8.0f} mm³  "
                  f"{m:>6.1f} g  小计 {m*cnt:>6.1f} g  ({m*cnt/fm*100:>4.1f}%)")
        print(f"  {'特征合计':<34}     {total:>6.1f} g "
              f"（整件 {fm:.1f} g，差 {fm-total:+.1f} g = 圆角/交集重叠）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
