#!/usr/bin/env python3
"""从真实 CAD 实体出图：3D 渲染图（着色）+ 工程图（HLR 线框）。

为什么自己写渲染器：CadQuery 的栅格渲染依赖 VTK（另一个 165 MB 级依赖），
而本层只需要"看清结构"级别的图。这里把 B-rep 三角化后用**画家算法**
投影，输出 SVG（矢量，可进 PPT/AI）与 PNG（位图，可进文档）。

工程图部分用 OpenCASCADE 的 **HLR**（隐藏线消除）直接投影：
    `cq.exporters.export(shape, "x.svg", opt={"projectionDir": ...})`
这是真正的工程制图输出（可见线 + 虚线），不是渲染。

用法：
    .venv-cad/bin/python design/cad/render3d.py --all
产出：
    out/renders/06_CAD等轴测.{svg,png}
    out/renders/07_CAD正视.{svg,png}
    out/renders/08_CAD侧视.{svg,png}
    out/renders/09_CAD背面等轴测.{svg,png}
    out/drawings/10_CAD三视图.svg
    out/drawings/11_关节笼-零件图.svg
    out/drawings/12_连杆叉-零件图.svg
"""
from __future__ import annotations

import json
import math
import struct
import sys
import zlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))

import cadquery as cq
import numpy as np

import assembly as A
import skeleton as sk

OUT = HERE / "out"
RENDERS = OUT / "renders"
DRAWINGS = OUT / "drawings"

# 配色（与 ppt/design.py 的墨蓝体系一致）
COLORS = {
    "bulk":    (0.55, 0.62, 0.72),   # 结构框架：钢蓝灰
    "cage":    (0.13, 0.30, 0.52),   # 关节笼：墨蓝
    "fork":    (0.20, 0.45, 0.68),   # 连杆叉：中蓝
    "adapter": (0.30, 0.55, 0.55),   # 转接块：青
    "servo":   (0.25, 0.27, 0.32),   # 舵机：深灰
    "elec":    (0.85, 0.55, 0.20),   # 电子件：橙
    "tube":    (0.45, 0.58, 0.45),   # 连杆管：灰绿
}
BG = (1.0, 1.0, 1.0)


# --------------------------------------------------------------------------
# PNG 写出（不依赖 Pillow）
# --------------------------------------------------------------------------
def write_png(path: Path, rgb: np.ndarray) -> None:
    h, w, _ = rgb.shape
    raw = b"".join(b"\x00" + rgb[y].tobytes() for y in range(h))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw, 6))
           + chunk(b"IEND", b""))
    path.write_bytes(png)


# --------------------------------------------------------------------------
# 三角化 + 投影
# --------------------------------------------------------------------------
def tessellate(items: Sequence[Tuple[str, cq.Workplane]], tol: float = 0.7
               ) -> List[Tuple[str, np.ndarray, np.ndarray]]:
    """把每件三角化：返回 [(名称, 顶点 (N,3), 三角形 (M,3) 索引)]。"""
    out = []
    for name, wp in items:
        verts: List[Tuple[float, float, float]] = []
        tris: List[Tuple[int, int, int]] = []
        for solid in wp.solids().vals():
            try:
                vs, fs = solid.tessellate(tol)
            except Exception:  # noqa: BLE001
                continue
            base = len(verts)
            for v in vs:
                verts.append((v.x, v.y, v.z))
            for f in fs:
                tris.append((base + f[0], base + f[1], base + f[2]))
        if tris:
            out.append((name, np.array(verts, dtype=float),
                        np.array(tris, dtype=np.int32)))
    return out


def kind_of(name: str) -> str:
    if name.startswith("servo__"):
        return "servo"
    if name.startswith("cage__"):
        return "cage"
    if name.startswith("fork__"):
        return "fork"
    if name.startswith("elec__"):
        return "elec"
    if name.endswith("compact_adapter"):
        return "adapter"
    if "limb_tube" in name:
        return "tube"
    return "bulk"


def project(verts: np.ndarray, cam: np.ndarray, up: np.ndarray
            ) -> Tuple[np.ndarray, np.ndarray]:
    """正交投影：返回屏幕坐标 (N,2) 与深度 (N,)。"""
    fwd = cam / np.linalg.norm(cam)
    right = np.cross(fwd, up)
    right /= np.linalg.norm(right)
    true_up = np.cross(right, fwd)
    x = verts @ right
    y = verts @ true_up
    z = verts @ fwd                      # 越大越靠近相机
    return np.stack([x, y], axis=1), z


