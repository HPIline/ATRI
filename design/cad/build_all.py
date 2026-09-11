#!/usr/bin/env python3
"""骨架零件一键构建：STEP / STL / 质量审计报告。

用法：
    .venv-cad/bin/python design/cad/build_all.py --all
    .venv-cad/bin/python design/cad/build_all.py --part joint_cage
    .venv-cad/bin/python design/cad/build_all.py --report      # 只出报告

产出：
    out/step/<part>.step     可进 SolidWorks / 任何 CAD
    out/stl/<part>.stl       可 3D 打印
    out/skeleton_parts.json  机器可读的零件表
    out/report.md            可制造性 + 质量闭合报告
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))

import cadquery as cq

import skeleton as sk
from kit import IF, MATERIALS, printed_mass
from standards import FDM, summary as standards_summary

OUT = HERE / "out"

# 质量闭合的其余三档（v3 口径：结构件用 CAD 实算值，见 handoff/新架构参数总表.md §3）
SERVO_G = 55.0 * 22
ELEC_G = 316.0
HARNESS_G = 120.0
BUDGET_STRUCT_G = 1790.0    # v3：CAD 实装实算（74 件）；v2 的合成预算 500 g 已弃用
BUDGET_TOTAL_G = 3437.0     # = 1790 + 1210 + 316 + 120
# 扭矩双口径：主判据 = 官方连续额定（额定负载 10 kg·cm @12V）；
# 峰值 = 堵转 × 50%，仅短时参考（与 components.json / robot_model.json 同源）
CONTINUOUS_NM = 0.98
PEAK_NM = 1.47


def build_one(name: str, export: bool = True) -> Dict[str, Any]:
    spec = sk.SKELETON_PARTS[name]
    shape = sk.build(name)
    rep = sk.report(name, shape)
    rep["count"] = spec.get("count", 1)
    rep["subtotal_g"] = round(rep["mass_printed_g"] * rep["count"], 1)
    if export:
        (OUT / "step").mkdir(parents=True, exist_ok=True)
        (OUT / "stl").mkdir(parents=True, exist_ok=True)
        step = OUT / "step" / f"{name}.step"
        stl = OUT / "stl" / f"{name}.stl"
        cq.exporters.export(shape, str(step))
        cq.exporters.export(shape, str(stl), tolerance=0.08,
                            angularTolerance=0.15)
        rep["step_kb"] = round(step.stat().st_size / 1024, 1)
        rep["stl_kb"] = round(stl.stat().st_size / 1024, 1)
    return rep


def closure(struct_g: float) -> Dict[str, float]:
    total = struct_g + SERVO_G + ELEC_G + HARNESS_G
    torque = 0.49 * total / 1000.0          # v2 判据：τ ≈ 0.49 × 整机质量
    return {
        "struct_g": round(struct_g, 1),
        "servo_g": SERVO_G, "elec_g": ELEC_G, "harness_g": HARNESS_G,
        "total_g": round(total, 1),
        "budget_struct_g": BUDGET_STRUCT_G,
        "budget_total_g": BUDGET_TOTAL_G,
        "struct_over_pct": round((struct_g / BUDGET_STRUCT_G - 1) * 100, 1),
        "ankle_torque_nm": round(torque, 3),
        "ankle_continuous_pct": round(torque / CONTINUOUS_NM * 100, 1),
        "ankle_peak_pct": round(torque / PEAK_NM * 100, 1),
    }


def write_report(reports: List[Dict[str, Any]]) -> Path:
    reports = sorted(reports, key=lambda r: -r["subtotal_g"])
    tot = sum(r["subtotal_g"] for r in reports)
    c = closure(tot)
    rows = "\n".join(
        f"| `{r['part']}` | {r['count']} | {r['material']} | "
        f"{r['infill']*100:.0f}% | {'×'.join(f'{v:.0f}' for v in r['bbox_mm'])} | "
        f"{r['mass_printed_g']:.1f} | **{r['subtotal_g']:.1f}** | "
        f"{'✅' if r['is_valid'] and r['solids'] == 1 else '❌'} |"
        for r in reports)
    warn = "\n".join(f"- `{r['part']}`: {'；'.join(r['warnings'])}"
                     for r in reports if r.get("warnings"))
    ifaces = "\n".join(
        f"| **{k}** | {v.get('why','')[:80]} |" for k, v in IF.items())
    md = f"""# 骨架零件构建报告（v3 · CAD 实物化）

> 自动生成：`design/cad/build_all.py`。内核 **OpenCASCADE**（经 CadQuery 2.5.2），
> 产出为 **B-rep 实体**，非网格基元；质量按 PETG 1.27 g/cm³ + 外壁/填充模型估算。

## 一、零件表（按小计质量降序）

| 零件 | 件数 | 材料 | 填充 | 包络 (mm) | 单件 (g) | 小计 (g) | 几何 |
|---|---|---|---|---|---|---|---|
{rows}
| **合计** | {sum(r['count'] for r in reports)} 件 | | | | | **{c['struct_g']:.0f}** | |

