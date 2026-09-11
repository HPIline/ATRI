"""厂商零件几何实测（T1/T2 核验工具）。

用途：把厂商/开源项目提供的 STEP 里的**几何事实**提取出来，
用于核验"凭世界知识给的参数"是否与真实零件一致。

    .venv-cad/bin/python design/cad/tools/measure_vendor.py \
        design/cad/vendor/so-arm100/STS3215_03a.step

输出：包络、体积、按（轴方向 + 半径）分组的圆柱面清单、按法向分组的平面清单。
**只报几何事实，不做装配判断**；语义（哪个孔是干什么的）由人结合配合件推断。
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

import cadquery as cq
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.GeomAbs import GeomAbs_SurfaceType
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps


def load(path: Path):
    wp = cq.importers.importStep(str(path))
    return wp.val() if hasattr(wp, "val") else wp


def _axis_name(v) -> str:
    """把方向向量归一成 +X/-X/+Y/-Y/+Z/-Z。"""
    comps = [("X", v.X()), ("Y", v.Y()), ("Z", v.Z())]
    name, val = max(comps, key=lambda c: abs(c[1]))
    return ("+" if val > 0 else "-") + name


def _round(v: float, nd: int = 2) -> float:
    return round(v + 0.0, nd)


def face_center(face):
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(face.wrapped, props)
    c = props.CentreOfMass()
    return c.X(), c.Y(), c.Z()


def cylinders(shape):
    """圆柱面清单。

    kind: bore = 材料在外、面朝轴心（孔/内腔/内螺纹）
          shaft = 材料在内、面朝外（轴/凸台/柱）
    判别依据：OCC 中 face 取向 REVERSED 表示实体法向与曲面法向相反；
    圆柱面法向天生朝外，故 REVERSED ⇒ 孔。
    """
    out = []
    for f in shape.Faces():
        s = BRepAdaptor_Surface(f.wrapped)
        if s.GetType() != GeomAbs_SurfaceType.GeomAbs_Cylinder:
            continue
        cyl = s.Cylinder()
        r = cyl.Radius()
        ax = cyl.Axis()
        loc, d = ax.Location(), ax.Direction()
        axis = _axis_name(d)
        bb = f.BoundingBox()
        spans = {"X": (bb.xmin, bb.xmax), "Y": (bb.ymin, bb.ymax), "Z": (bb.zmin, bb.zmax)}
        a = axis[-1]
        along = spans[a]
        area = f.Area()
        length = along[1] - along[0]
        # 圆弧张角：A = r·θ·L
        theta = area / (r * length) if r > 0 and length > 0 else 0.0
        out.append({
            "axis": axis,
            "r": r,
            "dia": 2 * r,
            "along_lo": along[0], "along_hi": along[1],
            "len": length,
            "pos": (loc.X(), loc.Y(), loc.Z()),
            "area": area,
            "kind": "bore" if str(f.wrapped.Orientation()) == "TopAbs_REVERSED" else "shaft",
            "arc_deg": min(theta, 2 * 3.141592653589793) * 180.0 / 3.141592653589793,
        })
    return out


def planes(shape, want_normal=None):
    """按法向列平面：[(normal, offset_along_normal, area, center)]"""
    out = []
    for f in shape.Faces():
        s = BRepAdaptor_Surface(f.wrapped)
        if s.GetType() != GeomAbs_SurfaceType.GeomAbs_Plane:
            continue
        pln = s.Plane()
        ax = pln.Axis()
        n = ax.Direction()
        normal = _axis_name(n)
        if want_normal and normal != want_normal:
            continue
        loc = ax.Location()
        offset = loc.X() * n.X() + loc.Y() * n.Y() + loc.Z() * n.Z()
        cx, cy, cz = face_center(f)
        out.append({"normal": normal, "offset": offset, "area": f.Area(),
                    "center": (cx, cy, cz)})
    return out


def group_cylinders(cyls, tol_pos=0.05):
    """按（轴 + 半径 + 垂直轴位置）分组 -> 孔位族。"""
    g = defaultdict(list)
    for c in cyls:
        a = c["axis"][-1]
        perp = [k for k in "XYZ" if k != a]
        idx = {"X": 0, "Y": 1, "Z": 2}
        key = (c["axis"], round(c["dia"], 2),
               round(c["pos"][idx[perp[0]]] / tol_pos) * tol_pos,
               round(c["pos"][idx[perp[1]]] / tol_pos) * tol_pos)
        g[key].append(c)
    return g


def report(path: Path) -> str:
    shape = load(path)
    bb = shape.BoundingBox()
    L = [f"# 实测报告：{path.name}", "",
         f"体积: {shape.Volume():.1f} mm³", "",
         "## 包络（mm）", "",
         "| 轴 | min | max | 尺寸 |", "|---|---|---|---|",
         f"| X | {bb.xmin:.2f} | {bb.xmax:.2f} | {bb.xlen:.2f} |",
         f"| Y | {bb.ymin:.2f} | {bb.ymax:.2f} | {bb.ylen:.2f} |",
         f"| Z | {bb.zmin:.2f} | {bb.zmax:.2f} | {bb.zlen:.2f} |", ""]

    L += ["## 圆柱面（按 轴/直径/轴心位置 分组）", "",
          "| 轴 | Φ | 轴心(垂直轴两坐标) | 面数 | 沿轴范围 | 深度 | 单个面积 |",
          "|---|---|---|---|---|---|---|"]
    for key, items in sorted(group_cylinders(cylinders(shape)).items(),
                             key=lambda kv: (-kv[0][1], kv[0][0])):
        axis, dia, p0, p1 = key
        a = axis[-1]
        perp = [k for k in "XYZ" if k != a]
        lo = min(i["along_lo"] for i in items)
        hi = max(i["along_hi"] for i in items)
        L.append(f"| {axis} | {dia:.2f} | {perp[0]}={p0:.2f}, {perp[1]}={p1:.2f} | "
                 f"{len(items)} | {lo:.2f} ~ {hi:.2f} | {hi - lo:.2f} | "
                 f"{items[0]['area']:.1f} |")

    L += ["", "## 圆柱面逐面明细（bore=孔/内腔，shaft=轴/凸台）", "",
          "| 轴 | Φ | 类型 | 轴心(垂直轴两坐标) | 沿轴范围 | 长 | 张角 | 面积 |",
          "|---|---|---|---|---|---|---|---|"]
    idx = {"X": 0, "Y": 1, "Z": 2}
    for c in sorted(cylinders(shape), key=lambda c: (c["axis"][-1], c["dia"], c["pos"])):
        a = c["axis"][-1]
        perp = [k for k in "XYZ" if k != a]
        L.append(f"| {c['axis']} | {c['dia']:.2f} | {c['kind']} | "
                 f"{perp[0]}={c['pos'][idx[perp[0]]]:.2f}, "
                 f"{perp[1]}={c['pos'][idx[perp[1]]]:.2f} | "
                 f"{c['along_lo']:.2f} ~ {c['along_hi']:.2f} | {c['len']:.2f} | "
                 f"{c['arc_deg']:.0f}° | {c['area']:.1f} |")

    L += ["", "## 平面（按法向 × 位置）", "",
          "| 法向 | 平面偏移 | 面积 | 面心 |", "|---|---|---|---|"]
    pg = defaultdict(list)
    for p in planes(shape):
        pg[(p["normal"], round(p["offset"], 2))].append(p)
    for (normal, off), items in sorted(pg.items(), key=lambda kv: (kv[0][0], -kv[0][1])):
        total = sum(i["area"] for i in items)
        c = items[0]["center"]
        L.append(f"| {normal} | {off:.2f} | {total:.1f} | "
                 f"({c[0]:.2f}, {c[1]:.2f}, {c[2]:.2f}) |")
    return "\n".join(L)


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    for arg in argv[1:]:
        p = Path(arg)
        if not p.exists():
            print(f"✗ 找不到 {p}", file=sys.stderr)
            return 1
        print(report(p))
        print("\n" + "=" * 78 + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
