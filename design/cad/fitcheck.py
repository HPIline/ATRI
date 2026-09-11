"""装配几何判定原语：干涉体积 / 最小距离 / 包围盒重叠。

**为什么单独成模块**：`assembly.py`（装配时校验）、`audit_assembly.py`（整机体检）、
`fit_clocking.py`（钟点求解）三处都要用同一套判定。判定逻辑一旦各写一份，
就会出现"体检说没问题、装配时放行"这种最坏情况——所以只留这一份实现。
"""
from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple

import cadquery as cq
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps


def bbox_of(shape: cq.Workplane):
    return shape.val().BoundingBox()


def boxes_overlap(b1, b2, pad: float = 0.0) -> bool:
    """两个包围盒是否相交（`pad>0` 时放大判定，用于"接近"查询）。"""
    return not (b1.xmax + pad < b2.xmin or b2.xmax + pad < b1.xmin or
                b1.ymax + pad < b2.ymin or b2.ymax + pad < b1.ymin or
                b1.zmax + pad < b2.zmin or b2.zmax + pad < b1.zmin)


def common_volume(a: cq.Workplane, b: cq.Workplane) -> float:
    """两实体的相交体积（mm³）。"""
    op = BRepAlgoAPI_Common(a.val().wrapped, b.val().wrapped)
    op.Build()
    if not op.IsDone():
        return 0.0
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(op.Shape(), props)
    return abs(props.Mass())


def distance(a: cq.Workplane, b: cq.Workplane) -> float:
    """两实体的最小距离（mm）；分离时为正。"""
    d = BRepExtrema_DistShapeShape(a.val().wrapped, b.val().wrapped)
    d.Perform()
    return d.Value() if d.IsDone() else 1e9


def verdict(overlap_mm3: float, frac: float) -> str:
    """按"重合率 + 绝对体积"给出性质判定。

    工程含义：
        重合率 ≥30% 或体积 ≥5000 mm³ ⇒ 两个零件被指派到同一块空间（**摆放错误**），
        改尺寸无解；5–30% ⇒ 让位不足；其余为局部干涉。
    """
    if frac >= 0.30 or overlap_mm3 >= 5000.0:
        return "❌ 摆放错误"
    if frac >= 0.05 or overlap_mm3 >= 500.0:
        return "⚠️ 让位不足"
    return "· 局部干涉"


def overlap_report(items: Sequence[Tuple[str, cq.Workplane]],
                   threshold: float = 1.0,
                   shapes: Sequence[cq.Workplane] | None = None,
                   boxes: Sequence[Any] | None = None,
                   ) -> List[Dict[str, Any]]:
    """两两求交，返回超过阈值的干涉清单（按体积降序）。

    返回项：{a, b, vol, frac, smaller_vol, verdict}
    """
    names = [n for n, _ in items]
    shapes = list(shapes) if shapes is not None else [w for _, w in items]
    boxes = list(boxes) if boxes is not None else [bbox_of(w) for w in shapes]
    vols = [w.val().Volume() for w in shapes]

    out: List[Dict[str, Any]] = []
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if not boxes_overlap(boxes[i], boxes[j]):
                continue
            v = common_volume(shapes[i], shapes[j])
            if v <= threshold:
                continue
            smaller = max(min(vols[i], vols[j]), 1e-9)
            frac = v / smaller
            out.append({"a": names[i], "b": names[j], "vol": v, "frac": frac,
                        "smaller_vol": smaller, "verdict": verdict(v, frac)})
    out.sort(key=lambda d: -d["vol"])
    return out
