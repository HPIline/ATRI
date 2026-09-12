#!/usr/bin/env python3
"""交互式 3D 查看器（CadQuery / VTK）：自由旋转、缩放、平移。

**不需要单独 pip install vtk** —— `cadquery-ocp` 自带 vtkmodules（见
`design/cad/交互预览-工具链.md` §3 的踩坑记录：另装 `vtk` 包会把两套 VTK
塞进同一个 `vtkmodules/` 目录，表现为 "Initialization failed for
vtkCommonTransforms, not compatible with vtkmodules.vtkCommonCore"）。

用法：
    # 交互窗口（本机 GUI）
    .venv-cad/bin/python design/cad/tools/view.py --assembly
    .venv-cad/bin/python design/cad/tools/view.py --part limb_fork --edges
    .venv-cad/bin/python design/cad/tools/view.py --parts joint_cage limb_fork

    # 无头截图（不需要 GUI，可用于自检/CI/出图）
    .venv-cad/bin/python design/cad/tools/view.py --assembly --screenshot out/view/整机.png

窗口里的操作（VTK trackball）：
    左键拖拽 = 旋转　中键/Shift+左键 = 平移　滚轮 = 缩放
    e = 切换边线　w = 线框　s = 曲面　r = 重置视角　q = 退出
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, List, Optional, Sequence, Tuple

CAD = Path(__file__).resolve().parent.parent  # design/cad/
HERE = CAD  # 产物仍写到 cad/out，不跟脚本下沉
REPO = HERE.parent.parent
sys.path.insert(0, str(CAD))
sys.path.insert(0, str(CAD / "tools"))

import cadquery as cq

import assembly as A
import render3d as R
import skeleton as sk

OUT = HERE / "out"


def build_assembly_colored(kin: A.Kin, placements: dict) -> cq.Assembly:
    """把整机装成一个带颜色的 CadQuery Assembly（按类别配色）。"""
    items, _ = A.build_assembly(kin, placements)
    asm = cq.Assembly(name="ATRI")
    for name, wp in items:
        c = R.COLORS[R.kind_of(name)]
        asm.add(wp.val(), name=name,
                color=cq.Color(c[0], c[1], c[2]))
    return asm


def offscreen(asm: cq.Assembly, path: Path, size: Tuple[int, int] = (1500, 1080),
              edges: bool = False) -> None:
    """把装配离屏渲染成 PNG（不需要 GUI，可用于自动化自检与出图）。"""
    import vtkmodules.vtkRenderingOpenGL2  # noqa: F401  注册 OpenGL 后端
    import vtkmodules.vtkInteractionStyle  # noqa: F401
    from cadquery.vis import toVTK
    from vtkmodules.vtkIOImage import vtkPNGWriter
    from vtkmodules.vtkRenderingCore import (vtkRenderWindow,
                                             vtkWindowToImageFilter)

    renderer = toVTK(asm, tolerance=0.35, angularTolerance=0.25)
    for act in renderer.GetActors():
        if edges:
            act.GetProperty().EdgeVisibilityOn()
    renderer.SetBackground(0.965, 0.973, 0.984)
    renderer.GradientBackgroundOff()

    win = vtkRenderWindow()
    win.SetOffScreenRendering(1)
    win.AddRenderer(renderer)
    win.SetSize(*size)

    renderer.ResetCamera()                 # 先取合理的焦点与距离
    cam = renderer.GetActiveCamera()
    fp = cam.GetFocalPoint()
    d = cam.GetDistance()
    # 本模型 Z 轴向上；VTK 默认 +Y 向上会让整机"躺着"，所以要显式摆机位
    cam.SetViewUp(0, 0, 1)
    cam.SetPosition(fp[0] + 0.78 * d, fp[1] - 0.78 * d, fp[2] + 0.60 * d)
    renderer.ResetCameraClippingRange()
    win.Render()

    w2i = vtkWindowToImageFilter()
    w2i.SetInput(win)
    w2i.SetScale(1)
    w2i.Update()
    path.parent.mkdir(parents=True, exist_ok=True)
    w = vtkPNGWriter()
    w.SetFileName(str(path))
    w.SetInputConnection(w2i.GetOutputPort())
    w.Write()
    win.Finalize()


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="A.T.R.I. 交互式 3D 查看器")
    ap.add_argument("--assembly", action="store_true", help="看整机装配")
    ap.add_argument("--part", type=str, default=None, help="看单个骨架零件")
    ap.add_argument("--parts", nargs="*", default=None, help="看多个零件")
    ap.add_argument("--edges", action="store_true", help="显示边线")
    ap.add_argument("--tolerance", type=float, default=0.4, help="网格容差 mm")
    ap.add_argument("--screenshot", type=str, default=None,
                    help="离屏渲染到 PNG（不开窗口，用于自检）")
    args = ap.parse_args(argv)

    if args.assembly:
        kin = A.Kin(A.DESIGN / "atri.urdf")
        placements = json.loads(
            (A.DESIGN / "placements.json").read_text(encoding="utf-8"))
        items, log = A.build_assembly(kin, placements)
        bad = [l for l in log if not l.get("ok")]
        print(f"整机 {len(items)} 个零件" + (f"（{len(bad)} 个失败）" if bad else ""))
        asm = cq.Assembly(name="ATRI")
        for name, wp in items:
            c = R.COLORS[R.kind_of(name)]
            asm.add(wp.val(), name=name, color=cq.Color(c[0], c[1], c[2]))
        title = "A.T.R.I. 整机装配"
    else:
        names = args.parts or ([args.part] if args.part else ["joint_cage"])
        asm = cq.Assembly(name="ATRI")
        for n in names:
            c = R.COLORS[R.kind_of(n + "__")]
            asm.add(sk.build(n).val(), name=n, color=cq.Color(c[0], c[1], c[2]))
        title = "ATRI · " + " / ".join(names)

    if args.screenshot:
        path = Path(args.screenshot)
        offscreen(asm, path, edges=args.edges)
        print(f"已离屏渲染 {path}（{path.stat().st_size/1024:.0f} KB）")
        return 0

    from cadquery.vis import show
    print(f"打开窗口：{title}（左键旋转 / 滚轮缩放 / 中键平移 / e 边线 / q 退出）")
    show(asm, tolerance=args.tolerance, edges=args.edges, title=title)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
