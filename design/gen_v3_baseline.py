#!/usr/bin/env python3
"""把 CAD 实装测量结果并入 L1 模型（v2 → v3）。

用法：
    python3 design/gen_v3_baseline.py            # 迁移（已迁移则拒绝重复执行）
    python3 design/gen_v3_baseline.py --check    # 只看当前版本

为什么有 v3
-----------
v2 的结构件质量（500 g）是**本项目的合成预算**；协作者用真实 CAD 体积 × PETG 密度
（`design/cad/assembly.py`）算出实装结构件 **1790 g**，整机 3435 g —— 二者差 258%。

按用户决定：**相关数据以协作者最新上传的 CAD 实装结果为准**。
本脚本把该结果并入模型，并把三条减重路径登记为待决策项。

改了什么（相对 v2）
------------------
1. ``structure_mass_g`` 500 → **1790 g**（CAD 实算；按原面密度比例分摊到各 link，
   模块级明细见 ``design/reference/cad_assembly_measurements.json``）
2. 新增 ``installed_envelope_mm`` = **418 × 223 × 129 mm**（CAD 实装包络）
   —— 基元模型的 372.8 × 190 × 123 是**运动学链包络**，不含支架/舵机笼厚度
3. 新增 ``reduction_paths``：A 拓扑减重 / B 买金属件 / C 减自由度（数字取自协作者 §7 表）
4. 质量预算与随附的 components.json 同步

**未改**：关节定义、连杆几何、运动学（那部分 v2 已定，与本轮无关）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
MODEL_PATH = HERE / "robot_model.json"
COMPONENTS_PATH = HERE / "components.json"
CAD_MEAS_PATH = HERE / "reference" / "cad_assembly_measurements.json"


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="并入 CAD 实装测量结果（v2 → v3）")
    ap.add_argument("--check", action="store_true", help="只报告当前模型版本")
    args = ap.parse_args(argv)

    model: Dict[str, Any] = json.loads(MODEL_PATH.read_text(encoding="utf-8"))
    cad: Dict[str, Any] = json.loads(CAD_MEAS_PATH.read_text(encoding="utf-8"))
    version = str(model.get("version", "1.0"))

    if args.check:
        print(f"robot_model.json version = {version}")
        print(f"  身高 {model['overall']['height_mm']} mm（基元）"
              f"｜实装 {model.get('installed_envelope_mm', {}).get('z_height_mm', '—')} mm")
        print(f"  整机质量 {model['overall']['mass_kg']} kg")
        return 0

    if version.startswith("3."):
        print("已是 v3，拒绝重复迁移。")
        return 1

    # ---- 1) 结构件质量：按 v2 的面密度比例放大到 CAD 实算总量 ----
    old_structure_g = float(model["mass_budget"]["structure_g"])
    new_structure_g = float(cad["structure_total_g"])
    k = new_structure_g / old_structure_g

    for link in model["links"]:
        bd = link["mass_breakdown_g"]
        bd["structure"] = round(bd["structure"] * k, 1)
        total = sum(bd.values())
        link["mass_kg"] = round(total / 1000.0, 5)

    # 线束/紧固件按新总量比例重摊（保持"按质量比例摊派"的口径）
    servo_g = float(model["mass_budget"]["servos_g"])
    elec_g = float(model["mass_budget"]["electronics_g"])
    harness_g = float(model["mass_budget"]["harness_fasteners_g"])
    base = {l["name"]: l["mass_breakdown_g"]["structure"]
            + l["mass_breakdown_g"]["servos"]
            + l["mass_breakdown_g"]["electronics"] for l in model["links"]}
    base_sum = sum(base.values())
    for link in model["links"]:
        bd = link["mass_breakdown_g"]
        bd["harness_fasteners"] = round(harness_g * base[link["name"]] / base_sum, 1)
        link["mass_kg"] = round(sum(bd.values()) / 1000.0, 5)

    total_g = sum(l["mass_kg"] for l in model["links"]) * 1000.0

    # ---- 2) 实装包络 ----
    env = cad["installed_envelope_mm"]
    model["installed_envelope_mm"] = {
        "height_mm": env["z_height"],
        "width_mm": env["y_width"],
        "depth_mm": env["x_depth"],
        "source": f"CAD 实装装配体（{cad['source_commit']} / {cad['source_doc']}）",
        "kinematic_envelope_mm": {
            "height_mm": model["overall"]["height_mm"],
            "width_mm": model["overall"]["width_mm"],
            "depth_mm": model["overall"]["depth_mm"],
        },
        "delta_mm": {"height": round(env["z_height"] - model["overall"]["height_mm"], 1),
                     "width": round(env["y_width"] - model["overall"]["width_mm"], 1),
                     "depth": round(env["x_depth"] - model["overall"]["depth_mm"], 1)},
        "why_different": ("基元模型的 link 包围盒是占位值，舵机笼与支架的实际突出量没进门；"
                          "实装包络才是报名材料该用的口径。"),
        "competition_limit_mm": [600.0, 300.0, 300.0],
        "limit_ok": (env["z_height"] <= 600.0 and env["y_width"] <= 300.0
                     and env["x_depth"] <= 300.0),
    }

    # ---- 3) 减重路径 + 版本 ----
    model["version"] = "3.0"
    model["reduction_paths"] = cad["reduction_paths"]
    model["reduction_recommendation"] = cad["recommendation"]
    model["reduction_pending"] = cad["pending"]
    model["mass_budget"] = {
        "structure_g": new_structure_g,
        "servos_g": servo_g,
        "electronics_g": elec_g,
        "harness_fasteners_g": harness_g,
        "total_g": round(total_g, 1),
        "structure_source": ("CAD 实装实算（真实体积 × PETG 1.27 g/cm³），"
                             f"来源 {cad['source_commit']} / {cad['source_doc']}"),
        "note": "全部摊入 link 质量；gen_handoff 的 cable/fastener 假设仍为 0，避免重复计入。",
    }
    model["overall"]["mass_kg"] = round(total_g / 1000.0, 3)
    model["overall"]["note"] = (
        f"v3：结构件按 CAD 实装实算 {new_structure_g:.0f} g（v2 合成预算为 {old_structure_g:.0f} g），"
        f"整机 {total_g / 1000.0:.3f} kg。**实装包络见 installed_envelope_mm（418 mm 高）**，"
        f"overall 里的包络是基元/运动学口径。"
    )
    model.setdefault("changelog", []).append({
        "from": "2.0", "to": "3.0",
        "changes": [
            f"结构件质量 {old_structure_g:.0f} → {new_structure_g:.0f} g（CAD 实装实算，×{k:.3f} 比例分摊）",
            f"整机质量 {total_g / 1000.0:.3f} kg",
            f"新增 installed_envelope_mm = {env['z_height']:.0f} × {env['y_width']:.0f} "
            f"× {env['x_depth']:.0f} mm（CAD 实装；基元口径仍为 "
            f"{model['overall']['height_mm']:.1f} mm）",
            "新增 reduction_paths：A 拓扑减重 / B 买金属件 / C 减自由度",
            "来源：6d4b077《骨架零件库与整机装配》、项目文档/骨架结构与集成方案.md §6–§7",
        ],
    })
    MODEL_PATH.write_text(json.dumps(model, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")

    # ---- 4) components.json ----
    comps = json.loads(COMPONENTS_PATH.read_text(encoding="utf-8"))
    comps["structure_mass_estimate_g"] = new_structure_g
    comps["structure_mass_note"] = (
        f"v3：按协作者 CAD 实装实算 {new_structure_g:.0f} g（74 个件，真实体积 × PETG 1.27 g/cm³）。"
        f"v2 的 {old_structure_g:.0f} g 是合成预算，已弃用。三条减重路径见 robot_model.json 的 reduction_paths。")
    COMPONENTS_PATH.write_text(json.dumps(comps, ensure_ascii=False, indent=2) + "\n",
                               encoding="utf-8")

    print("v2 → v3 并入完成（数据源：CAD 实装测量）")
    print(f"  结构件 {old_structure_g:.0f} → {new_structure_g:.0f} g")
    print(f"  整机   {total_g / 1000.0:.3f} kg")
    print(f"  实装包络 {env['z_height']:.0f} × {env['y_width']:.0f} × {env['x_depth']:.0f} mm"
          f"（基元口径 {model['overall']['height_mm']:.1f} mm）")
    print("  减重路径 A/B/C 已登记为待决策项")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
