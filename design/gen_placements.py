#!/usr/bin/env python3
"""生成 design/placements.json —— 配件位置总表（可重复运行）。

为什么单独抽出来：本文件原来内嵌在 `gen_v2_baseline.py` 的一次性迁移里，
于是 v3 改了质量之后它就过期了（还写着 2146 g）。现在它是**从 L1 模型 + components.json
派生**的常规产物，模型一改就能重跑。

数据来源（全部单一真值）：
- 舵机：每个关节一只，装在**该关节的父 link** 上，位置 = 关节原点（`robot_model.json`）
- 电子件：`design/components.json` 的 `placements`
- 结构件：`robot_model.json` 的 links（几何 + 质量分项）
- 线束紧固件：`design/components.json` 的 `cable_mass_g` / `fastener_mass_g`

用法：
    python3 design/gen_placements.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

HERE = Path(__file__).resolve().parent
MODEL = HERE / "robot_model.json"
COMPONENTS = HERE / "components.json"
OUT = HERE / "placements.json"
sys.path.insert(0, str(HERE))
import geometry  # noqa: E402


def main() -> int:
    m: Dict[str, Any] = json.loads(MODEL.read_text(encoding="utf-8"))
    c: Dict[str, Any] = json.loads(COMPONENTS.read_text(encoding="utf-8"))
    sd = m["servo_defaults"]

    # ---- 舵机：每个关节一只，装在父 link 上 ----
    servos: List[Dict[str, Any]] = []
    for j in sorted(m["joints"], key=lambda x: x["id"]):
        servos.append({
            "joint": j["name"],
            "id": j["id"],
            "mounted_on_link": j["parent"],
            "position_mm": j["origin_xyz_mm"],
            "axis": j["axis"],
            "size_mm": sd["size_mm"],
            "mass_g": sd["mass_g"],
            "model": sd["model"],
        })

    electronics = [
        {"id": p.get("component", ""), "name": p["component"], "link": p["link"],
         "mass_g": p.get("mass_g"), "size_mm": p.get("size_mm"),
         "position_mm": p.get("position_mm"), "note": p.get("note", "")}
        for p in c.get("placements", [])
    ]

    structures = []
    for link in m["links"]:
        bb = geometry.bounding_box(link["geometry"])
        structures.append({
            "link": link["name"], "group": link.get("group", ""),
            "primitive": link["geometry"].get("type", ""),
            "bbox_mm": [round(v, 1) for v in bb],
            "structure_mass_g": link.get("mass_breakdown_g", {}).get("structure"),
            "total_link_mass_g": round(link["mass_kg"] * 1000.0, 1),
        })

    total_g = sum(l["mass_kg"] for l in m["links"]) * 1000.0
    ie = m.get("installed_envelope_mm", {})
    out = {
        "schema_version": "3.0",
        "generated_by": "design/gen_placements.py",
        "model_version": m.get("version"),
        "units": {"length": "mm", "mass": "g", "angle": "deg", "axis": "URDF 约定（+z 向上）"},
        "frame_note": (
            "position_mm 是相对『宿主 link 坐标系原点』的偏移；link 坐标系原点落在驱动它的关节轴线上。"
            "舵机的位置 = 它驱动的那个关节的原点（即父 link 坐标系里的 joint origin）。"
            "全部为**设计位**，实物装配前须按采购件复测。"
        ),
        "servos": servos,
        "electronics": electronics,
        "harness_fasteners": {
            "cable_g": c.get("cable_mass_g"), "fastener_g": c.get("fastener_mass_g"),
            "allocation": "按各 link 的（结构+舵机+电子）质量比例摊派（见各 link 的 harness_fasteners 分项）",
        },
        "structures": structures,
        "summary": {
            "links": len(m["links"]), "joints": len(m["joints"]), "servos": len(servos),
            "envelope_installed_mm": [ie.get("height_mm"), ie.get("width_mm"), ie.get("depth_mm")],
            "envelope_kinematic_mm": [m["overall"]["height_mm"], m["overall"]["width_mm"],
                                      m["overall"]["depth_mm"]],
            "total_mass_g": round(total_g, 1),
            "mass_budget_g": m["mass_budget"],
            "reduction_paths": m.get("reduction_paths", []),
        },
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已写出 {OUT.relative_to(HERE.parent)}")
    print(f"  {len(servos)} 舵机 + {len(electronics)} 电子件 + {len(structures)} 结构件"
          f"｜整机 {total_g / 1000.0:.3f} kg｜实装包络 "
          f"{ie.get('height_mm')}×{ie.get('width_mm')}×{ie.get('depth_mm')} mm")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
