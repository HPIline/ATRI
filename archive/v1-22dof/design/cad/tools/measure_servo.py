#!/usr/bin/env python3
"""STS3215 机械接口核验：从真实 STEP 模型量取接口尺寸。

为什么需要它：`standards.py` 里标注为"飞特官方 2D 工程图纸"的那组数据**自相矛盾**
（总长 51.2 与耳孔距 48.5 推出 0.10 mm 壁厚），需要用真实模型做独立复核，
结论写进 `design/handoff/STS3215-机械接口核验.md`。

> ⚠️ **官网可达性订正（2026-09-11）**：此前写的"官网 feetech.cn / feetechrc.com 不可达"
> **不成立** —— 官网 **feetechrc.com 可达**（只是慢，首字节 ≈8 s，`curl --max-time 120` 稳定 200）；
> 官方规格书 PDF 已入库 `design/cad/vendor/feetech/`。`feetech.cn` 确实不通。
> 详见 `design/handoff/STS3215-官方规格书核验.md` 第 1 节、`design/cad/vendor/README.md`。
> 本脚本仍然有用：它量的是**第三方 B-rep 实物模型**，与官方 PDF 互为独立印证。

模型来源：TheRobotStudio/SO-ARM100（Apache-2.0），`STEP/SO100/STS3215_03a.step`
—— 这是 LeRobot 生态的标准开源机械臂，全球大量用户按它打印支架，
其舵机接口几何经过实物验证。

用法：
    .venv-cad/bin/python design/cad/tools/measure_servo.py
    .venv-cad/bin/python design/cad/tools/measure_servo.py --json   # 机器可读输出

产出（stdout）：包络、端面盘圆心、孔位阵列、特征清单。
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

CAD = Path(__file__).resolve().parent.parent  # design/cad/
HERE = CAD  # 产物仍写到 cad/out，不跟脚本下沉
REPO = HERE.parents[3]  # cad/design/v1-22dof/archive → repo
STEP = REPO / "design" / "reference" / "sts3215" / "STS3215_03a.step"


def _load():
    from OCP.STEPControl import STEPControl_Reader
    from OCP.IFSelect import IFSelect_RetDone

    reader = STEPControl_Reader()
    if reader.ReadFile(str(STEP)) != IFSelect_RetDone:
        raise SystemExit(f"无法读取 {STEP}")
    reader.TransferRoots()
    return reader.OneShape()


def measure() -> Dict[str, Any]:
    from OCP.Bnd import Bnd_Box
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepBndLib import BRepBndLib
    from OCP.BRepGProp import BRepGProp
    from OCP.GeomAbs import GeomAbs_Cylinder, GeomAbs_Plane
    from OCP.GProp import GProp_GProps
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    shape = _load()

    bb = Bnd_Box()
    BRepBndLib.Add_s(shape, bb)
    x0, y0, z0, x1, y1, z1 = bb.Get()
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)

    out: Dict[str, Any] = {
        "source": str(STEP.relative_to(REPO)),
        "envelope_mm": [round(x1 - x0, 3), round(y1 - y0, 3), round(z1 - z0, 3)],
        "envelope_min_mm": [round(x0, 3), round(y0, 3), round(z0, 3)],
        "envelope_max_mm": [round(x1, 3), round(y1, 3), round(z1, 3)],
        "volume_mm3": round(props.Mass(), 1),
        "disc_faces": [],      # Φ20 端面盘（法向 ±Z 且外接框 20×20）
        "holes": [],           # 轴向 Z 的圆柱孔，按 (半径, 深) 归组
    }

    exp = TopExp_Explorer(shape, TopAbs_FACE)
    groups: Dict[Any, List[Dict[str, Any]]] = defaultdict(list)
    while exp.More():
        face = TopoDS.Face_s(exp.Current())
        surf = BRepAdaptor_Surface(face, True)
        kind = surf.GetType()
        fbb = Bnd_Box()
        BRepBndLib.Add_s(face, fbb)
        fx0, fy0, fz0, fx1, fy1, fz1 = fbb.Get()

        if kind == GeomAbs_Plane:
            n = surf.Plane().Axis().Direction()
            if abs(n.Z()) > 0.99:
                dx, dy = fx1 - fx0, fy1 - fy0
                if abs(dx - 20) < 0.5 and abs(dy - 20) < 0.5:
                    fp = GProp_GProps()
                    BRepGProp.SurfaceProperties_s(face, fp)
                    out["disc_faces"].append({
                        "z": round(fz0, 3),
                        "center_xy": [round((fx0 + fx1) / 2, 3),
                                      round((fy0 + fy1) / 2, 3)],
                        "area_mm2": round(fp.Mass(), 1),
                    })
        elif kind == GeomAbs_Cylinder:
            cyl = surf.Cylinder()
            axis = cyl.Axis()
            d = axis.Direction()
            if abs(d.Z()) > 0.99:          # 只看轴向 Z 的孔
                loc = axis.Location()
                groups[(round(cyl.Radius(), 3), round(fz1 - fz0, 2))].append({
                    "x": round(loc.X(), 3), "y": round(loc.Y(), 3),
                    "z_span": [round(fz0, 3), round(fz1, 3)],
                })
        exp.Next()

    for (radius, depth), items in sorted(groups.items()):
        xs = sorted({i["x"] for i in items})
        ys = sorted({i["y"] for i in items})
        out["holes"].append({
            "dia_mm": round(2 * radius, 2),
            "depth_mm": depth,
            "count": len(items),
            "unique_x": xs,
            "unique_y": ys,
            "pitch_x_mm": round(max(xs) - min(xs), 3) if len(xs) > 1 else None,
            "pitch_y_mm": round(max(ys) - min(ys), 3) if len(ys) > 1 else None,
            "positions": sorted(items, key=lambda i: (i["x"], i["y"], i["z_span"][0])),
        })

    out["disc_faces"].sort(key=lambda f: f["z"])
    return out


def report(m: Dict[str, Any]) -> str:
    L: List[str] = []
    L.append(f"模型：{m['source']}")
    L.append(f"包络：{m['envelope_mm'][0]} × {m['envelope_mm'][1]} × "
             f"{m['envelope_mm'][2]} mm    体积 {m['volume_mm3']} mm³")
    L.append("")
    L.append("== Φ20 端面盘（法向 ±Z，外接框 20×20）==")
    for f in m["disc_faces"]:
        L.append(f"   z = {f['z']:8.3f}   圆心 = {f['center_xy']}   "
                 f"面积 {f['area_mm2']} mm²")
    L.append("")
    L.append("== 轴向 Z 的圆柱孔 ==")
    for h in m["holes"]:
        L.append(f"   Φ{h['dia_mm']:<5} 深 {h['depth_mm']:<6} ×{h['count']:<3}"
                 f" X间距 {h['pitch_x_mm']}  Y间距 {h['pitch_y_mm']}")
        for p in h["positions"]:
            L.append(f"        ({p['x']:8.3f}, {p['y']:8.3f})  z{p['z_span']}")
    return "\n".join(L)


def main(argv: List[str]) -> int:
    m = measure()
    if "--json" in argv:
        print(json.dumps(m, ensure_ascii=False, indent=2))
    else:
        print(report(m))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
