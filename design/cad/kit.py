"""骨架建模工具箱：统一约定 + 通用结构特征 + 打印质量模型。

**全库统一约定**（SolidWorks 侧同样适用，见 `design/handoff/SolidWorks-工作流.md`）：

1. 单位 **mm**；**Z 轴向上**；X 向前（与 URDF 一致）。
2. 零件以**配合面**为基准面；原点落在该零件的**关节轴线**或安装基准上，
   装配时直接对齐，不做二次对刀。
3. 界面尺寸不写死在零件里，一律引用本文件的 `IF`（接口标准）。
4. 打印件质量用 `printed_mass()` 估算（外壁 + 填充），**不用实心质量**——
   实心质量会把质量闭合算崩（v1 的教训）。
"""
from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Sequence, Tuple

import cadquery as cq

from parts import sanitize
from standards import (BEARINGS, FDM, SERVOS, bearing, fastener, servo,
                       servo_horn_interface)

# --------------------------------------------------------------------------
# 材料
# --------------------------------------------------------------------------
MATERIALS: Dict[str, Dict[str, Any]] = {
    "PETG": {
        "density_g_cm3": 1.27,
        "toughness": "高（层间韧性优于 PLA）",
        "use": "承力结构件：关节笼、连杆、足板、躯干框架",
        "note": "吸湿，开封后需干燥；打印温度 240–250 °C，热床 80 °C",
    },
    "PLA": {
        "density_g_cm3": 1.24,
        "toughness": "中（脆，层间差）",
        "use": "仅非承力装饰件（头壳外观、线夹）",
        "note": "不耐温（>60 °C 软化），禁止用于舵机附近与受力件",
    },
    "PA12_CF": {
        "density_g_cm3": 1.06,
        "toughness": "很高（尼龙 + 碳纤，抗冲击最好）",
        "use": "落地冲击件：足板、踝部传动架（若预算允许）",
        "note": "需高温喷嘴与干燥，打印门槛高；单价约 PETG 的 4–6 倍",
    },
    "TPU95A": {
        "density_g_cm3": 1.21,
        "toughness": "柔性",
        "use": "足底防滑垫、线束护套",
        "note": "软料，需直驱挤出机",
    },
}

# --------------------------------------------------------------------------
# 接口标准（Interface standard）
# --------------------------------------------------------------------------
# 打印件之间、打印件与商品件之间的**唯一接口口径**。
# 改这里 = 改全机装配，所以每一个都标了依据。
IF: Dict[str, Dict[str, Any]] = {
    # I1：打印件 ↔ 打印件 级联法兰
    "cage_flange": {
        "holes": 4, "pcd_mm": 26.0, "hole_dia_mm": 3.2,
        "thread": "M3", "screw": "M3x8 内六角",
        "why": "4×M3 是打印件能可靠承力的最小配置；PCD26 保证扳手空间",
    },
    # I2：打印件 ↔ 金属舵盘
    "horn": {
        "holes": 4, "pcd_mm": 14.0, "hole_dia_mm": 2.7,
        "thread": "M2.5", "screw": "M2.5x8 内六角",
        "why": "飞特 25T 金属舵盘自带 4×M2.5 螺孔，PCD 已实物测绘为 Φ14",
    },
    # I3：副轴支撑（双支撑点的第二个点）
    "secondary_shaft": {
        "bearing": "MF106ZZ", "shaft_dia_mm": 6.0, "shaft_h7_mm": [5.96, 5.98],
        "boss_dia_mm": 14.0, "boss_height_mm": 6.0,
        "why": "单靠舵机输出轴承弯会让齿轮箱早期磨损；副轴轴承把弯矩分走一半",
    },
    # I4：连杆管接口
    "tube": {
        "od_mm": 40.0, "wall_mm": 3.0, "flange_pcd_mm": 26.0,
        "why": "Φ40 与舵机笼同宽，整机视觉与包络一致；壁厚 3.0 ≥ 结构底线 3.2 的 0.94 倍",
    },
    # I5：舵机机身安装孔（来自飞特 2D 图纸，自洽性待复测）
    "servo_ear": {
        "pitch_len_mm": 48.5, "pitch_width_mm": 10.0, "hole_dia_mm": 2.7,
        "verify": "drawing-待复测",
        "why": "图纸总长 51.2 与孔距 48.5 推出孔边仅 0.10 mm，二者需实物确认其一",
    },
}

# 舵机输出轴相对机身高度的偏置（图纸值 11.0 mm，从主端面算）
SERVO_SHAFT_FROM_FACE_MM = 11.0


def servo_axis_offset_mm(servo_name: str = "STS3215") -> float:
    """关节轴线相对舵机几何中心的 Z 偏置（mm）。

    舵机高度 H=35.0，输出轴中心距主端面 11.0 mm →
    轴线在几何中心上方 (H/2 − 11.0) = 6.5 mm。
    即：**把舵机中心放在轴线下方 6.5 mm** 才是真实姿态。
    旧 `servo_yoke` 按居中建模，图纸核验后才暴露这个偏差。
    """
    H = servo(servo_name)["body_mm"][2]
    return H / 2.0 - SERVO_SHAFT_FROM_FACE_MM