def render_svg(meshes, cam, up, path: Path, width: int = 1400,
               height: int = 1100, margin: int = 40) -> None:
    """画家算法：按深度排序三角形，投影填色输出 SVG。"""
    all_xy, all_z = [], []
    proj = []
    for name, verts, tris in meshes:
        xy, z = project(verts, cam, up)
        proj.append((name, verts, tris, xy, z))
        all_xy.append(xy)
    P = np.concatenate([p[3] for p in proj])
    lo, hi = P.min(axis=0), P.max(axis=0)
    span = np.maximum(hi - lo, 1e-6)
    scale = min((width - 2 * margin) / span[0], (height - 2 * margin) / span[1])

    light = np.array([0.35, -0.55, 0.75])
    light /= np.linalg.norm(light)

    # 收集所有三角形（世界坐标法向 > 屏幕坐标 > 深度）
    ox = (width - span[0] * scale) / 2.0 - lo[0] * scale
    oy = (height - span[1] * scale) / 2.0
    polys = []
    # 零件级排序：零件之间按质心深度从远到近；零件内部再按面深度
    proj_sorted = sorted(
        proj, key=lambda p: float(p[4].mean()))
    for name, verts, tris, xy, z in proj_sorted:
        k = kind_of(name)
        base = np.array(COLORS[k])
        for tri in tris:
            idx = tri
            v0, v1, v2 = verts[idx[0]], verts[idx[1]], verts[idx[2]]
            n = np.cross(v1 - v0, v2 - v0)
            ln = np.linalg.norm(n)
            if ln < 1e-12:
                continue
            n = n / ln
            if np.dot(n, cam) < 0:       # 背面剔除
                continue
            shade = 0.42 + 0.58 * max(0.0, float(np.dot(n, light)))
            col = np.clip(base * shade, 0, 1)
            sx = [xy[i][0] * scale + ox for i in idx]
            sy = [(hi[1] - xy[i][1]) * scale + oy for i in idx]
            depth = float(z[idx[0]] + z[idx[1]] + z[idx[2]]) / 3.0
            hexc = "#%02x%02x%02x" % tuple(int(c * 255) for c in col)
            polys.append((depth, sx, sy, hexc))

    polys.sort(key=lambda p: p[0])
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
             f'height="{height}" viewBox="0 0 {width} {height}">',
             f'<rect width="{width}" height="{height}" fill="#ffffff"/>']
    for _, sx, sy, hexc in polys:
        pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(sx, sy))
        parts.append(f'<polygon points="{pts}" fill="{hexc}" '
                     f'stroke="{hexc}" stroke-width="0.35"/>')
    parts.append("</svg>")
    path.write_text("\n".join(parts), encoding="utf-8")


def render_png(meshes, cam, up, path: Path, width: int = 1100,
               height: int = 900, margin: int = 30) -> None:
    """画家算法栅格化：全局按深度从远到近填三角形，近的覆盖远的。

    不用 z-buffer 是有意的：零件之间基本不互相穿插，画家算法在这种
    "多实体装配"场景下更简单也更不容易出错；代价是深度交错的零件
    （如舵机插进笼子里）可能有一两处像素级顺序错误。
    """
    cam = cam / np.linalg.norm(cam)
    proj = []
    for name, verts, tris in meshes:
        xy, z = project(verts, cam, up)
        proj.append((name, verts, tris, xy, z))
    P = np.concatenate([p[3] for p in proj])
    lo, hi = P.min(axis=0), P.max(axis=0)
    span = np.maximum(hi - lo, 1e-6)
    scale = min((width - 2 * margin) / span[0], (height - 2 * margin) / span[1])

    light = np.array([0.35, -0.55, 0.75])
    light /= np.linalg.norm(light)

    ox = (width - span[0] * scale) / 2.0 - lo[0] * scale
    oy = (height - span[1] * scale) / 2.0
    # 收集全部三角形：先按零件质心深度排零件，再在零件内按面深度排
    tris_all = []
    proj_sorted = sorted(proj, key=lambda p: float(p[4].mean()))
    for pi, (name, verts, tris, xy, z) in enumerate(proj_sorted):
        base = np.array(COLORS[kind_of(name)])
        sx = xy[:, 0] * scale + ox
        sy = (hi[1] - xy[:, 1]) * scale + oy
        for tri in tris:
            v0, v1, v2 = verts[tri[0]], verts[tri[1]], verts[tri[2]]
            n = np.cross(v1 - v0, v2 - v0)
            ln = np.linalg.norm(n)
            if ln < 1e-12:
                continue
            n = n / ln
            if np.dot(n, cam) < 0.02:          # 背面剔除（留一点余量防漏）
                continue
            depth = float(z[tri[0]] + z[tri[1]] + z[tri[2]]) / 3.0
            shade = 0.42 + 0.58 * max(0.0, float(np.dot(n, light)))
            col = np.clip(base * shade * 255, 0, 255).astype(np.uint8)
            tris_all.append((pi, depth, sx[tri], sy[tri],
                             (col[0], col[1], col[2])))
    tris_all.sort(key=lambda t: (t[0], t[1]))
    print(f"    可绘制三角形 {len(tris_all)} 个")

    img = np.ones((height, width, 3), dtype=np.uint8) * 255
    for _pi, depth, tx, ty, col in tris_all:
        minx = int(max(0, np.floor(tx.min())))
        maxx = int(min(width - 1, np.ceil(tx.max())))
        miny = int(max(0, np.floor(ty.min())))
        maxy = int(min(height - 1, np.ceil(ty.max())))
        if maxx < minx or maxy < miny:
            continue
        xs = np.arange(minx, maxx + 1) + 0.5
        ys = np.arange(miny, maxy + 1) + 0.5
        gx, gy = np.meshgrid(xs, ys)
        ax, ay = float(tx[0]), float(ty[0])
        bx, by = float(tx[1]), float(ty[1])
        cx, cy = float(tx[2]), float(ty[2])
        d = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(d) < 1e-12:
            # 退化三角形：按 1px 线补一个点，避免结构出现空洞
            px, py = int(round(ax)), int(round(ay))
            if 0 <= px < width and 0 <= py < height:
                img[py, px] = col
            continue
        w0 = ((by - cy) * (gx - cx) + (cx - bx) * (gy - cy)) / d
        w1 = ((cy - ay) * (gx - cx) + (ax - cx) * (gy - cy)) / d
        w2 = 1.0 - w0 - w1
        eps = -1e-9
        mask = (w0 >= eps) & (w1 >= eps) & (w2 >= eps)
        if mask.any():
            img[miny:maxy + 1, minx:maxx + 1][mask] = col
    write_png(path, img)