## 二、质量闭合审计

| 项 | 质量 (g) | 说明 |
|---|---|---|
| 打印结构件（实算） | **{c['struct_g']:.0f}** | 本表合计 |
| 打印结构件（v2 预算） | {c['budget_struct_g']:.0f} | 超 **{c['struct_over_pct']:+.0f}%** |
| 舵机 22 × STS3215 | {c['servo_g']:.0f} | 55 g/只 |
| 电子件 + 电池 | {c['elec_g']:.0f} | placements.json |
| 线束 + 紧固件 | {c['harness_g']:.0f} | v2 摊派 |
| **整机合计** | **{c['total_g']:.0f}** | v2 设计值 {c['budget_total_g']:.0f} |
| 踝关节力矩需求 | **{c['ankle_torque_nm']:.2f} N·m** | τ ≈ 0.49 × 整机质量 |
| 占连续额定 {CONTINUOUS_NM} N·m（主判据） | **{c['ankle_continuous_pct']:.0f}%** | {'✅ 可行' if c['ankle_continuous_pct'] <= 90 else '❌ 超连续额定，需减重或换舵机'} |
| 占峰值 {PEAK_NM} N·m（堵转×50%，仅短时参考） | **{c['ankle_peak_pct']:.0f}%** | {'✅ 可行' if c['ankle_peak_pct'] <= 90 else '❌ 超峰值'} |

> ⚠️ **这是本轮最重要的结论**：薄壁打印件的质量 ≈ 材料体积 × 密度，
> 提高填充率或加厚壁只会更重；**减重只能靠减少材料体积（挖料/改形态/改工艺路线）**。
> 详细分析与三条出路见 `项目文档/骨架结构与集成方案.md` 第 7 节。

## 三、接口标准

| 接口 | 取舍理由（摘要） |
|---|---|
{ifaces}

## 四、打印清单与后处理

- 材料：PETG（结构）/ PLA（头壳外观、线夹）；喷嘴 0.4、层高 0.2
- 承力面壁厚 ≥ 3.0 mm；填充 gyroid 30–55%
- 建议按合计质量的 **1.2 倍**备料（支撑 + 失败损耗）
- 后处理：铰 Φ6 h7 副轴孔、攻 M3 径向孔、热熔 M2.5 铜螺母（底孔 Ø3.2）

## 五、可打印性告警

{warn if warn else "（无：所有零件均在 220×220 热床内，无最小特征告警）"}

## 六、标准件参数状态

```
{standards_summary()}
```

**`unknown`/`provisional` 状态的参数是采购前必须闭环的项**，见
`项目文档/骨架结构与集成方案.md` 第 8 节的风险表。
"""
    path = OUT / "report.md"
    path.write_text(md, encoding="utf-8")
    return path


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="A.T.R.I. 骨架零件构建")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--part", type=str, default=None)
    ap.add_argument("--report", action="store_true", help="只重建报告")
    ap.add_argument("--no-export", action="store_true")
    args = ap.parse_args(argv)

    names = [args.part] if args.part else sorted(sk.SKELETON_PARTS)
    reports: List[Dict[str, Any]] = []
    print("=" * 78)
    print("A.T.R.I. 骨架零件构建（OpenCASCADE / CadQuery）")
    print("=" * 78)
    for name in names:
        try:
            r = build_one(name, export=not (args.no_export or args.report))
        except Exception as exc:  # noqa: BLE001
            print(f"  [ERR] {name:<18} {type(exc).__name__}: {exc}")
            continue
        flag = "OK " if r["is_valid"] and r["solids"] == 1 else "BAD"
        print(f"  [{flag}] {name:<18} x{r['count']:<3} "
              f"{'×'.join(f'{v:.0f}' for v in r['bbox_mm']):<14} "
              f"{r['mass_printed_g']:>6.1f} g/件  小计 {r['subtotal_g']:>7.1f} g")
        reports.append(r)

    if not reports:
        return 1
    tot = sum(r["subtotal_g"] for r in reports)
    c = closure(tot)
    print("-" * 78)
    print(f"  结构件合计        {c['struct_g']:>8.1f} g   （预算 {c['budget_struct_g']:.0f} g，"
          f"{c['struct_over_pct']:+.0f}%）")
    print(f"  整机合计          {c['total_g']:>8.1f} g   （v2 设计值 {c['budget_total_g']:.0f} g）")
    print(f"  踝关节力矩需求    {c['ankle_torque_nm']:>8.2f} N·m "
          f"（占连续额定 {CONTINUOUS_NM} 判据 {c['ankle_continuous_pct']:.0f}%，"
          f"占峰值 {PEAK_NM} {c['ankle_peak_pct']:.0f}%）")
    path = write_report(reports)
    json.dump(reports, (OUT / "skeleton_parts.json").open("w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"\n报告: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
