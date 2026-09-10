"""参数化零件建模（CadQuery / OpenCASCADE 真 B-rep 实体）。

与之前的"基元脚本"的根本区别：
  - 产出是**实心 B-rep 实体**，可圆角、抽壳、布尔、拔模
  - 导出 **STEP**（可进 SolidWorks / 任何 CAD）与 **STL**（可 3D 打印）
  - 全部参数化，改一个数即重新生成

零件清单（按关节模块拆解）：
  servo_yoke       舵机 U 型支架：夹持舵机本体，两端分别接舵盘与副轴轴承
  horn_adapter     舵盘转接件：把 25T 舵盘转成 4×M2.5 螺孔法兰
  bearing_cap      轴承压盖：把副轴轴承固定在打印件里
  link_tube        连杆：两端带接口的承力管

设计约定：
  单位 mm；Z 轴为回转轴；零件以配合面为基准面，便于装配时对齐。
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

try:
    import cadquery as cq
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "需要 CadQuery：pip install cadquery\n"
        "（它会拉取 OpenCASCADE 绑定 OCP）"
    ) from exc

from standards import (BEARINGS, FDM, bearing, fastener, servo,
                       servo_horn_interface)


def sanitize(part: cq.Workplane) -> cq.Workplane:
    """布尔运算与圆角之后做一次几何修复。

    OCC 在多次布尔/圆角后偶尔会留下微小的自交或容差问题，
    表现为 isValid() == False。这些零件多数仍能切片，但会让
    下游 CAD（SolidWorks/Webots）导入报错，所以统一修复一次。
    """
    out = []
    for solid in part.solids().vals():
        s = solid.fix() if not solid.isValid() else solid
        out.append(s)
    return cq.Workplane("XY").newObject(out).clean()



# --------------------------------------------------------------------------
# 基础特征
# --------------------------------------------------------------------------
def _centered_box(length: float, width: float, height: float,
                  z0: float = 0.0) -> cq.Workplane:
    """以 XY 中心为原点、底面在 z0 的长方体。"""
    return (cq.Workplane("XY").box(length, width, height)
            .translate((0, 0, z0 + height / 2.0)))


def screw_boss(dia: float, hole_depth: float, boss_height: float
               ) -> cq.Workplane:
    """螺钉柱：外径 2× 螺钉径，中心为底孔。"""
    f = fastener(f"M{int(dia)}" if dia in (2.0, 3.0) else "M2.5")
    od = dia * FDM["boss_od_factor"]
    boss = cq.Workplane("XY").circle(od / 2.0).extrude(boss_height)
    return boss.cut(
        cq.Workplane("XY").circle(f["tap_drill_mm"] / 2.0).extrude(hole_depth)
    )


# --------------------------------------------------------------------------
# 零件 1：舵机 U 型支架
# --------------------------------------------------------------------------
def servo_yoke(
    servo_name: str = "STS3215",
    bearing_name: str = "MF105ZZ",
    wall: float = 3.0,
    clearance: Optional[float] = None,
    fillet: float = 2.0,
    bearing_fit: str = "press",
) -> cq.Workplane:
    """舵机 U 型支架。

    结构：
        ┌─ 侧板 A：舵机输出轴侧，开孔让 25T 舵盘穿出 ─┐
        │  舵机本体夹在两块侧板之间                    │
        └─ 侧板 B：副轴侧，带轴承位（支撑对侧转动）  ─┘

    舵机从上方落入，两侧用 M2.5 螺钉压紧。
    侧板 B 的轴承位让副轴有第二个支撑点——这是双轴关节的标准做法，
    能显著降低输出轴承受的弯矩。
    """
    s = servo(servo_name)
    horn = servo_horn_interface(servo_name)

    L, W, H = s["body_mm"]            # 长 45.2 / 宽 24.7 / 高 35.0
    cl = FDM["clearance_loose_mm"] if clearance is None else clearance
    side_t = wall                      # 侧板厚
    gap = W + cl * 2                   # 两侧板之间的净距

    # 侧板外形（略大于舵机高度，留出压紧余量）
    plate_h = H + 6.0
    plate_len = L + 4.0

    part = cq.Workplane("XY")

    # --- 两侧板 ---
    for sign in (-1, 1):
        plate = (cq.Workplane("XY")
                 .box(plate_len, side_t, plate_h)
                 .translate((0, sign * (gap / 2.0 + side_t / 2.0),
                             plate_h / 2.0)))
        part = part.union(plate)

    # --- 底板（连接两侧板，舵机坐在上面）---
    base_t = wall
    base = (cq.Workplane("XY")
            .box(plate_len, gap + 2 * side_t, base_t)
            .translate((0, 0, base_t / 2.0)))
    part = part.union(base)

    # --- 侧板 A：舵盘穿出孔 ---
    horn_hole_d = horn["spline_od_mm"] + 2 * FDM["clearance_loose_mm"]
    part = part.cut(
        cq.Workplane("YZ")
        .circle(horn_hole_d / 2.0)
        .extrude(side_t * 3)
        .translate((0, -(gap / 2.0 + side_t), plate_h / 2.0))
    )

    # --- 侧板 A：舵盘 4×M2.5 安装孔（节圆）---
    for i in range(horn["hole_count"]):
        ang = 2 * math.pi * i / horn["hole_count"] + math.pi / 4
        px = (horn["pcd_mm"] / 2.0) * math.cos(ang)
        pz = (horn["pcd_mm"] / 2.0) * math.sin(ang)
        part = part.cut(
            cq.Workplane("YZ")
            .center(px, pz)
            .circle(fastener(horn["hole_thread"])["clearance_hole_mm"] / 2.0)
            .extrude(side_t * 3)
            .translate((0, -(gap / 2.0 + side_t), plate_h / 2.0))
        )

    # --- 侧板 B：轴承位 ---
    b = bearing(bearing_name)
    if bearing_fit == "press":
        bore_d = b["od_mm"] - FDM["clearance_press_mm"]
    elif bearing_fit == "snug":
        bore_d = b["od_mm"] + FDM["clearance_snug_mm"]
    else:
        bore_d = b["od_mm"] + FDM["clearance_loose_mm"]

    part = part.cut(
        cq.Workplane("YZ")
        .circle(bore_d / 2.0)
        .extrude(side_t * 3)
        .translate((0, (gap / 2.0 + side_t), plate_h / 2.0))
    )

    # --- 侧板 B：法兰轴承的沉台 ---
    if "flange_od_mm" in b:
        part = part.cut(
            cq.Workplane("YZ")
            .circle((b["flange_od_mm"] + FDM["clearance_snug_mm"]) / 2.0)
            .extrude(b["flange_width_mm"])
            .translate((0, (gap / 2.0 + side_t) + side_t / 2.0
                        - b["flange_width_mm"], plate_h / 2.0))
        )

    # --- 舵机压紧螺钉孔（两侧板各 2 个）---
    for sign in (-1, 1):
        for dx in (-L / 4.0, L / 4.0):
            part = part.cut(
                cq.Workplane("XY")
                .center(dx, sign * (gap / 2.0 + side_t / 2.0))
                .circle(fastener("M2.5")["tap_drill_mm"] / 2.0)
                .extrude(plate_h + 2)
            )

    # --- 减重孔（底板）---
    for dx in (-L / 4.0, 0.0, L / 4.0):
        part = part.cut(
            cq.Workplane("XY")
            .center(dx, 0)
            .circle(min(gap, plate_len) * 0.16)
            .extrude(base_t * 3)
        )

    # --- 结构圆角 ---
    # 只对侧板的外侧竖边倒圆：全选 |Y 方向边会在两板与底板交汇的
    # 内凹处产生自交，使实体变为 invalid。
    try:
        part = (part.edges("|Y")
                .edges(cq.selectors.BoxSelector(
                    (-plate_len, -100, -10), (plate_len, 100, plate_h + 10)))
                .fillet(fillet))
    except Exception:  # noqa: BLE001  圆角失败不阻塞构建
        pass

    return sanitize(part)


# --------------------------------------------------------------------------
# 零件 2：舵盘转接件
# --------------------------------------------------------------------------
def horn_adapter(
    servo_name: str = "STS3215",
    out_hole_thread: str = "M2.5",
    out_pcd_mm: float = 20.0,
    thickness: float = 4.0,
) -> cq.Workplane:
    """把 25T 舵盘转成带 4×M2.5 螺孔的法兰。

    用途：舵盘原厂孔位与自制连杆不匹配时的过渡件。
    """
    horn = servo_horn_interface(servo_name)

    disc = cq.Workplane("XY").circle(out_pcd_mm / 2.0 + 5.0).extrude(thickness)

    # 中心 25T 花键孔（简化为带 D 形切口的圆孔，避免建模花键）
    spline_d = horn["spline_od_mm"] + FDM["clearance_press_mm"]
    disc = disc.cut(cq.Workplane("XY").circle(spline_d / 2.0).extrude(thickness * 3))

    # 输出侧螺孔
    f = fastener(out_hole_thread)
    n = horn["hole_count"]
    for i in range(n):
        ang = 2 * math.pi * i / n + math.pi / 4
        disc = disc.cut(
            cq.Workplane("XY")
            .center((out_pcd_mm / 2.0) * math.cos(ang),
                    (out_pcd_mm / 2.0) * math.sin(ang))
            .circle(f["tap_drill_mm"] / 2.0)
            .extrude(thickness * 3)
        )

    # 减重
    for i in range(n):
        ang = 2 * math.pi * i / n
        disc = disc.cut(
            cq.Workplane("XY")
            .center((out_pcd_mm / 2.0 + 2.0) * math.cos(ang),
                    (out_pcd_mm / 2.0 + 2.0) * math.sin(ang))
            .circle(2.0)
            .extrude(thickness * 3)
        )

    try:
        disc = disc.edges("|Z").fillet(1.0)
    except Exception:  # noqa: BLE001
        pass
    return disc


# --------------------------------------------------------------------------
# 零件 3：连杆（承力管）
# --------------------------------------------------------------------------
def link_tube(
    length: float = 80.0,
    outer_dia: float = 40.0,
    wall: float = 3.0,
    end_bore_mm: float = 5.0,
    end_thickness: float = 6.0,
    wire_hole_dia: float = 6.0,
) -> cq.Workplane:
    """两端实心封头 + 轴孔的空心承力连杆。

    等效替代现有 capsule 基元，但：
      - 管身**空心**（省料省时，刚度重量比更高）
      - 两端为**实心端头**并开轴孔，形成"眼"结构，可穿轴或接轴承
      - 侧壁开**走线孔**

    关键几何约束：端头直径必须等于管外径，才能与管壁在径向上重叠
    （管壁位于 r∈[outer/2−wall, outer/2]）。若端头直径小于管内径，
    两者径向上不相交，fuse 无法合并，会留下互不相连的多个实体。
    """
    from cadquery import Solid, Vector

    r_out = outer_dia / 2.0
    r_in = r_out - wall

    # 管身：外圆柱减去内圆柱
    body = Solid.makeCylinder(r_out, length, Vector(0, 0, 0))
    body = body.cut(Solid.makeCylinder(r_in, length + 2, Vector(0, 0, -1)))

    # 两端实心端头（与外径同径，保证与管壁径向重叠）
    for z in (0.0, length - end_thickness):
        body = body.fuse(
            Solid.makeCylinder(r_out, end_thickness, Vector(0, 0, z))
        )

    # 贯穿轴孔
    body = body.cut(
        Solid.makeCylinder(end_bore_mm / 2.0, length * 3, Vector(0, 0, -length))
    )

    # 侧壁走线孔（径向打通）
    wire = Solid.makeCylinder(wire_hole_dia / 2.0, outer_dia * 2,
                              Vector(-outer_dia, 0, length / 2.0))
    wire = wire.rotate(Vector(0, 0, 0), Vector(0, 1, 0), 90)
    body = body.cut(wire)

    return sanitize(cq.Workplane("XY").add(body))



# --------------------------------------------------------------------------
# 零件登记表
# --------------------------------------------------------------------------
PARTS: Dict[str, Dict[str, Any]] = {
    "servo_yoke": {
        "builder": servo_yoke,
        "desc": "舵机 U 型支架（夹持舵机 + 副轴轴承位）",
        "used_by": "所有 pitch/roll 关节",
    },
    "horn_adapter": {
        "builder": horn_adapter,
        "desc": "25T 舵盘转接法兰",
        "used_by": "舵盘与连杆的过渡",
    },
    "link_tube": {
        "builder": link_tube,
        "desc": "两端带法兰的空心承力连杆",
        "used_by": "大腿 / 小腿 / 上臂 / 前臂",
    },
}


def build(name: str, **kwargs: Any) -> cq.Workplane:
    if name not in PARTS:
        raise KeyError(f"未登记零件 {name}；可选 {sorted(PARTS)}")
    return PARTS[name]["builder"](**kwargs)


def part_report(name: str, solid: cq.Workplane) -> Dict[str, Any]:
    """零件的可制造性摘要。"""
    v = solid.val()
    bb = v.BoundingBox()
    return {
        "part": name,
        "volume_mm3": round(v.Volume(), 1),
        "bbox_mm": [round(bb.xlen, 1), round(bb.ylen, 1), round(bb.zlen, 1)],
        "is_valid": bool(v.isValid()),
        "solids": len(solid.solids().vals()),
    }