# --------------------------------------------------------------------------
# 基础特征
# --------------------------------------------------------------------------
def box(length: float, width: float, height: float,
        at: Sequence[float] = (0, 0, 0),
        centered_z: bool = False) -> cq.Workplane:
    """轴对齐长方体。默认 `at` 是**底面中心**；`centered_z=True` 时是几何中心。"""
    x, y, z = at
    b = cq.Workplane("XY").box(length, width, height)
    dz = z if centered_z else z + height / 2.0
    return b.translate((x, y, dz))


def plate(length: float, width: float, thickness: float,
          at: Sequence[float] = (0, 0, 0)) -> cq.Workplane:
    """底板：`at` 为底面中心。"""
    return box(length, width, thickness, at=at)


def cyl(dia: float, height: float, at: Sequence[float] = (0, 0, 0),
        axis: str = "Z") -> cq.Workplane:
    """圆柱：`at` 为轴线上的**起点**（底面中心）。"""
    x, y, z = at
    c = cq.Workplane("XY").circle(dia / 2.0).extrude(height)
    if axis == "X":
        c = c.rotate((0, 0, 0), (0, 1, 0), 90)
    elif axis == "Y":
        c = c.rotate((0, 0, 0), (1, 0, 0), -90)
    return c.translate((x, y, z))


def tube(od: float, idia: float, height: float,
         at: Sequence[float] = (0, 0, 0), axis: str = "Z") -> cq.Workplane:
    """圆管（外径/内径/长）。"""
    x, y, z = at
    t = (cq.Workplane("XY").circle(od / 2.0).circle(idia / 2.0).extrude(height))
    if axis == "X":
        t = t.rotate((0, 0, 0), (0, 1, 0), 90)
    elif axis == "Y":
        t = t.rotate((0, 0, 0), (1, 0, 0), -90)
    return t.translate((x, y, z))


def drill(part: cq.Workplane, points: Iterable[Tuple[float, float]],
          dia: float, depth: float, z0: float = -1.0,
          axis: str = "Z") -> cq.Workplane:
    """在给定 XY 点上打一排通孔（沿 `axis`，起点 z0）。"""
    pts = list(points)
    if not pts:
        return part
    if axis == "Z":
        cutter = (cq.Workplane("XY").pushPoints(pts)
                  .circle(dia / 2.0).extrude(depth).translate((0, 0, z0)))
    elif axis == "Y":
        cutter = (cq.Workplane("XZ").pushPoints(pts)
                  .circle(dia / 2.0).extrude(depth).translate((0, z0, 0)))
    else:  # X
        cutter = (cq.Workplane("YZ").pushPoints(pts)
                  .circle(dia / 2.0).extrude(depth).translate((z0, 0, 0)))
    return part.cut(cutter)


def bolt_circle(pcd: float, holes: int = 4, phase_deg: float = 45.0
                ) -> List[Tuple[float, float]]:
    """节圆上的孔位坐标（XY 平面）。"""
    return [(pcd / 2.0 * math.cos(math.radians(phase_deg + 360.0 * i / holes)),
             pcd / 2.0 * math.sin(math.radians(phase_deg + 360.0 * i / holes)))
            for i in range(holes)]


def bosses(points: Iterable[Tuple[float, float]], od: float, height: float,
           bore_dia: float = 0.0, bore_depth: float = 0.0,
           z0: float = 0.0) -> cq.Workplane:
    """一组螺钉柱（可带底孔）。"""
    pts = list(points)
    b = (cq.Workplane("XY").pushPoints(pts).circle(od / 2.0)
         .extrude(height).translate((0, 0, z0)))
    if bore_dia > 0:
        b = (b.cut(cq.Workplane("XY").pushPoints(pts).circle(bore_dia / 2.0)
                   .extrude(bore_depth).translate((0, 0, z0 + height - bore_depth))))
    return b


def vent_slots(part: cq.Workplane, length: float, width: float, thickness: float,
               x0: float, y0: float, z0: float, count: int = 4,
               pitch: float = 0.0, vertical: bool = False) -> cq.Workplane:
    """减重/散热槽阵列（沿 X 或 Y 排布）。"""
    pitch = pitch or width * 1.8
    for i in range(count):
        off = (i - (count - 1) / 2.0) * pitch
        if vertical:
            cut = box(length, width, thickness, at=(x0 + off, y0, z0))
        else:
            cut = box(length, width, thickness, at=(x0, y0 + off, z0))
        part = part.cut(cut)
    return part


def safe_fillet(part: cq.Workplane, radius: float,
                selector: str = "|Z") -> cq.Workplane:
    """圆角失败不阻塞构建（OCC 在复杂交汇处会自交）。"""
    try:
        return part.edges(selector).fillet(radius)
    except Exception:  # noqa: BLE001
        return part


def safe_chamfer(part: cq.Workplane, length: float,
                 selector: str = "|Z") -> cq.Workplane:
    try:
        return part.edges(selector).chamfer(length)
    except Exception:  # noqa: BLE001
        return part


