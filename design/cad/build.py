#!/usr/bin/env python3
"""零件构建入口：生成 STEP / STL / 可制造性报告。

用法（需要 CadQuery，建议独立 venv）：
    python3 -m venv .venv-cad
    .venv-cad/bin/pip install cadquery
    .venv-cad/bin/python design/cad/build.py --all
    .venv-cad/bin/python design/cad/build.py --part servo_yoke
    .venv-cad/bin/python design/cad/build.py --standards   # 只看参数状态

产出：
    design/cad/out/step/<part>.step   可进 SolidWorks / 任何 CAD
    design/cad/out/stl/<part>.stl     可 3D 打印
    design/cad/out/report.md          可制造性报告
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

OUT = HERE / "out"


def _require_cadquery():
    try:
        import cadquery  # noqa: F401
    except ImportError:
        print("需要 CadQuery。请先创建独立环境：")
        print("  python3 -m venv .venv-cad")
        print("  .venv-cad/bin/pip install cadquery")
        print("然后用 .venv-cad/bin/python 运行本脚本。")
        raise SystemExit(3)


def build_one(name: str, export: bool = True) -> Dict[str, Any]:
    import cadquery as cq
    import parts

    solid = parts.build(name)
    report = parts.part_report(name, solid)

    if export:
        (OUT / "step").mkdir(parents=True, exist_ok=True)
        (OUT / "stl").mkdir(parents=True, exist_ok=True)
        step = OUT / "step" / f"{name}.step"
        stl = OUT / "stl" / f"{name}.stl"
        cq.exporters.export(solid, str(step))
        cq.exporters.export(solid, str(stl),
                            tolerance=0.05, angularTolerance=0.1)
        report["step_bytes"] = step.stat().st_size
        report["stl_bytes"] = stl.stat().st_size

    # 估算打印质量（PLA 1.24 g/cm³，实心等效，未计填充）
    report["mass_solid_g"] = round(report["volume_mm3"] * 1.24 / 1000.0, 1)
    return report



# --------------------------------------------------------------------------
# 打印清单与质量闭合
# --------------------------------------------------------------------------
PRINT_USAGE: Dict[str, Dict[str, Any]] = {
    "pitch_module": {"count": 14, "infill": 0.50,
                     "note": "俯仰关节模块（hip/knee/ankle/shoulder_pitch/elbow/head_pitch/trunk_pitch）"},
    "limb_segment": {"count": 8, "infill": 0.50,
                     "note": "大腿×2 小腿×2 上臂×2 前臂×2（v2：62.8/62.8/47.1/39.3 mm，此处按大腿 62.8mm 计）"},
    "foot_plate": {"count": 2, "infill": 0.40, "note": "左右足底"},
    "horn_adapter": {"count": 4, "infill": 0.60, "note": "舵盘转接（仅转角处需要）"},
}

MATERIAL_DENSITY = 1.24   # PLA g/cm³


def print_bill(reports: List[Dict[str, Any]]) -> Dict[str, Any]:
    """打印清单：件数、耗材、打印质量。"""
    by_name = {r["part"]: r for r in reports}
    rows = []
    total_g = 0.0
    for name, use in PRINT_USAGE.items():
        r = by_name.get(name)
        if not r:
            continue
        solid_g = r["mass_solid_g"]
        # 打印质量 ≈ 实心 × (外壁占比 + 填充率 × 内部占比)
        printed_g = solid_g * (0.35 + 0.65 * use["infill"])
        subtotal = printed_g * use["count"]
        total_g += subtotal
        rows.append({
            "part": name, "count": use["count"],
            "solid_g": round(solid_g, 1),
            "printed_each_g": round(printed_g, 1),
            "subtotal_g": round(subtotal, 1),
            "infill": use["infill"],
            "note": use["note"],
        })
    return {"rows": rows, "total_printed_g": round(total_g, 1)}


def mass_closure() -> Dict[str, Any]:
    """整机质量闭合：结构 + 外购件 vs 设计预算。"""
    repo = HERE.parent.parent
    comps_p = repo / "design" / "components.json"
    model_p = repo / "design" / "robot_model.json"
    out: Dict[str, Any] = {}
    if comps_p.exists():
        comps = json.loads(comps_p.read_text(encoding="utf-8"))
        servo = next((c for c in comps["components"]
                      if c.get("role") == "servo_s"), None)
        if servo:
            out["servo_g"] = servo["mass_g"] * 22
            out["servo_note"] = f"{servo['name']} x22"
        out["electronics_g"] = round(sum(
            c["mass_g"] * c.get("qty", 1) for c in comps["components"]
            if c.get("role") != "servo_s"), 1)
        out["cable_g"] = comps.get("cable_mass_g", 0.0)
        out["fastener_g"] = comps.get("fastener_mass_g", 0.0)
    if model_p.exists():
        m = json.loads(model_p.read_text(encoding="utf-8"))
        out["design_total_g"] = round(m["overall"]["mass_kg"] * 1000, 0)
    return out


def write_report(reports: List[Dict[str, Any]], standards_text: str) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    bill = print_bill(reports)
    closure = mass_closure()
    bill_rows = "\n".join(
        f"| `{r['part']}` | {r['count']} | {r['solid_g']:.1f} | "
        f"{r['infill']*100:.0f}% | {r['printed_each_g']:.1f} | "
        f"**{r['subtotal_g']:.1f}** | {r['note']} |"
        for r in bill["rows"]
    )
    _servo = closure.get("servo_g", 0.0)
    _elec = closure.get("electronics_g", 0.0)
    _cable = closure.get("cable_g", 0.0)
    _fast = closure.get("fastener_g", 0.0)
    _total = bill["total_printed_g"] + _servo + _elec + _cable + _fast
    _budget = closure.get("design_total_g", 0.0) or 1.0
    _delta = _total - _budget
    rows = "\n".join(
        f"| `{r['part']}` | {r['volume_mm3']:.0f} | "
        f"{'×'.join(f'{v:.1f}' for v in r['bbox_mm'])} | "
        f"{r['mass_solid_g']:.1f} | {r['solids']} | "
        f"{'✅' if r['is_valid'] else '❌'} |"
        for r in reports
    )
    md = f"""# CAD 零件构建报告

