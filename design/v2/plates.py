"""激光切割铝板定义。原点 = 关节轴或零件几何中心，单位 mm。"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Sequence, Tuple

from .profile import CAD_INTERFACE, K, MATERIALS, SERVO

Point = Tuple[float, float]


@dataclass
class Hole:
    x: float
    y: float
    d: float
    kind: str


@dataclass
class Plate:
    name: str
    drawing_no: str
    thickness_mm: float
    material: str
    qty: int
    outline: List[Point]
    holes: List[Hole]
    note: str = ""
    layer: str = "1.5mm"


def _rect(w: float, h: float, r: float = 2.0) -> List[Point]:
    """中心矩形，角微倒圆用折线近似。"""
    hw, hh = w / 2.0, h / 2.0
    r = min(r, hw, hh)
    return [
        (-hw + r, -hh), (hw - r, -hh), (hw, -hh + r), (hw, hh - r),
        (hw - r, hh), (-hw + r, hh), (-hw, hh - r), (-hw, -hh + r),
    ]


def _round_rect(w: float, h: float, r: float, n: int = 4) -> List[Point]:
    hw, hh = w / 2.0, h / 2.0
    r = min(r, hw, hh)
    pts: List[Point] = []
    corners = [
        (hw - r, hh - r, 0.0),
        (-hw + r, hh - r, math.pi / 2),
        (-hw + r, -hh + r, math.pi),
        (hw - r, -hh + r, 3 * math.pi / 2),
    ]
    for cx, cy, a0 in corners:
        for i in range(n + 1):
            a = a0 + (math.pi / 2) * (i / n)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def _circle(radius: float, n: int = 24) -> List[Point]:
    return [
        (radius * math.cos(2 * math.pi * i / n), radius * math.sin(2 * math.pi * i / n))
        for i in range(n)
    ]


def _pcd14_m3() -> List[Hole]:
    s = SERVO["horn_hole_square_mm"] / 2.0
    d = SERVO["horn_clear_mm"]
    return [
        Hole(s, s, d, "horn_M3_clear"),
        Hole(s, -s, d, "horn_M3_clear"),
        Hole(-s, s, d, "horn_M3_clear"),
        Hole(-s, -s, d, "horn_M3_clear"),
    ]


def _c_arm(length: float, width: float = 18.0) -> Tuple[List[Point], List[Hole]]:
    """两端各一组 PCD14，中心距 = length。"""
    outline = _round_rect(length + 28.0, width, 8.0, n=6)
    holes: List[Hole] = []
    for sign in (-1.0, 1.0):
        cx = sign * length / 2.0
        for h in _pcd14_m3():
            holes.append(Hole(h.x + cx, h.y, h.d, h.kind))
        holes.append(Hole(cx, 0.0, 6.2, "center_clear"))
    return outline, holes


def all_plates() -> List[Plate]:
    t15 = MATERIALS["6061-T6"]["t_mm"]
    t20 = MATERIALS["6061-T6"]["foot_t_mm"]
    plates: List[Plate] = []

    idle_holes = _pcd14_m3() + [
        Hole(0.0, 0.0, 10.2, "bearing_MF106"),
        Hole(16.0, 12.0, 3.2, "M3_clear"),
        Hole(16.0, -12.0, 3.2, "M3_clear"),
    ]
    plates.append(Plate(
        name="IDLE-PLATE",
        drawing_no="ATRI-v2-P01",
        thickness_mm=t15,
        material="6061-T6",
        qty=17,
        outline=[(-20,-16),(20,-16),(20,16),(-20,16),
                 (-20,CAD_INTERFACE["idle_connector_notch_half_h_mm"]),
                 (CAD_INTERFACE["idle_connector_notch_x_mm"],CAD_INTERFACE["idle_connector_notch_half_h_mm"]),
                 (CAD_INTERFACE["idle_connector_notch_x_mm"],-CAD_INTERFACE["idle_connector_notch_half_h_mm"]),
                 (-20,-CAD_INTERFACE["idle_connector_notch_half_h_mm"])],
        holes=idle_holes,
        note="待重设计：副轴支撑板，4×M3舵盘孔不能视为壳体固定孔；MF106配合尚待闭合",
    ))

    horn_holes = _pcd14_m3() + [Hole(0.0, 0.0, 6.2, "spline_clear")]
    plates.append(Plate(
        name="HORN-DISC",
        drawing_no="ATRI-v2-P02",
        thickness_mm=t15,
        material="6061-T6",
        qty=20,
        outline=_circle(12.0),
        holes=horn_holes,
        note="输出端夹板，与 25T 金属舵盘叠装。中心 Φ6.2 让花键/M3 中心螺通过",
    ))

    for name, no, length, qty, note in (
        ("C-ARM-SHANK", "ATRI-v2-P03", K["shank"], 4, "小腿两侧板，中心距=踝-膝"),
        ("C-ARM-THIGH", "ATRI-v2-P04", K["thigh"], 4, "大腿两侧板，中心距=膝-髋俯仰"),
        ("C-ARM-UPPER", "ATRI-v2-P05", K["upper_arm"], 4, "上臂两侧板"),
        ("C-ARM-FOREARM", "ATRI-v2-P06", K["forearm"], 4, "前臂两侧板"),
    ):
        outline, holes = _c_arm(length)
        plates.append(Plate(
            name=name, drawing_no=no, thickness_mm=t15, material="6061-T6",
            qty=qty, outline=outline, holes=holes, note=note,
        ))

    # Superseded PELVIS/TORSO rectangular plates are not manufacturing parts.
    # Open pelvis DXF is generated from its actual B-rep by pelvis_cad.py.

    sh_holes: List[Hole] = []
    for y in (-K["shoulder_width"] / 2.0, K["shoulder_width"] / 2.0):
        for h in _pcd14_m3():
            sh_holes.append(Hole(h.x, h.y + y, h.d, h.kind))
    sh_holes += [Hole(0.0, 0.0, 3.2, "M3_clear"), Hole(20.0, 0.0, 3.2, "M3_clear"), Hole(-20.0, 0.0, 3.2, "M3_clear")]
    plates.append(Plate(
        name="SHOULDER-BAR",
        drawing_no="ATRI-v2-P09",
        thickness_mm=t15,
        material="6061-T6",
        qty=2,
        outline=_round_rect(36.0, K["shoulder_width"] + 28.0, 4.0),
        holes=sh_holes,
        note="肩宽 150 mm 横梁夹层",
    ))

    plates.append(Plate(
        name="HEAD-BRACKET",
        drawing_no="ATRI-v2-P10",
        thickness_mm=t15,
        material="6061-T6",
        qty=2,
        outline=_round_rect(40.0, 32.0, 3.0),
        holes=_pcd14_m3() + [Hole(0.0, 0.0, 6.2, "center_clear")],
        note="头偏航/俯仰安装板",
    ))

    foot_holes = _pcd14_m3()
    ax = -(K["foot_l"] / 2.0 - K["ankle_from_heel"])
    shifted = [Hole(h.x + ax, h.y, h.d, h.kind) for h in foot_holes]
    shifted.append(Hole(ax, 0.0, 10.2, "bearing_MF106"))
    for x, y in ((-48, -24), (-48, 24), (48, -24), (48, 24), (20, 0), (-20, 0)):
        shifted.append(Hole(float(x), float(y), 3.2, "M3_clear"))
    plates.append(Plate(
        name="FOOT",
        drawing_no="ATRI-v2-P11",
        thickness_mm=t20,
        material="6061-T6",
        qty=2,
        outline=_round_rect(K["foot_l"], K["foot_w"], 8.0),
        holes=shifted,
        note="2.0 mm 足板。踝轴距踵 42 mm。TPU 底用 6×M3 从下向上拧",
        layer="2.0mm",
    ))
    return plates


def _poly_area(pts: Sequence[Point]) -> float:
    a = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        a += x1 * y2 - x2 * y1
    return abs(a) / 2.0


def plate_mass_g(p: Plate) -> float:
    area = _poly_area(p.outline)
    for h in p.holes:
        area -= math.pi * (h.d / 2.0) ** 2
    area = max(area, 0.0)
    vol_cm3 = area * p.thickness_mm / 1000.0
    dens = MATERIALS[p.material]["density_g_cm3"]
    return vol_cm3 * dens * p.qty


def aluminum_mass_g() -> float:
    return sum(plate_mass_g(p) for p in all_plates())


def plates_by_layer(layer: str) -> List[Plate]:
    return [p for p in all_plates() if p.layer == layer]


def bbox(p: Plate) -> Tuple[float, float, float, float]:
    xs = [x for x, _ in p.outline]
    ys = [y for _, y in p.outline]
    return min(xs), min(ys), max(xs), max(ys)
