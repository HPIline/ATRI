#!/usr/bin/env python3
"""把 CAD 实装测量结果并入 L1 模型（v2 → v3）。

用法：
    python3 design/gen_v3_baseline.py            # 迁移（已迁移则拒绝重复执行）
    python3 design/gen_v3_baseline.py --check    # 只看当前版本
    python3 design/gen_v3_baseline.py --refresh  # 已迁移过：按权威源刷新实装包络/质量口径

为什么有 v3
-----------
v2 的结构件质量（500 g）是**本项目的合成预算**；协作者用真实 CAD 体积 × PETG 密度
（`design/cad/assembly.py`）算出实装结构件 **1790 g**，整机 3435 g —— 二者差 258%。

按用户决定：**相关数据以协作者最新上传的 CAD 实装结果为准**。
本脚本把该结果并入模型，并把三条减重路径登记为待决策项。

`--refresh` 是给"已经迁到 v3 之后、CAD 又往前跑了几轮"用的：
它从 `reference/cad_assembly_measurements.json` 重新读实装包络与结构件实算质量
（该文件是 CAD 实测量的唯一落盘处），幂等重算，**不碰关节/连杆/运动学**。
禁止手改 `robot_model.json` 里这几行——改源头再刷新。

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
REPO = HERE.parents[2]  # design/v1-22dof/archive → repo
MODEL_PATH = HERE / "robot_model.json"
COMPONENTS_PATH = HERE / "components.json"
CAD_MEAS_PATH = HERE / "reference" / "cad_assembly_measurements.json"


def _envelope_from_cad(model: Dict[str, Any], cad: Dict[str, Any]) -> Dict[str, Any]:
    """实装包络块：唯一来源是 cad_assembly_measurements.json 的 installed_envelope_mm。"""
    env = cad["installed_envelope_mm"]
    ov = model["overall"]
    return {
        "height_mm": env["z_height"],
        "width_mm": env["y_width"],
        "depth_mm": env["x_depth"],
        "source": f"CAD 实装装配体（{cad['source_commit']} / {cad['source_doc']}）",
        "measured_by": cad.get("measured_by", ""),
        "kinematic_envelope_mm": {
            "height_mm": ov["height_mm"],
            "width_mm": ov["width_mm"],
            "depth_mm": ov["depth_mm"],
        },
        "delta_mm": {"height": round(env["z_height"] - ov["height_mm"], 1),
                     "width": round(env["y_width"] - ov["width_mm"], 1),
                     "depth": round(env["x_depth"] - ov["depth_mm"], 1)},
        "why_different": ("基元模型的 link 包围盒是占位值，舵机笼与支架的实际突出量没进门；"
                          "实装包络才是报名材料该用的口径。"),
        "competition_limit_mm": [600.0, 300.0, 300.0],
        "limit_ok": (env["z_height"] <= 600.0 and env["y_width"] <= 300.0
                     and env["x_depth"] <= 300.0),
        "order_note": "高 × 宽 × 深（与 installed_envelope_mm 源文件的 X×Y×Z = 深×宽×高 顺序不同）",
    }


def _servo_defaults(model: Dict[str, Any]) -> None:
    """把舵机的**官方**口径写进 servo_defaults（额定 ≠ 堵转，速度 0.222 s/60°）。"""
    sd = model.setdefault("servo_defaults", {})
    sd["stall_torque_nm"] = 2.94
    sd["rated_torque_nm"] = 0.98
    sd["rated_torque_basis"] = (
        "【官方】额定负载 10 kg·cm = 0.98 N·m @12V（DFRobot SER0070 + 飞特 STS3235 规格书双重印证，"
        "见 design/handoff/STS3215-官方规格书核验.md §4.1、总体参数汇总表.md §2.1）。"
        "历史口径『堵转 × 50% = 1.47 N·m』偏乐观 50%，降为并列参考"
        "（rated_torque_nm_half_stall_deprecated），不再是 rated_torque_nm"
    )
    sd["rated_torque_nm_half_stall_deprecated"] = 1.47   # 历史判据『堵转×50%』，偏乐观 50%
    sd["no_load_speed_dps"] = 270.0
    sd["speed_basis"] = (
        "0.222 s/60°(12V) → 270 °/s。来源【实物包装标签】ST-3215-C018"
        "（见 design/reference/sts3215/）；0.18 与 300 °/s 均无出处，2026-09-11 订正"
    )


def _apply_structure_scale(model: Dict[str, Any], new_structure_g: float) -> float:
    """把各 link 的结构质量按比例缩放到新的实算总量，并重摊线束/紧固件。

    返回 sum(link mass)（g）。幂等：同一个 new_structure_g 反复跑结果一致。
    """
    applied = float(model["mass_budget"]["structure_g"])
    k = new_structure_g / applied if applied > 0 else 1.0
    if abs(k - 1.0) > 1e-12:
        for link in model["links"]:
            bd = link["mass_breakdown_g"]
            bd["structure"] = round(bd["structure"] * k, 1) if k != 1.0 else bd["structure"]

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
    return sum(l["mass_kg"] for l in model["links"]) * 1000.0


def _mass_status(cad: Dict[str, Any]) -> Dict[str, Any]:
    """整机质量口径的**状态标注**（用户仍在与队友讨论重量方案，未定案）。"""
    total = cad.get("total_mass_g")
    return {
        "structure_source": "实算",
        "total_source": "纸面推算",
        "state": "整机重量方案未定案",
        "note": (f"结构件 {cad['structure_total_g']:.0f} g / {cad.get('part_count', '—')} 件为 CAD 实算；"
                 f"整机 {total:.0f} g 为「结构实算 + 舵机 1210 + 电子件与电池 316 + 线束紧固件 120」的"
                 f"纸面推算（≈{total / 1000.0:.3f} kg），**重量方案尚未定案**（减重 / 换工艺 / 减件三选一），"
                 f"定案后须重测回填。"),
        "history": [{"caliber": "v3 虚高值", "structure_g": 1790.0, "total_g": 3435.0,
                     "why": "『舵机 35 与 24.7 用反』时期，见 装配一致性修正记录.md §4.4"},
                    {"caliber": "第 4 轮修正后", "structure_g": 1404.0, "total_g": 3050.0,
                     "why": "装配一致性修正，见 装配一致性修正记录.md §4.4"},
                    {"caliber": "第 5 轮后", "structure_g": 1490.0, "total_g": 3136.0,
                     "why": "第 5 轮新零件族 +86 g，见 装配一致性修正记录.md §8.3"},
                    {"caliber": "第 6–10 轮合入后（当前）", "structure_g": float(cad["structure_total_g"]),
                     "total_g": float(total) if total else None,
                     "why": "atri-next 十轮 CAD 改造（骨盆 U 架/头壳封顶/足垫/背挂外移），"
                            "结构件 1490 → 1390 g；at 2026-09-12 模型质量已回灌 URDF，"
                            "见 design/handoff/线程报告-模型质量回灌.md"}],
    }

def _sync_components(cad: Dict[str, Any]) -> None:
    """components.json 里的舵机官方口径 + 结构件实算质量（与 robot_model 同源）。"""
    comps = json.loads(COMPONENTS_PATH.read_text(encoding="utf-8"))
    comps["structure_mass_estimate_g"] = float(cad["structure_total_g"])
    comps["structure_mass_note"] = (
        f"v3：按协作者 CAD 实装实算 {cad['structure_total_g']:.0f} g"
        f"（{cad.get('part_count', '—')} 个件，真实体积 × PETG 1.27 g/cm³）。"
        "v2 的 500 g 是合成预算，已弃用。三条减重路径见 robot_model.json 的 reduction_paths。")
    for c in comps.get("components", []):
        if c.get("role") == "servo_s":
            sp = c.setdefault("spec", {})
            sp["rated_torque_nm"] = 0.98
            sp["stall_torque_nm"] = 2.94
            sp["rated_torque_nm_half_stall_deprecated"] = 1.47
            sp["rated_basis"] = (
                "【官方】额定负载 10 kg·cm = 0.98 N·m @12V（DFRobot SER0070 + 飞特 STS3235 规格书，"
                "2026-09-11 确认）；历史『堵转 × 50% = 1.47 N·m』偏乐观 50%，降为并列参考；"
                "早期『额定 1.0 N·m 无权威出处』的说法已撤销")
            sp["speed_s_per_60deg"] = 0.222
            sp["speed_basis"] = (
                "0.222 s/60°(12V) → 270 °/s。来源【实物包装标签】ST-3215-C018"
                "（见 design/reference/sts3215/）；0.18 与 300 °/s 均无出处，2026-09-11 订正")
            c["note"] = ("全机型号归一；额定取【官方】0.98 N·m（2026-09-11 确认），"
                         "历史『堵转 × 50% = 1.47』仅作并列参考")
    COMPONENTS_PATH.write_text(json.dumps(comps, ensure_ascii=False, indent=2) + "\n",
                               encoding="utf-8")


def _refresh(model: Dict[str, Any], cad: Dict[str, Any]) -> int:
    """已迁到 v3 之后：按权威源刷新实装包络 / 结构件实算质量 / 舵机官方口径。幂等。

    幂等保证：口径已经等于权威源时**不写任何字段、不追加 changelog**（只打印"已是最新"）。
    否则反复 `--refresh` 会把 changelog 灌满重复条目、并让各 link 的取整误差累积。
    """
    old_env = model.get("installed_envelope_mm", {})
    old_struct = float(model["mass_budget"]["structure_g"])
    want_struct = float(cad["structure_total_g"])
    want_env = (float(cad["installed_envelope_mm"]["z_height"]),
                float(cad["installed_envelope_mm"]["y_width"]),
                float(cad["installed_envelope_mm"]["x_depth"]))
    have_env = (float(old_env.get("height_mm", 0)), float(old_env.get("width_mm", 0)),
                float(old_env.get("depth_mm", 0)))
    sd = model.get("servo_defaults", {})
    up_to_date = (abs(old_struct - want_struct) < 1e-9 and have_env == want_env
                  and float(sd.get("rated_torque_nm", 0)) == 0.98
                  and float(sd.get("no_load_speed_dps", 0)) == 270.0)
    if up_to_date:
        _sync_components(cad)
        print("口径已是最新，无需刷新（幂等跳过）")
        print(f"  实装包络 {' × '.join(f'{v:.0f}' for v in have_env)} mm")
        print(f"  结构件 {want_struct:.0f} g（{cad.get('part_count', '—')} 件，实算）")
        print(f"  整机   {model['overall']['mass_kg']:.3f} kg（纸面推算，重量方案未定案）")
        return 0

    model["installed_envelope_mm"] = _envelope_from_cad(model, cad)
    # ⚠️ 顺序要紧：_apply_structure_scale 用 mass_budget["structure_g"] 作为**当前已应用值**
    # 算缩放比，所以必须先缩放、后改这个字段。
    new_total_g = _apply_structure_scale(model, want_struct)
    model["mass_budget"]["structure_g"] = want_struct
    # 头条数字用权威源（out/report.md 的整机合计，报告里就是 3136），
    # 另存 sum(link mass) 的实际累加值，避免两边对不上时看不出来（差异来自各 link 分摊取整）。
    model["mass_budget"]["total_g"] = float(cad.get("total_mass_g") or round(new_total_g, 1))
    model["mass_budget"]["total_g_from_links"] = round(new_total_g, 1)
    total_g = float(model["mass_budget"]["total_g"])
    model["mass_budget"]["closure_delta_g"] = round(new_total_g - total_g, 1)
    model["mass_budget"]["structure_source"] = (
        f"CAD 实装实算（真实体积 × PETG 1.27 g/cm³），来源 {cad['source_commit']} / {cad['source_doc']}")
    model["mass_budget"]["note"] = (
        "全部摊入 link 质量；gen_handoff 的 cable/fastener 假设仍为 0，避免重复计入。"
        "结构件为实算，整机为纸面推算，重量方案未定案，见 mass_status。")
    model["overall"]["mass_kg"] = round(total_g / 1000.0, 3)
    model["mass_status"] = _mass_status(cad)
    _servo_defaults(model)
    model["reduction_paths"] = cad.get("reduction_paths", model.get("reduction_paths", []))
    model["reduction_recommendation"] = cad.get("recommendation", model.get("reduction_recommendation", ""))
    model["reduction_pending"] = cad.get("pending", model.get("reduction_pending", ""))
    model.setdefault("changelog", []).append({
        "from": "3.0", "to": "3.0-refresh",
        "changes": [
            f"实装包络 {(old_env.get('height_mm') or 0):.0f} × {(old_env.get('width_mm') or 0):.0f} "
            f"× {(old_env.get('depth_mm') or 0):.0f} → {cad['installed_envelope_mm']['z_height']:.0f} × "
            f"{cad['installed_envelope_mm']['y_width']:.0f} × {cad['installed_envelope_mm']['x_depth']:.0f} mm"
            f"（来源 {cad['source_commit']} / {cad['measured_by']}）",
            f"结构件实算质量 {old_struct:.0f} → {cad['structure_total_g']:.0f} g"
            f"（{cad.get('part_count', '—')} 件）；各 link 按比例重摊",
            f"整机质量 {model['overall']['mass_kg']:.3f} kg（纸面推算，重量方案未定案）",
            "舵机口径：额定 0.98 N·m（官方）/ 堵转 2.94 / 空载 270 °/s；1.47 降为并列参考",
        ],
    })
    MODEL_PATH.write_text(json.dumps(model, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _sync_components(cad)

    ie = model["installed_envelope_mm"]
    print("v3 口径刷新完成（数据源：CAD 实装测量）")
    print(f"  实装包络 {old_env.get('height_mm', '—')} × {old_env.get('width_mm', '—')} × "
          f"{old_env.get('depth_mm', '—')} → {ie['height_mm']:.0f} × {ie['width_mm']:.0f} × "
          f"{ie['depth_mm']:.0f} mm")
    print(f"  结构件 {old_struct:.0f} → {cad['structure_total_g']:.0f} g"
          f"（{cad.get('part_count', '—')} 件，实算）")
    print(f"  整机   {model['overall']['mass_kg']:.3f} kg（纸面推算，重量方案未定案）")
    print(f"  舵机   额定 0.98 / 堵转 2.94 N·m，空载 270 °/s")
    print(f"  赛题包络上限判定：{'✅ 通过' if ie['limit_ok'] else '❌ 超限'}")
    return 0


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="并入 CAD 实装测量结果（v2 → v3）")
    ap.add_argument("--check", action="store_true", help="只报告当前模型版本")
    ap.add_argument("--refresh", action="store_true",
                    help="已迁到 v3：按权威源刷新实装包络 / 结构件实算质量（幂等）")
    args = ap.parse_args(argv)

    model: Dict[str, Any] = json.loads(MODEL_PATH.read_text(encoding="utf-8"))
    cad: Dict[str, Any] = json.loads(CAD_MEAS_PATH.read_text(encoding="utf-8"))
    version = str(model.get("version", "1.0"))

    if args.check:
        print(f"robot_model.json version = {version}")
        ie = model.get("installed_envelope_mm", {})
        print(f"  身高 {model['overall']['height_mm']} mm（基元）"
              f"｜实装 {ie.get('height_mm', '—')} × {ie.get('width_mm', '—')} "
              f"× {ie.get('depth_mm', '—')} mm")
        print(f"  结构件实算 {model['mass_budget']['structure_g']:.0f} g"
              f"（{cad.get('part_count', '—')} 件）")
        print(f"  整机质量 {model['overall']['mass_kg']} kg（推算，重量方案未定案）")
        return 0

    if args.refresh:
        return _refresh(model, cad)

    if version.startswith("3."):
        print("已是 v3，拒绝重复迁移。（要按最新 CAD 实测量刷新请用 --refresh）")
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
    model["installed_envelope_mm"] = _envelope_from_cad(model, cad)

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
        f"〔订正：上述「418 mm 高」是 6d4b077 时刻的历史值，现行实测见 installed_envelope_mm；"
        f"整机质量为纸面推算且重量方案未定案，见 mass_status。〕"
    )
    model["mass_status"] = _mass_status(cad)
    model.setdefault("changelog", []).append({
        "from": "2.0", "to": "3.0",
        "changes": [
            f"结构件质量 {old_structure_g:.0f} → {new_structure_g:.0f} g（CAD 实装实算，×{k:.3f} 比例分摊）",
            f"整机质量 {total_g / 1000.0:.3f} kg",
            f"新增 installed_envelope_mm = {env['z_height']:.0f} × {env['y_width']:.0f} "
            f"× {env['x_depth']:.0f} mm（CAD 实装；基元口径仍为 "
            f"{model['overall']['height_mm']:.1f} mm）",
            "新增 reduction_paths：A 拓扑减重 / B 买金属件 / C 减自由度",
            "来源：6d4b077《骨架零件库与整机装配》、design/robot_model.json",
        ],
    })
    MODEL_PATH.write_text(json.dumps(model, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")

    # ---- 4) components.json ----
    comps = json.loads(COMPONENTS_PATH.read_text(encoding="utf-8"))
    comps["structure_mass_estimate_g"] = new_structure_g
    comps["structure_mass_note"] = (
        f"v3：按协作者 CAD 实装实算 {new_structure_g:.0f} g（{cad.get('part_count', 74)} 个件，"
        f"真实体积 × PETG 1.27 g/cm³）。"
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