> 自动生成：`design/cad/build.py`。内核为 **OpenCASCADE**（经 CadQuery），
> 产出为 **B-rep 实体**，非网格基元。

## 零件清单

| 零件 | 体积 (mm³) | 包络 (mm) | 实心质量 (g) | 实体数 | 几何有效 |
|---|---|---|---|---|---|
{rows}

> 实心质量按 PLA 1.24 g/cm³ 估算，**未计填充率**。实际打印按
> 30–50% 填充约为该值的 40–60%。

## 打印清单

| 零件 | 件数 | 实心(g) | 填充 | 单件(g) | 小计(g) | 说明 |
|---|---|---|---|---|---|---|
{bill_rows}
| **合计** | | | | | **{bill['total_printed_g']:.1f}** | |

> 打印质量 ≈ 实心 × (0.35 + 0.65 × 填充率)，经验估算，未含支撑与失败损耗。
> 建议按合计的 **1.2 倍** 备料。

## 质量闭合

| 项目 | 质量 (g) |
|---|---|
| 打印结构件 | {bill['total_printed_g']:.1f} |
| 舵机 {closure.get('servo_note','')} | {_servo:.1f} |
| 电子件 | {_elec:.1f} |
| 线束 | {_cable:.1f} |
| 紧固件 | {_fast:.1f} |
| **合计** | **{_total:.1f}** |
| 设计预算 | {_budget:.0f} |
| 差 | {_delta:+.0f} ({_delta/_budget*100:+.1f}%) |

## 标准件参数状态

```
{standards_text}
```

**`unknown` 状态的参数是建模阻塞项**，必须先实测回填
`design/cad/standards.py`，否则相关零件只能停留在占位状态。

## 下一步

1. 补齐 `STS3215.body_mount_spacing_mm`（机身安装孔间距）——当前 unknown
2. 复核舵盘节圆（白皮书给了 Φ14 与 Φ16 两个值，需以实物为准）
3. 按同一套 `standards.py` 逐个建立 22 个关节的模块与连杆
4. 组装成装配体，做**干涉检查**与**装配顺序**验证
"""
    path = OUT / "report.md"
    path.write_text(md, encoding="utf-8")
    return path


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="构建 A.T.R.I. CAD 零件")
    ap.add_argument("--all", action="store_true", help="构建全部已登记零件")
    ap.add_argument("--part", type=str, default=None, help="只构建单个零件")
    ap.add_argument("--standards", action="store_true",
                    help="只打印标准件参数状态")
    ap.add_argument("--no-export", action="store_true", help="不写 STEP/STL")
    args = ap.parse_args(argv)

    _require_cadquery()
    import standards
    import parts

    if args.standards:
        print(standards.summary())
        return 0

    names = [args.part] if args.part else sorted(parts.PARTS)
    reports: List[Dict[str, Any]] = []
    print("=" * 68)
    print("CAD 零件构建（OpenCASCADE / CadQuery）")
    print("=" * 68)
    for name in names:
        try:
            r = build_one(name, export=not args.no_export)
        except Exception as exc:  # noqa: BLE001
            print(f"  [ERR] {name:<16} {type(exc).__name__}: {exc}")
            continue
        flag = "OK " if (r["is_valid"] and r["solids"] == 1) else "BAD"
        print(f"  [{flag}] {r['part']:<16} 体积 {r['volume_mm3']:>9.0f} mm³  "
              f"包络 {'×'.join(f'{v:.0f}' for v in r['bbox_mm']):<14} "
              f"≈{r['mass_solid_g']:>5.1f} g(实心)")
        reports.append(r)

    bill = print_bill(reports)
    closure = mass_closure()
    if bill["rows"]:
        print("\n打印清单:")
        for r in bill["rows"]:
            print(f"  {r['part']:<16} x{r['count']:<3} "
                  f"单件 {r['printed_each_g']:>5.1f} g  "
                  f"小计 {r['subtotal_g']:>6.1f} g")
        print(f"  {'打印件合计':<16}     {bill['total_printed_g']:>8.1f} g")
        servo_g = closure.get("servo_g", 0.0)
        elec = closure.get("electronics_g", 0.0)
        cable = closure.get("cable_g", 0.0)
        fast = closure.get("fastener_g", 0.0)
        total = bill["total_printed_g"] + servo_g + elec + cable + fast
        budget = closure.get("design_total_g", 0.0)
        print("\n质量闭合:")
        print(f"  打印结构件        {bill['total_printed_g']:>8.1f} g")
        print(f"  舵机 22x          {servo_g:>8.1f} g")
        print(f"  电子件            {elec:>8.1f} g")
        print(f"  线束+紧固件       {cable + fast:>8.1f} g")
        print(f"  合计              {total:>8.1f} g")
        if budget:
            print(f"  设计预算          {budget:>8.1f} g   "
                  f"差 {total-budget:+.0f} g ({(total-budget)/budget*100:+.1f}%)")

    if reports and not args.no_export:
        path = write_report(reports, standards.summary())
        print(f"\n已导出 STEP/STL 到 {OUT}")
        print(f"报告: {path}")
    bad = [r for r in reports if not (r["is_valid"] and r["solids"] == 1)]
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