# --------------------------------------------------------------------------
# 质量模型：打印件 ≠ 实心件
# --------------------------------------------------------------------------
def printed_mass(shape: cq.Workplane, material: str = "PETG",
                 wall: float = None, infill: float = None) -> Dict[str, float]:
    """打印件质量估算：外壁壳 + 内部填充。

        V_壳 ≈ 表面积 × 壁厚          （薄壁近似，对 3 mm 壁足够准）
        m    = (V_壳 + (V − V_壳) × 填充率) × ρ

    这是**给质量闭合用的工程估算**，不是切片器结果；切片器会因
    支撑、拉丝、挤出倍率再差 ±8%。
    """
    wall = FDM["wall_mm"] if wall is None else wall
    infill = 0.5 if infill is None else infill
    rho = MATERIALS[material]["density_g_cm3"]
    v = shape.val().Volume()
    a = shape.val().Area()
    v_shell = min(a * wall, v)
    v_core = max(v - v_shell, 0.0)
    m = (v_shell + v_core * infill) * rho / 1000.0
    return {
        "volume_mm3": round(v, 1),
        "v_shell_mm3": round(v_shell, 1),
        "shell_ratio": round(v_shell / v, 3) if v else 0.0,
        "mass_solid_g": round(v * rho / 1000.0, 2),
        "mass_printed_g": round(m, 2),
        "material": material, "wall_mm": wall, "infill": infill,
    }


def part_report(name: str, shape: cq.Workplane, material: str = "PETG",
                wall: float = None, infill: float = 0.5) -> Dict[str, Any]:
    """零件可制造性摘要（供 build_all.py 汇总）。"""
    v = shape.val()
    bb = v.BoundingBox()
    rep: Dict[str, Any] = {
        "part": name,
        "bbox_mm": [round(bb.xlen, 1), round(bb.ylen, 1), round(bb.zlen, 1)],
        "bbox_min": [round(bb.xmin, 1), round(bb.ymin, 1), round(bb.zmin, 1)],
        "is_valid": bool(v.isValid()),
        "solids": len(shape.solids().vals()),
        "material": material,
    }
    rep.update(printed_mass(shape, material=material, wall=wall, infill=infill))
    return rep


# --------------------------------------------------------------------------
# 姿态：把"标准姿态"的关节模块旋到真实姿态
# --------------------------------------------------------------------------
DIRS = {
    "+x": (1, 0, 0), "-x": (-1, 0, 0),
    "+y": (0, 1, 0), "-y": (0, -1, 0),
    "+z": (0, 0, 1), "-z": (0, 0, -1),
}


def apply_trsf(part: cq.Workplane, trsf) -> cq.Workplane:
    """对整件施加 OCC 变换（CadQuery 2.5 的 Workplane 没有 transformShape）。"""
    out = [s.transformShape(cq.Matrix(trsf)) for s in part.solids().vals()]
    return cq.Workplane("XY").newObject(out).clean()


def orient(shape: cq.Workplane, shaft: str, parent: str) -> cq.Workplane:
    """把标准姿态零件旋到 (输出轴方向, 母端朝向) 指定的真实姿态。

    标准姿态（所有关节模块件的建模基准）：
        - 舵机输出轴沿 **+Y**
        - 母端接口板朝 **+Z**
        - 子端（连杆）朝 **−Z**

    这两个方向正交，唯一确定一个旋转；`yaw` 关节（轴与母端同向）
    是退化情形，由零件自己显式建模，不走这里。
    """
    from OCP.gp import gp_Ax3, gp_Dir, gp_Pnt, gp_Trsf

    src = DIRS[parent], DIRS[shaft]
    if abs(sum(a * b for a, b in zip(*src))) > 1e-9:
        raise ValueError(f"shaft={shaft} 与 parent={parent} 不能同向（yaw 请显式建模）")
    from_ax = gp_Ax3(gp_Pnt(0, 0, 0), gp_Dir(*DIRS["+z"]), gp_Dir(*DIRS["+y"]))
    to_ax = gp_Ax3(gp_Pnt(0, 0, 0), gp_Dir(*DIRS[parent]), gp_Dir(*DIRS[shaft]))
    trsf = gp_Trsf()
    trsf.SetTransformation(from_ax, to_ax)
    return apply_trsf(shape, trsf)


def needs_support(shape: cq.Workplane, axis: str = "Z") -> List[str]:
    """粗略的可打印性提示（不做真正的悬垂分析，只查包络与最小特征）。"""
    warnings: List[str] = []
    bb = shape.val().BoundingBox()
    if max(bb.xlen, bb.ylen, bb.zlen) > 220.0:
        warnings.append(f"最大尺寸 {max(bb.xlen, bb.ylen, bb.zlen):.0f} mm "
                        f"超过常见 220×220 热床，需分件或大尺寸机型")
    if min(bb.xlen, bb.ylen, bb.zlen) < FDM["min_feature_mm"]:
        warnings.append("存在小于最小可靠特征 0.8 mm 的方向，需检查薄壁")
    return warnings