# --------------------------------------------------------------------------
# 工程图（HLR）
# --------------------------------------------------------------------------
def hlr_drawing(shape: cq.Workplane, path: Path, direction: Sequence[float],
                width: int = 1200, height: int = 1200,
                show_hidden: bool = True) -> None:
    opt = {
        "width": width, "height": height,
        "marginLeft": 40, "marginTop": 40,
        "projectionDir": tuple(direction),
        "showAxes": False,
        "showHidden": show_hidden,
        "strokeWidth": 0.35,
        "strokeColor": (10, 37, 64),
        "hiddenColor": (150, 165, 185),
    }
    cq.exporters.export(shape, str(path), opt=opt)


def main(argv: Optional[List[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="CAD 出图：渲染图 + 工程图")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--tol", type=float, default=0.7)
    args = ap.parse_args(argv)

    RENDERS.mkdir(parents=True, exist_ok=True)
    DRAWINGS.mkdir(parents=True, exist_ok=True)

    kin = A.Kin(A.DESIGN / "atri.urdf")
    placements = json.loads((A.DESIGN / "placements.json").read_text(encoding="utf-8"))
    items, log = A.build_assembly(kin, placements)
    print(f"装配件 {len(items)} 个，开始三角化（tol={args.tol}）…")
    meshes = tessellate(items, tol=args.tol)
    ntri = sum(len(t[2]) for t in meshes)
    print(f"三角面片 {ntri} 个")

    views = {
        "06_CAD等轴测": (np.array([1.0, -1.0, 0.62]), np.array([0.0, 0.0, 1.0])),
        "07_CAD正视":   (np.array([1.0, 0.0, 0.02]), np.array([0.0, 0.0, 1.0])),
        "08_CAD侧视":   (np.array([0.0, -1.0, 0.02]), np.array([0.0, 0.0, 1.0])),
        "09_CAD背面等轴测": (np.array([-1.0, 1.0, 0.62]), np.array([0.0, 0.0, 1.0])),
    }
    for name, (cam, up) in views.items():
        render_svg(meshes, cam, up, RENDERS / f"{name}.svg")
        render_png(meshes, cam, up, RENDERS / f"{name}.png")
        print(f"  渲染 {name}.svg/.png")

    # --- 工程图：整机三视图 ---
    comp = cq.Workplane("XY").newObject(
        [cq.Compound.makeCompound([w.val() for _, w in items])])
    for tag, d in {"front": (0, -1, 0), "side": (1, 0, 0), "top": (0, 0, 1)}.items():
        hlr_drawing(comp, DRAWINGS / f"10_CAD三视图-{tag}.svg", d)
    print("  工程图 10_CAD三视图-{front,side,top}.svg")

    # --- 工程图：关键零件的零件图 ---
    for part, builder in [("11_关节笼", lambda: sk.joint_cage()),
                          ("12_连杆叉", lambda: sk.limb_fork()),
                          ("13_紧凑转接块", lambda: sk.compact_adapter()),
                          ("14_骨盆框架", lambda: sk.pelvis_frame()),
                          ("15_足板", lambda: sk.foot_plate())]:
        hlr_drawing(builder(), DRAWINGS / f"{part}-零件图.svg", (1, -1, 0.6))
        print(f"  零件图 {part}-零件图.svg")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
