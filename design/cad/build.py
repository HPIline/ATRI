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


def write_report(reports: List[Dict[str, Any]], standards_text: str) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
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

    if reports and not args.no_export:
        path = write_report(reports, standards.summary())
        print(f"\n已导出 STEP/STL 到 {OUT}")
        print(f"报告: {path}")
    bad = [r for r in reports if not (r["is_valid"] and r["solids"] == 1)]
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
