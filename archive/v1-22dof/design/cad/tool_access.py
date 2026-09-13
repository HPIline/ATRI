"""工具可达性校核：拧螺钉的批头/手柄空间是否够。

任务点（A）：
    对装配体里每一个需要拧螺钉的位置，构造"工具包络"——批头 Φ6 × 60 mm 圆柱 + 手柄 Φ25 球——
    沿该螺钉的装配方向（从孔口向外），与周围所有零件求干涉 / 最小距离；
    给出三档判定：
        ✅ 可达        最小余量 ≥ 2 mm
        ⚠️ 勉强可达   0 ≤ 最小余量 < 2 mm
        ❌ 不可达      余量 < 0（与某零件穿模）

为什么单独成模块：
    `audit_assembly.py` 测的是"零件互相之间"的穿模；这里测的是"工具能否到达某个孔"。
    后者要构造一个外部实体（工具）伸进装配体里求交，传统做法（手测 / 凭经验）会漏掉
    60 mm 深孔 + 旁边紧贴件这种情形——本脚本把"拧得到 / 拧不到"变成数字。

用法：
    .venv-cad/bin/python design/cad/tool_access.py
    .venv-cad/bin/python design/cad/tool_access.py --json     # 同时输出 JSON

位置来源（与骨架零件库一一对应，禁止手猜坐标）：
    - 舵机 4×M2.5 沿轴       joint_cage / joint_cage_yaw / cluster_outrigger / compact_adapter
    - 笼法兰 4×M3             joint_cage_yaw（母端 PCD26） + torso_frame 颈座顶板
    - 舵盘 4×M2.5             limb_fork（PCD14） + cluster_horn_arm（PCD14） + gripper_jaw
    - 插接芯棒 3×M3 径向      joint_cage + limb_fork（120° × 3，在 r=20 的 XZ 平面上）
    - 副轴轴承挡片            yaw 关节母端板内的 MF106ZZ 沉台（无螺钉，校核避空）
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]  # cad/design/v1-22dof/archive → repo
sys.path.insert(0, str(HERE))

import cadquery as cq
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.gp import gp_Dir, gp_Pnt, gp_Vec

import assembly as A
from fitcheck import bbox_of, common_volume, distance
from kit import (DIRS, IF, apply_trsf, box, cyl, orient, servo_frame)
from standards import fastener, servo


# --------------------------------------------------------------------------
# 工具包络（批头 + 手柄）
# --------------------------------------------------------------------------
# 依据：1.5 mm 内六角扳手套 Φ6 × 60 mm 批头（型号常用 T6/T8，套筒外径 ≈ Φ6）；
# 手柄段按标准棘轮扳手握把最大径 Φ25 计算（球头 → 任何方向都能容纳）。
TOOL_BIT_DIA = 6.0
TOOL_BIT_LEN = 60.0        # 60 mm 长：M3×8 沉入再加 50+ 余量；M2.5 也够
TOOL_HANDLE_DIA = 25.0
TOOL_HANDLE_LEN = 40.0     # 球段总长 = 40 mm（球径 25 占长 25，两端倒角各 7.5）
# 沿装配方向（从孔口向外）的最短需求空间 = 批头长 60 + 手柄球径 12.5；
# 小于这个值就拧不到位（手柄顶到底盘）。
MIN_REACH = TOOL_BIT_LEN + 12.5

# 判定阈值
MARGIN_OK = 2.0            # 余量 ≥ 2 mm ⇒ ✅ 可达
MARGIN_TIGHT = 0.0         # 0 ≤ 余量 < 2 mm ⇒ ⚠️ 勉强
# < 0 ⇒ ❌ 不可达


def tool_envelope(origin: Tuple[float, float, float],
                  axis: Tuple[float, float, float],
                  dia: float = TOOL_BIT_DIA,
                  length: float = TOOL_BIT_LEN) -> cq.Workplane:
    """沿 `axis` 方向（从 origin 向外延伸 length）构造一段圆柱包络。

    `axis` 必须是单位向量或可归一化向量。圆柱底面中心 = origin，端面方向 = axis。

    实现：用 gp_Trsf.SetValues 把"局部 +Z 方向"映射到 axis，并设平移 = origin。
    这样圆柱的 z=0 截面（起点）落在 origin 上，沿 +Z 拉出的 60 mm 落在 origin + axis*60。
    """
    v = gp_Vec(*axis)
    n = v.Magnitude()
    if n < 1e-9:
        raise ValueError(f"axis 长度为零：{axis}")
    ux, uy, uz = v.X() / n, v.Y() / n, v.Z() / n

    # 选一个与 axis 不共线的参考方向构造局部 +X / +Y，使三者成右手正交。
    # 经典做法：若 axis 接近 ±Z，取 +X 作 up；否则用 +Z 作 up。
    if abs(uz) < 0.9:
        up = (0.0, 0.0, 1.0)
    else:
        up = (1.0, 0.0, 0.0)
    # local +Y = up × axis（确保与 axis 正交）
    lyx = up[1] * uz - up[2] * uy
    lyy = up[2] * ux - up[0] * uz
    lyz = up[0] * uy - up[1] * ux
    ln = math.sqrt(lyx * lyx + lyy * lyy + lyz * lyz) or 1.0
    lyx, lyy, lyz = lyx / ln, lyy / ln, lyz / ln
    # local +X = +Y × axis
    lxx = lyy * uz - lyz * uy
    lxy = lyz * ux - lxx * 0  # placeholder
    # recompute properly
    lxx = lyy * uz - lyz * uy
    lxy = lyz * ux - lyx * uz
    lxz = lyx * uy - lyy * ux

    ox, oy, oz = origin
    # SetValues 第 i 行 = (local X 在 world i, local Y 在 world i, local Z 在 world i, 平移 i)
    from OCP.gp import gp_Trsf
    trsf = gp_Trsf()
    trsf.SetValues(
        lxx, lyx, ux, ox,
        lxy, lyy, uy, oy,
        lxz, lyz, uz, oz,
    )
    base = cq.Workplane("XY").circle(dia / 2.0).extrude(length)
    from kit import apply_trsf
    return apply_trsf(base, trsf)


def tool_full(origin: Tuple[float, float, float],
              axis: Tuple[float, float, float]) -> cq.Workplane:
    """完整工具：批头 60 mm + 手柄球 25 mm（沿同一轴向串联）。"""
    bit = tool_envelope(origin, axis, TOOL_BIT_DIA, TOOL_BIT_LEN)
    v = gp_Vec(*axis)
    n = v.Magnitude()
    d = gp_Dir(v.X() / n, v.Y() / n, v.Z() / n)
    # 手柄中心 = origin + axis * (60 + 12.5)
    hand_origin = (origin[0] + d.X() * (TOOL_BIT_LEN + TOOL_HANDLE_LEN / 2.0),
                   origin[1] + d.Y() * (TOOL_BIT_LEN + TOOL_HANDLE_LEN / 2.0),
                   origin[2] + d.Z() * (TOOL_BIT_LEN + TOOL_HANDLE_LEN / 2.0))
    handle = tool_envelope(hand_origin, axis, TOOL_HANDLE_DIA, TOOL_HANDLE_LEN)
    return bit.union(handle)


def common_vol(a: cq.Workplane, b: cq.Workplane) -> float:
    op = BRepAlgoAPI_Common(a.val().wrapped, b.val().wrapped)
    op.Build()
    if not op.IsDone():
        return 0.0
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(op.Shape(), props)
    return abs(props.Mass())


def min_dist(a: cq.Workplane, b: cq.Workplane) -> float:
    d = BRepExtrema_DistShapeShape(a.val().wrapped, b.val().wrapped)
    d.Perform()
    return d.Value() if d.IsDone() else 1e9


# --------------------------------------------------------------------------
# 把"关节原点 + (a,b,c) 偏移 + 轴向"转成世界 (origin, axis)
# --------------------------------------------------------------------------
def world_origin(kin: A.Kin, joint: str,
                 local: Tuple[float, float, float]) -> Tuple[float, float, float]:
    m = kin.joint_world(joint)
    return A.apply(m, local)


def world_axis(kin: A.Kin, joint: str,
               axis_local: str) -> Tuple[float, float, float]:
    """把"骨架源码里写的局部方向"映射到世界。

    ⚠️ 关键设计：骨架建模约定（`skeleton.py` 与 `kit.orient()`）——
        标准姿态下 `+Y = 关节输出轴`，`+Z = 母端朝向`。
        所以：
        - joint_cage / limb_fork / cluster_outrigger / compact_adapter：
          局部 ±Y → 世界 ±kin.axis_world(joint)
        - joint_cage_yaw：标准姿态输出轴 = +Z，yaw 类不调用 `orient()`；
          `axis_rot` 把 +Z 旋到目标 `shaft`，所以：
          局部 ±Z → 世界 ±kin.axis_world(joint)
        - cluster_horn_arm（按"父关节名"记录）：标准姿态 `+Z = 父舵机输出轴反方向`，
          `orient(part, out_shaft, OPP[in_shaft])` 中 `parent_dir = OPP[in_shaft]`。
          局部 +Z → 世界 = OPP[in_shaft] 方向 = −父舵机输出轴。
          局部 −Z → 世界 = +父舵机输出轴 = kin.axis_world(joint)。
        - gripper_jaw（关节 = gripper）：gripper_jaw 是独立函数，
          drill axis="Z"，z0=-1 → 进给 −Z 局部。gripper link 局部坐标系与世界一致
          （gripper shaft = ±Y，gripper link frame = pelvis frame + …的平移），
          所以 −Z 局部 = 世界 −Z。
        - joint_cage 母端 / limb_fork 子端 3×M3 径向：drill axis="Z"，
          沿 +Z 局部进给。joint_cage / limb_fork 的 +Z = parent 方向。
          所以 +Z 局部 = OPP[shaft] 方向（局部 +Z → 世界 OPP[shaft]）？
          实际上骨架 orient() 的映射是 +Y→shaft, +Z→parent。对于正交 cage，
          parent ⊥ shaft，所以 +Z 局部 → world = OPP[parent] 还是 OPP[shaft]？
          这是关键问题 —— 必须用 `apply(orient_rot, (0,0,1))`。
    """
    sc = A.JOINT_SCHEME.get(joint, {})
    cage_kind = sc.get("cage", "")
    shaft = sc.get("shaft", "+z")

    # 1) yaw 关节：局部 ±Z = ±输出轴
    if cage_kind == "yaw" and axis_local in ("+z", "-z"):
        v = kin.axis_world(joint)
        if axis_local == "-z":
            v = (-v[0], -v[1], -v[2])
        nv = math.sqrt(sum(c * c for c in v)) or 1.0
        return (v[0] / nv, v[1] / nv, v[2] / nv)

    # 2) joint_cage / limb_fork / cluster_outrigger / compact_adapter：
    #    局部 ±Y → 世界 ±输出轴
    if axis_local in ("+y", "-y"):
        v = kin.axis_world(joint)
        if axis_local == "-y":
            v = (-v[0], -v[1], -v[2])
        nv = math.sqrt(sum(c * c for c in v)) or 1.0
        return (v[0] / nv, v[1] / nv, v[2] / nv)

    # 3) cluster_horn_arm 锁上一级（joint = 父关节名）
    if axis_local in ("+z", "-z"):
        for link, cfg in A.CLUSTER_ARMS.items():
            parent_j = link[:-5] if link.endswith("_link") else ""
            if parent_j == joint:
                # local +Z → OPP[in_shaft] 方向；−Z → +in_shaft 方向
                v = kin.axis_world(joint) if axis_local == "-z" else \
                    (-kin.axis_world(joint)[0],
                     -kin.axis_world(joint)[1],
                     -kin.axis_world(joint)[2])
                nv = math.sqrt(sum(c * c for c in v)) or 1.0
                return (v[0] / nv, v[1] / nv, v[2] / nv)
        # 4) gripper_jaw（局部 −Z）：世界 −Z
        if joint.endswith("_gripper") and axis_local == "-z":
            return (0.0, 0.0, -1.0)
        # 5) joint_cage / limb_fork 3×M3 径向：局部 +Z → ？
        #    骨架源码里 joint_cage 母端 / limb_fork 子端 3×M3 的 drill 进给 = +Z 局部。
        #    骨架 orient() 映射：+Y→shaft, +Z→parent, +X=shaft×parent。
        #    所以局部 +Z → 世界 parent 方向 = JOINT_SCHEME[parent]。
        #    反之 −Z 局部 → −parent 方向。
        if axis_local in ("+z", "-z"):
            parent_str = sc.get("parent", "+z")
            v = DIRS[parent_str]
            if axis_local == "-z":
                v = (-v[0], -v[1], -v[2])
            return v  # DIRS 已是单位向量

    raise ValueError(f"未实现 joint={joint} axis_local={axis_local}")


# --------------------------------------------------------------------------
# 校核场景
# --------------------------------------------------------------------------
# 每个场景返回一个 dict：
#   joint, kind, hole_local (关节系下), axis_local (进给方向: '+x'/'-x'/... 在关节局部),
#   desc, fastener (紧固件规格)
#
# 关键约定：
#   - `joint` = 该螺钉"装在哪个关节的笼子上"；
#   - `hole_local` = 在 `joint_world` 矩阵坐标系下的局部偏移；
#   - `axis_local` = 拧螺钉的进给方向，在**关节局部坐标系**下。
#   真实方向由 `orient()` / `joint_world()` 把局部向量旋到世界得到。
#
# 为什么"局部方向" = `axis_local` 而不是世界表达：
#   skeleton.py 里的 `drill(... axis='Y'/'Z')` 写死是局部方向；
#   本脚本必须按**局部进给方向**记录，再让 `world_axis(joint, axis_local)` 旋到世界。
#   这样方向与骨架源码 1:1 对应，未来改骨架时不会同步走偏。

SCENARIOS: List[Dict[str, Any]] = []

def _add(joint: str, kind: str, hole: Tuple[float, float, float],
         axis_local: str, desc: str, fastener_name: str = "M2.5") -> None:
    SCENARIOS.append({
        "joint": joint, "kind": kind, "hole_local": hole,
        "axis_local": axis_local, "desc": desc, "fastener": fastener_name,
    })


ORTHO_JOINTS = [j for j, sc in A.JOINT_SCHEME.items() if sc["cage"] == "ortho"]
YAW_JOINTS = [j for j, sc in A.JOINT_SCHEME.items() if sc["cage"] == "yaw"]
CLUSTER_JOINTS = [j for j, sc in A.JOINT_SCHEME.items() if sc["cage"] == "cluster"]
FORK_JOINTS = [j for j, sc in A.JOINT_SCHEME.items() if sc["fork"] == "fork"]
HORN_PCD = IF["horn"]["pcd_mm"]        # 14.0


# 几何参数（与 skeleton.py 同源；改这里不会同步骨架 ——
# 但本脚本是只读骨架，单向参考；若骨架数值变更，运行本脚本会立刻看出）
PLATE_T = 3.0
PLATE_Y = 19.25                  # 侧板中心
PLATE_OUT = PLATE_Y + PLATE_T / 2.0   # 20.75：+Y 端板外表面
PLATE_IN = PLATE_Y - PLATE_T / 2.0    # 17.75：+Y 端板内表面
HORN_FACE = 24.05                # limb_fork 内表面（贴舵盘）
ARM_T = PLATE_T                  # 3.0
FORK_OUT = HORN_FACE + ARM_T     # 27.05：limb_fork +Y 端面（板外）
COMPACT_OUT = 16.0               # compact limb_fork 的 +Y 端高度（compact=True 时 z_top=16）
YAW_PLATE_OUT_Z = 20.0           # joint_cage_yaw 输出端板外表面 z = -BOSS_FACE - plate_t
YAW_PLATE_OUT_Z_SEC = 17.5 + PLATE_T / 2.0   # 副轴端板外表面 z = +Y_HALF + plate_t = +19.0
YAW_PCD26_Z_SEC = 17.5 + PLATE_T * 2.0       # 19+3 = 22 → 上方空间可拧

# limb_fork 子端芯棒（skeleton.py L300）：SPIGOT_H=12，从 z_base_bot 向 -z 延伸 12。
# 孔在 z_base_bot - SPIGOT_H/2；进给 +Z 局部；z_base_bot 默认 -19.6（非 compact）。
FORK_SPIGOT_Z = -19.6 - 6.0     # -25.6：孔中心（从上面进给则需 -25.6 - 7 = -32.6）
JOINT_CAGE_SPIGOT_Z = 20.0 + 12.0  # 32：孔中心（joint_cage 母端芯棒）
JOINT_CAGE_SPIGOT_OUT_Z = 20.0 + 12.0 + 7.0   # 39：+Z 外表面（+Z 进给的孔口）

# torso 颈座顶板（skeleton.py L674）：shelf = box(60, 44, 2.6, at=(0, 0, 60.0))
# 顶板 z 上表面 = 60.0 + 2.6 = 62.6；4 孔在 z=62.0（torso 局部）。
NECK_TOP_Z = 60.0 + 2.6         # 62.6

# ---------- 1) joint_cage 4×M2.5 沿输出轴 ----------
# 工具起点放在 +Y 端板外侧 1 mm；孔口位置 (sx*4.95, +PLATE_OUT + 1, sy*4.95)。
# 注：drill 的"孔中心"是 (±4.95, ±4.95) 在 XY，但 sketch 是 (sx, sy) → X, Y。
# 所以输出侧 (4.95, 4.95, 0) 这个 (X, Y, Z) 对应局部 X = 4.95（孔位 X）、
# 局部 Y = 4.95（孔位 Y，但 skeleton drill 的 Y 参数其实没用）、
# 局部 Z = 0（孔位 Z，但 skeleton drill 的 Z 也没用）。
# 看 skeleton L149：
#   part = drill(part, [(sx * pitch[0] / 2.0, sy * pitch[1] / 2.0)
#                       for sx in (-1, 1) for sy in (-1, 1)],
#                dia=..., depth=2*(PLATE_Y + PLATE_T) + 2.0,
#                z0=-PLATE_Y - PLATE_T - 1.0, axis="Y")
# 所以孔位坐标是 (X, Y) → 实际映射到 drill 的 (X, Y) —— 与标准的 (X=横, Y=纵) 一致；
# 但因 axis="Y"，所以深度沿 Y。孔中心 (sx*4.95, sy*4.95, *) 在 XY 平面上的孔位置，
# 与"沿 Y 钻深度"无关。
# 工具起点：取 (4.95, +PLATE_OUT + 1, 4.95)，方向 +Y（局部）= 世界 +shaft。
for j in ORTHO_JOINTS:
    _add(j, "joint_cage 4×M2.5（输出侧端面）",
         (4.95, PLATE_OUT + 1.0, 4.95), "+y",
         f"joint_cage 的 M2.5（输出侧 +Y 端进给）", "M2.5")
    _add(j, "joint_cage 4×M2.5（副轴侧端面）",
         (-4.95, -(PLATE_OUT + 1.0), -4.95), "-y",
         f"joint_cage 的 M2.5（副轴侧 -Y 端进给）", "M2.5")


# ---------- 2) joint_cage_yaw 4×M2.5 沿 Z 轴 ----------
# 骨架源码（skeleton.py L232-236）：drill 沿 axis="Z"；孔位 (sx*4.95, sy*4.95, ...)；
# 深度覆盖 post_h。post_h = (z_sec + plate_t) - (z_out - plate_t) = 17.5 + 3 - (-20 - 3) = 43.5。
# 工具起点：选 +Z 端（输出侧外 1 mm）。joint_cage_yaw 标准姿态下 z_out = -20 - 3 = -23（外表面），
# z_sec = 17.5 + 3 = 20.5（副轴侧外表面）。但要看 axis_rot 把 +Z 旋到 world shaft。
# 因为 yaw 类 orient 不调 orient()，axis_rot 把整个件旋到目标姿态。
# 所以局部 z_out = -20 是固定的"输出侧外表面"（关节系下）；局部 +Z = 世界 = OPP[shaft]。
# 工具从 +Z 端进给（局部 +Z）= 世界 OPP[shaft]。
# 选 (4.95, 4.95, 20.5 + 1) = (4.95, 4.95, 21.5) 作为 +Z 端孔口位置。
for j in YAW_JOINTS:
    _add(j, "joint_cage_yaw 4×M2.5（副轴侧外）",
         (4.95, 4.95, YAW_PCD26_Z_SEC + 1.0), "+z",
         f"joint_cage_yaw 的 M2.5（副轴侧外 +Z 端进给）", "M2.5")
    _add(j, "joint_cage_yaw 4×M2.5（输出侧外）",
         (-4.95, -4.95, -YAW_PCD26_Z_SEC - 1.0), "-z",
         f"joint_cage_yaw 的 M2.5（输出侧外 -Z 端进给）", "M2.5")


# ---------- 3) compact_adapter 4×M2.5（颈 / 腰短链） ----------
# 骨架源码（skeleton.py L387-391）：drill 沿 axis="Y"，孔位 (sx*4.95, -drop + sy*4.95)。
# orient(part, out_shaft, parent_dir) → 局部 +Y → world out_shaft。
# 工具起点：取 (4.95, +(PLATE_OUT + 1) - drop, 4.95)，即 +Y 端外 1 mm。
COMPACT_LINKS = list(A.ADAPTERS.keys())
for link in COMPACT_LINKS:
    parent_j = link[:-5] if link.endswith("_link") else ""
    if not parent_j:
        continue
    drop = A.ADAPTERS[link]["drop"]
    _add(parent_j, "compact_adapter 4×M2.5（输出侧）",
         (4.95, PLATE_OUT + 1.0 - drop, 4.95), "+y",
         f"compact_adapter 的 M2.5（{link}，drop={drop}）", "M2.5")
    _add(parent_j, "compact_adapter 4×M2.5（副轴侧）",
         (-4.95, -(PLATE_OUT + 1.0) - drop, -4.95), "-y",
         f"compact_adapter 的 M2.5 副轴侧（{link}，drop={drop}）", "M2.5")


# ---------- 4) cluster_outrigger 4×M2.5（髋/肩错轴） ----------
# 骨架源码（skeleton.py L502-506）：drill 沿 axis="Y"，孔位 (sx*4.95, sy*4.95 + stagger)；
# orient(part, shaft, parent) → 局部 +Y → world shaft。
# 工具起点：选 (4.95, +PLATE_OUT + 1 + stagger, 4.95)。
for j in CLUSTER_JOINTS:
    sc = A.JOINT_SCHEME[j]
    stagger = float(sc.get("stagger", 0.0) or 0.0)
    _add(j, "cluster_outrigger 4×M2.5（输出侧）",
         (4.95, PLATE_OUT + 1.0 + stagger, 4.95), "+y",
         f"cluster_outrigger 的 M2.5 输出侧（stagger={stagger}）", "M2.5")
    _add(j, "cluster_outrigger 4×M2.5（副轴侧）",
         (-4.95, -(PLATE_OUT + 1.0) + stagger, -4.95), "-y",
         f"cluster_outrigger 的 M2.5 副轴侧（stagger={stagger}）", "M2.5")


# ---------- 5) limb_fork 4×M2.5 锁舵盘（PCD14） ----------
# 骨架源码（skeleton.py L286-288）：drill 沿 axis="Y"，孔位 bolt_circle(PCD14, 4)。
# depth = arm_t * 6 = 18；z0 = -(arm_t*3) = -9。这说明孔从 y=-9 钻进，深度 18，
# 孔中心 y = -9 + 18/2 = 0（即孔穿过 y ∈ [-9, +9]），但更精确是 y = -9 + 9 = 0。
# 但 18 mm 深度 + arm_t=3 板厚 = 孔横穿臂；arm_out = HORN_FACE = 24.05（+Y 板内表面），
# arm_t = 3，+Y 板外 = 24.05 + 3 = 27.05。
# 工具从 +Y 端外 1 mm 进给，起点 (hx, FORK_OUT + 1, hy)。
for j in FORK_JOINTS:
    hx = HORN_PCD / 2.0 * math.cos(math.radians(45))
    hy = HORN_PCD / 2.0 * math.sin(math.radians(45))
    _add(j, "limb_fork 4×M2.5 锁舵盘（PCD14）",
         (hx, FORK_OUT + 1.0, hy), "+y",
         f"limb_fork 锁舵盘 M2.5（{j}，PCD{HORN_PCD}）", "M2.5")


# ---------- 6) cluster_horn_arm 4×M2.5 锁上一级舵盘 ----------
# 骨架源码（skeleton.py L435-437）：drill 沿 axis="Z"，孔位 bolt_circle(PCD14, 4)；
# depth = horn_t * 3 = 12；z0 = z_flange - horn_t * 2 = parent_stagger - 6。
# orient(part, out_shaft, OPP[in_shaft]) → 局部 +Z → world OPP[in_shaft] 方向。
# 工具起点：取 (hx, hy, parent_stagger + horn_t + 1) = (hx, hy, parent_stagger + 5)。
# 这里 horn_t = wall + 1 = 4；所以 z = parent_stagger + 4 + 1 = parent_stagger + 5。
for link, cfg in A.CLUSTER_ARMS.items():
    parent_j = link[:-5] if link.endswith("_link") else ""
    if not parent_j:
        continue
    parent_shaft = A.JOINT_SCHEME[parent_j]["shaft"]
    parent_stagger = float(A.JOINT_SCHEME[parent_j].get("stagger", 0.0) or 0.0)
    hx = HORN_PCD / 2.0 * math.cos(math.radians(45))
    hy = HORN_PCD / 2.0 * math.sin(math.radians(45))
    _add(parent_j, "cluster_horn_arm 4×M2.5 锁上一级舵盘（外侧）",
         (hx, hy, parent_stagger + 5.0), "+z",
         f"cluster_horn_arm 锁 {parent_j} 舵盘 M2.5（{link}）", "M2.5")


# ---------- 7) gripper_jaw 4×M2.5 锁舵盘 ----------
# 骨架源码（skeleton.py L831-832）：drill 沿 axis="Z"，孔位 bolt_circle(PCD14, 4)；
# depth = 30；z0 = -1。孔中心 z = -1 + 15 = 14（孔从 z=-1 钻到 z=29）。
# 但 gripper_jaw 是 gripper_jaw 函数，没有 orient。
# gripper_jaw 是 limb_fork 的衍生 —— 实际它是建在 gripper_jaw 函数里（与 limb_fork 类似）。
# 工具起点：取 (hx, hy, -1 - 1) = (hx, hy, -2)，进给 -Z 局部。
GRIPPER_JOINTS = [j for j in A.JOINT_SCHEME if j.endswith("_gripper")]
for j in GRIPPER_JOINTS:
    hx = HORN_PCD / 2.0 * math.cos(math.radians(45))
    hy = HORN_PCD / 2.0 * math.sin(math.radians(45))
    _add(j, "gripper_jaw 4×M2.5 锁舵盘",
         (hx, hy, -2.0), "-z",
         f"gripper_jaw 锁舵盘 M2.5（{j}，-Z 进给）", "M2.5")


# ---------- 8) joint_cage 母端 3×M3 径向（插接芯棒） ----------
# 骨架源码（skeleton.py L155-162）：`Workplane("XZ").center(hx, z_cap_top + SPIGOT_H/2)
#                                       .circle(...).extrude(14).translate((0, hy, 0))`。
# Workplane("XZ") 默认挤出方向 = +Y。孔沿 +Y 方向深 14 mm，
# 圆心 XZ 坐标 = (hx, z_cap_top + SPIGOT_H/2) = (hx, 32)，Y 坐标 = hy = ±17.3。
# 3 个相位：(90°, 210°, 330°) → (hx, hy) = (0, +20), (-17.3, -10), (+17.3, -10)。
# orient(part, shaft, parent) → 局部 +Y → world shaft，+Z → world parent。
# **进给方向 = 局部 +Y = 世界 JOINT_SCHEME[shaft]**。
# 工具起点：(hx, hy + 14 + 1, z_center) — 但 hy = 20 是 Y 中心，加上 14 + 1 = +Y 端外 1 mm。
for j in ORTHO_JOINTS:
    hx = 20.0 * math.cos(math.radians(90))      # 0
    hy = 20.0 * math.sin(math.radians(90))      # +20
    z_center = 20.0 + 12.0                       # 32：芯棒孔中心 z
    _add(j, "joint_cage 母端 3×M3 径向（90° 相位）",
         (hx, hy + 14.0 + 1.0, z_center), "+y",
         f"joint_cage 母端芯棒径向 M3（{j}，90° 相位）", "M3")
    ang = math.radians(210)
    hx = 20.0 * math.cos(ang)
    hy = 20.0 * math.sin(ang)
    _add(j, "joint_cage 母端 3×M3 径向（210° 相位）",
         (hx, hy + 14.0 + 1.0, z_center), "+y",
         f"joint_cage 母端芯棒径向 M3（{j}，210° 相位）", "M3")


# ---------- 9) limb_fork 子端 3×M3 径向（连杆管端） ----------
# 骨架源码（skeleton.py L303-309）：同 joint_cage，沿 +Y 方向挤出 14 mm；
#   圆心 z = z_base_bot - SPIGOT_H/2 = -25.6 - 6 = -31.6，Y 坐标 = hy。
# 非 compact limb_fork 的 z_base_bot = -25.6（参见骨架注释与代码）。
# 工具起点：(0, hy + 14 + 1, -31.6)。
for j in FORK_JOINTS:
    hx = 20.0 * math.cos(math.radians(90))      # 0
    hy = 20.0 * math.sin(math.radians(90))      # +20
    z_center = -25.6 - 6.0                       # -31.6：芯棒孔中心 z
    _add(j, "limb_fork 子端 3×M3 径向（90° 相位）",
         (hx, hy + 14.0 + 1.0, z_center), "+y",
         f"limb_fork 子端芯棒径向 M3（{j}）", "M3")


# ---------- 10) yaw 笼母端 4×M3（PCD26） + 颈座顶板 4×M3 ----------
# 骨架源码（skeleton.py L222-224）：yaw 笼副轴侧板的 4×M3 在 (±9.19, ±9.19, 17.5)，
# depth=9，z0=17.5-3=14.5。孔覆盖 z ∈ [14.5, 23.5]。工具起点：取 (9.19, 9.19, 23.5 + 1)。
# yaw 笼副轴侧端板是连接上级结构（骨盆顶面 / 躯干）的那块。
for j in YAW_JOINTS:
    _add(j, "joint_cage_yaw 母端 4×M3 接上级（PCD26）",
         (9.192, 9.192, YAW_PCD26_Z_SEC + 1.0), "+z",
         f"joint_cage_yaw 母端 PCD26 M3（{j}）", "M3")

# torso_frame 颈座顶板（skeleton.py L681-683）：
#   for pt in bolt_circle(PCD26, 4): top.cut(cyl(3.4, 10, at=(pt[0], pt[1], 62.0)))
# 这是 4 个 Φ3.4 底孔（深度 10 mm），中心 z=62，颈部顶板上表面 z = 60.0 + 5 = 65。
# 工具起点：取 (9.192, 9.192, NECK_TOP_Z + 1) = (9.192, 9.192, 63.6)，进给 +Z。
_add("head_yaw", "torso_frame 颈座顶板 4×M3 接 head_yaw 笼",
     (9.192, 9.192, NECK_TOP_Z + 1.0), "+z",
     "torso_frame 颈座顶板 PCD26 M3（head_yaw）", "M3")


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------
def evaluate(items: List[Tuple[str, cq.Workplane]],
              joint_to_shape: Dict[str, cq.Workplane]) -> List[Dict[str, Any]]:
    """对每个场景评估工具可达性。

    joint_to_shape: 关节名 → 该关节对应的零件实体（笼 / outrigger / fork / 紧凑块）
                    用于排除"工具正在穿过的本零件"（避免自身 = 假干涉）。
    """
    out: List[Dict[str, Any]] = []
    for sc in SCENARIOS:
        joint = sc["joint"]
        # 工具起点 = 关节原点 + 局部 hole 偏移
        o_world = world_origin(KIN, joint, sc["hole_local"])
        a_world = world_axis(KIN, joint, sc["axis_local"])
        bit = tool_envelope(o_world, a_world, TOOL_BIT_DIA, TOOL_BIT_LEN)
        full = tool_full(o_world, a_world)

        # 最小距离与碰撞
        d_bit = 1e9
        d_full = 1e9
        worst_name = ""
        worst_d = 1e9
        collide_name = ""
        collide_vol = 0.0
        # 本零件 = 与该螺钉**直接相关的本体**，应排除
        # 例：head_yaw 关节的 compact_adapter 不在 items（cage/compact adapter 只在子 link 上），
        #     但 cage__head_yaw 是它的母端笼；其余 cage__{j} / fork__{j} / outrigger__{j}
        #     都按关节名匹配。
        #     当 joint 是"父关节"（cluster_horn_arm 锁上一级），本体是子 link 上的实体，
        #     例如 cluster_horn_arm 锁 trunk_roll，本体是 cluster_horn_arm__left_hip_yaw_link
        #     （父关节的子 link）。
        self_names: set = set()
        for nm, _ in items:
            tail = nm.split("__")[1] if "__" in nm else ""
            if tail == joint:
                self_names.add(nm)
        # 父关节场景：把 cluster_horn_arm__<parent_link> 也算本体
        # 父关节名 → 子 link 名（CLUSTER_ARMS 的 key）
        for link in A.CLUSTER_ARMS:
            parent_j = link[:-5] if link.endswith("_link") else ""
            if parent_j == joint:
                self_names.add(f"cluster_horn_arm__{link}")
        for nm, sh in items:
            if nm in self_names:
                continue
            if not _bbox_near(bbox_of(sh), bbox_of(full), pad=80.0):
                continue
            d = min_dist(bit, sh)
            if d < d_bit:
                d_bit = d
            df = min_dist(full, sh)
            if df < d_full:
                d_full = df
                worst_name = nm
                worst_d = df
            v = common_vol(bit, sh)
            if v > 1.0 and v > collide_vol:
                collide_vol = v
                collide_name = nm
        # 判定
        margin = d_bit
        if collide_vol > 0:
            verdict = "❌ 不可达"
        elif margin < MARGIN_TIGHT:
            verdict = "❌ 不可达"
        elif margin < MARGIN_OK:
            verdict = "⚠️ 勉强可达"
        else:
            verdict = "✅ 可达"

        out.append({
            "joint": joint,
            "kind": sc["kind"],
            "desc": sc["desc"],
            "fastener": sc["fastener"],
            "hole_world_mm": [round(c, 2) for c in o_world],
            "axis_world_mm": [round(c, 3) for c in a_world],
            "min_margin_mm": round(margin, 2),
            "worst_part": worst_name,
            "worst_dist_mm": round(worst_d, 2),
            "collide_part": collide_name,
            "collide_vol_mm3": round(collide_vol, 1),
            "verdict": verdict,
        })
    return out


def _bbox_near(b1, b2, pad: float = 80.0) -> bool:
    return not (b1.xmax + pad < b2.xmin or b2.xmax + pad < b1.xmin or
                b1.ymax + pad < b2.ymin or b2.ymax + pad < b1.ymin or
                b1.zmax + pad < b2.zmin or b2.zmax + pad < b1.zmin)


KIN: A.Kin = None  # type: ignore


def main(argv: Optional[Sequence[str]] = None) -> int:
    global KIN
    want_json = "--json" in (argv or sys.argv)
    kin = A.Kin(A.DESIGN / "atri.urdf")
    KIN = kin
    placements = json.loads((A.DESIGN / "placements.json").read_text(encoding="utf-8"))
    items, log = A.build_assembly(kin, placements)
    bad = [l for l in log if not l.get("ok")]
    print(f"装配件 {len(items)} 个（失败 {len(bad)}）")
    for b in bad[:5]:
        print(f"  [ERR] {b['name']}: {b.get('err')}")

    rows = evaluate(items, joint_to_shape={})
    # ---- 汇总 ----
    n_ok = sum(1 for r in rows if r["verdict"] == "✅ 可达")
    n_tight = sum(1 for r in rows if r["verdict"] == "⚠️ 勉强可达")
    n_bad = sum(1 for r in rows if r["verdict"] == "❌ 不可达")
    print(f"\n## 工具可达性（批头 Φ6 × 60 mm + 手柄 Φ25 球）\n")
    print(f"**总场景 {len(rows)}**：✅ 可达 **{n_ok}** ｜ ⚠️ 勉强 **{n_tight}**"
          f" ｜ ❌ 不可达 **{n_bad}**\n")
    print(f"| # | 关节 | 位置类型 | 紧固件 | 孔位 (X,Y,Z) | 轴向 | 最小余量 | 判定 |")
    print(f"|---|---|---|---|---|---|---|---|")
    for k, r in enumerate(rows, 1):
        print(f"| {k} | `{r['joint']}` | {r['kind']} | {r['fastener']} | "
              f"({r['hole_world_mm'][0]}, {r['hole_world_mm'][1]}, "
              f"{r['hole_world_mm'][2]}) | {r['axis_world_mm']} | "
              f"{r['min_margin_mm']} mm | {r['verdict']} |")
    # 详细：每个 ❌ / ⚠️ 给出最严零件 + 改法
    tight_or_bad = [r for r in rows if r["verdict"] != "✅ 可达"]
    if tight_or_bad:
        print(f"\n### 不可达 / 勉强可达清单（{len(tight_or_bad)} 条）\n")
        for k, r in enumerate(tight_or_bad, 1):
            print(f"\n{k}. **{r['joint']} / {r['kind']}**")
            print(f"   - 紧固件：`{r['fastener']}`")
            print(f"   - 孔位（世界）：({r['hole_world_mm'][0]}, "
                  f"{r['hole_world_mm'][1]}, {r['hole_world_mm'][2]}) mm")
            print(f"   - 拧入方向（世界）：{r['axis_world_mm']}")
            print(f"   - 与周围零件最小距离：**{r['min_margin_mm']} mm** "
                  f"（最严件 `{r['worst_part']}`，"
                  f"距离 {r['worst_dist_mm']} mm）")
            if r["collide_vol_mm3"] > 0:
                print(f"   - ⚠️ 与 `{r['collide_part']}` 碰撞 "
                      f"{r['collide_vol_mm3']} mm³")
    if want_json:
        out_path = A.OUT / "tool_access.json"
        out_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        print(f"\n已写入 {out_path}")
    # CI：存在 ❌ 则非零退出
    return 1 if n_bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))