"""3D 打印件骨架结构：零件库（CadQuery / OpenCASCADE 真 B-rep）。

设计原则（与 `standards.py` 的 ASSEMBLY 章、`kit.py` 的 IF 表配套）：

1. **骨架不是盒子**：所有大件都是"框 + 筋 + 减重窗"，不是闭合薄壳。
   闭合薄壳按 3 mm 壁算，一个 100×90×55 的躯干壳就是 137 g，
   而 v2 给整机结构的预算是 **500 g / 23 个 link** —— 壳体方案必然超支。
2. **模块化**：22 个自由度只用 4 类结构件覆盖
   （关节笼 `joint_cage` + 连杆叉 `limb_fork` + 连杆管 `limb_tube` + 紧凑转接块 `compact_adapter`）。
3. **接口固定**：所有连接面尺寸取自 `kit.IF`，零件里不出现魔数。
4. **能买不打印**：主轴舵盘、踝/膝 U 型传动架按 `ASSEMBLY.buy_metal_not_print` 走商品件。

坐标系约定（全库统一）：
    标准姿态 = 舵机输出轴沿 **+Y**，母端接口朝 **+Z**，子端连杆朝 **−Z**。
    `joint_cage()` / `limb_fork()` 用 `kit.orient()` 旋到真实姿态。
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

import cadquery as cq

from kit import (FDM, IF, MATERIALS, bolt_circle, box, bosses, cyl, drill,
                 needs_support, orient, part_report, plate, printed_mass,
                 safe_chamfer, safe_fillet, servo_axis_offset_mm, tube)
from parts import sanitize
from standards import (ASSEMBLY, WIRING, bearing, fastener, servo,
                       servo_horn_interface)

SERVO_NAME = "STS3215"

# --------------------------------------------------------------------------
# 舵机几何（所有关节模块的唯一真值来源）
# --------------------------------------------------------------------------
S = servo(SERVO_NAME)
L_S, W_S, H_S = S["body_mm"]          # 45.2 / 24.7 / 35.0
GAP = W_S + FDM["servo_cavity_clearance_mm"]     # 两侧板净距 25.2
AXIS_DZ = servo_axis_offset_mm(SERVO_NAME)       # 6.5：轴线在几何中心上方
Z_TOP = H_S / 2.0 - AXIS_DZ                      # 11.0：机体上表面（轴线为 0）
Z_BOT = -H_S / 2.0 - AXIS_DZ                     # -24.0：机体下表面
X_HALF = L_S / 2.0                               # 22.6
Y_HALF = W_S / 2.0                               # 12.35
PLATE_T = FDM["wall_mm"]                         # 3.0
PLATE_Y = GAP / 2.0 + PLATE_T / 2.0              # 14.1：两侧板中心
SPAN_X = 52.0                                    # 侧板长（含端部包边）
SPIGOT_D, SPIGOT_H, SPIGOT_BORE = 34.0, 14.0, 24.0


# --------------------------------------------------------------------------
# 零件 1：关节笼（母端）—— 夹住舵机机体，坐在上一级结构上
# --------------------------------------------------------------------------
def joint_cage(shaft: str = "+y", parent: str = "+z",
               wall: float = PLATE_T, lighten: bool = True) -> cq.Workplane:
    """舵机笼：把舵机固定到**上一级 link**，并给副轴提供第二个支撑点。

    载荷路径：舵机反扭矩 → 底部 4×M2.5（拧进舵机自带底孔）
              → 侧板 → 母端接口（Ø34 插接芯棒 + 3×M3 径向螺钉）→ 上级结构。

    为什么用"插接芯棒 + 径向螺钉"而不是法兰螺栓：
    舵机笼的横截面只有 52×31，放不下 Φ40 连杆的 4×M3 端面螺栓
    （孔要落在 r>20 才在管壁外，而笼宽 ±15.6）。插接 + 径向螺钉
    同时解决了连接刚度和"连杆可现场截长"两个问题。
    """
    z_floor_top = Z_BOT                      # 舵机底面
    z_floor_bot = z_floor_top - wall
    z_cap_bot = Z_TOP + 2.0                  # 顶板与舵机之间留 2 mm 散热缝
    z_cap_top = z_cap_bot + wall + 2.0       # 顶板兼作母端插接座

    part = cq.Workplane("XY")

    # --- 两侧板（⊥ 输出轴）---
    for sign in (-1, 1):
        p = box(SPAN_X, wall, z_cap_top - z_floor_bot,
                at=(0, sign * PLATE_Y, z_floor_bot))
        part = part.union(p)

    # --- 底板（舵机坐在上面，4 个 M2.5 从下方拧进舵机底孔）---
    part = part.union(box(SPAN_X, GAP + 2 * wall, wall,
                          at=(0, 0, z_floor_bot)))

    # --- 顶板（母端接口的基座 + 抗扭）---
    part = part.union(box(SPAN_X, GAP + 2 * wall, wall,
                          at=(0, 0, z_cap_bot)))

    # --- 母端插接芯棒（Φ34 h9 → Φ40 连杆管内孔）---
    part = part.union(cyl(SPIGOT_D, SPIGOT_H,
                          at=(0, 0, z_cap_top)))
    part = part.cut(cyl(SPIGOT_BORE, SPIGOT_H + 2, at=(0, 0, z_cap_top - 1)))

    # --- 输出侧（+Y 板）：让 Ø20 金属舵盘穿出的避空 ---
    horn_clear = servo_horn_interface(SERVO_NAME)["spline_od_mm"]
    part = part.cut(cyl(horn_clear + 20.0, PLATE_T * 4, at=(0, 0, 0), axis="Y")
                    .translate((0, PLATE_Y - PLATE_T * 2, 0)))

    # --- 副轴侧（−Y 板）：MF106ZZ 压入孔 + 法兰沉台 ---
    b = bearing(IF["secondary_shaft"]["bearing"])
    bore = b["od_mm"] + FDM["bearing_bore_interference_mm"]
    part = part.cut(cyl(bore, PLATE_T * 4, at=(0, -PLATE_Y - PLATE_T * 2, 0),
                        axis="Y"))
    if {"flange_od_mm", "flange_width_mm"} <= set(b):
        part = part.cut(cyl(b["flange_od_mm"] + FDM["clearance_snug_mm"],
                            b["flange_width_mm"] + 0.2,
                            at=(0, -PLATE_Y - PLATE_T / 2.0, 0), axis="Y")
                        .translate((0, -0.1, 0)))

    # --- 舵机底部 4×M2.5 通孔（拧进舵机自带底孔，pitch 38×15）---
    pitch = S["bottom_hole_pitch_mm"]
    part = drill(part, [(sx * pitch[0] / 2.0, sy * pitch[1] / 2.0)
                        for sx in (-1, 1) for sy in (-1, 1)],
                 dia=fastener("M2.5")["clearance_hole_mm"],
                 depth=wall * 3, z0=z_floor_bot - wall)

    # --- 母端插接芯棒的 3×M3 径向螺钉（120°，攻丝底孔，现场攻丝或热熔）---
    for i in range(3):
        ang = math.radians(90 + 120 * i)
        hx, hy = 20.0 * math.cos(ang), 20.0 * math.sin(ang)
        hole = (cq.Workplane("XZ").center(hx, z_cap_top + SPIGOT_H / 2.0)
                .circle(fastener("M3")["tap_drill_mm"] / 2.0)
                .extrude(14.0).translate((0, hy, 0)))
        part = part.cut(hole)

    # --- 减重窗 ---
    if lighten:
        for sign in (-1, 1):
            for dx in (-13.0, 0.0, 13.0):
                part = part.cut(box(11.0, wall * 4, 30.0,
                                    at=(dx, sign * PLATE_Y, z_floor_bot + 8.0)))

    part = safe_fillet(part, FDM["fillet_struct_mm"], "|Y")
    part = orient(part, shaft, parent)
    return sanitize(part)


# --------------------------------------------------------------------------
# 零件 1b：偏转关节笼（轴 Z，母端在同一轴线上 —— 退化情形）
# --------------------------------------------------------------------------
def joint_cage_yaw(parent: str = "+z", shaft: str = "+z",
                   wall: float = PLATE_T) -> cq.Workplane:
    """偏转（yaw）关节笼：输出轴与母端同轴，不能走 `orient()` 的通用路径。

    用于 `hip_yaw ×2` 与 `head_yaw`（3 个关节）。
    结构：上下两块 ⊥Z 板 + 4 根角柱；**母端侧那块板同时是副轴轴承座**
    （舵机副轴 Φ6 从机体另一端伸出，正好被这块板里的 MF106ZZ 支住，
    形成双支点）；输出侧那块板开 Ø21 让金属舵盘与子端叉的螺栓通过。
    舵机本体的 4×M2.5 是从 ±Y 侧拧进舵机底面螺孔的，所以侧向必须留出批头空间。
    """
    part = cq.Workplane("XY")
    z_out = -Y_HALF - 0.25          # 输出面（−Z）
    z_sec = +Y_HALF + 0.25          # 副轴面（+Z）

    plate_t = wall
    span_x, span_y = 56.0, 46.0

    # 输出侧板（开 Ø21 舵盘避空）
    part = part.union(box(span_x, span_y, plate_t, at=(0, 0, z_out - plate_t)))
    part = part.cut(cyl(21.0, plate_t * 3, at=(0, 0, z_out - plate_t * 2)))
    # 母端侧板（副轴轴承 + 4×M3 与骨架对接）
    part = part.union(box(span_x, span_y, plate_t, at=(0, 0, z_sec)))
    b = bearing(IF["secondary_shaft"]["bearing"])
    part = part.cut(cyl(b["od_mm"] + FDM["bearing_bore_interference_mm"],
                        plate_t * 3, at=(0, 0, z_sec - plate_t)))
    part = drill(part, bolt_circle(IF["cage_flange"]["pcd_mm"], 4),
                 dia=IF["cage_flange"]["hole_dia_mm"], depth=plate_t * 3,
                 z0=z_sec - plate_t)
    # 4 根角柱
    for sx in (-1, 1):
        for sy in (-1, 1):
            part = part.union(box(8.0, 8.0, 2 * z_sec + 2 * plate_t - 1.0,
                                  at=(sx * (span_x / 2 - 4.0),
                                      sy * (span_y / 2 - 4.0), z_out - plate_t)))
    part = safe_fillet(part, FDM["fillet_min_mm"], "|Z")
    if parent == "-z":                      # 翻转：母端朝下（head_yaw 装在躯干下方）
        part = part.rotate((0, 0, 0), (1, 0, 0), 180)
    # 输出轴方向：标准建模为 +Z（母端朝 −Z 时已翻转）→ 旋到目标轴
    axis_rot = {"+z": ((0, 0, 1), 0.0), "-z": ((1, 0, 0), 180.0),
                "+y": ((1, 0, 0), -90.0), "-y": ((1, 0, 0), 90.0),
                "+x": ((0, 1, 0), 90.0), "-x": ((0, 1, 0), -90.0)}
    ax, ang = axis_rot[shaft]
    if ang:
        part = part.rotate((0, 0, 0), ax, ang)
    return sanitize(part)


# --------------------------------------------------------------------------
# 零件 2：连杆叉（子端）—— 被舵盘驱动，接下一根连杆管
# --------------------------------------------------------------------------
def limb_fork(shaft: str = "+y", parent: str = "+z",
              wall: float = PLATE_T, compact: bool = False,
              spigot: bool = True) -> cq.Workplane:
    """连杆叉：一侧螺栓锁在金属舵盘上，另一侧套在副轴轴承上，底部接连杆管。

    **为什么必须两侧都接**：舵机输出轴单侧悬臂，落地的交变弯矩全部由
    输出轴轴承承担，齿轮箱会早期磨损。副轴侧加一个 MF106ZZ 后，
    弯矩由两个支点分担（第二个支点就是笼子 −Y 板里的轴承）。
    """
    horn = servo_horn_interface(SERVO_NAME)
    b = bearing(IF["secondary_shaft"]["bearing"])

    horn_face = Y_HALF + S["horn_disc_thickness_mm"]         # 16.35 舵盘外表面
    arm_out = horn_face + 0.05
    arm_t = wall

    z_top = (Z_TOP + 2.0) if not compact else 16.0
    z_base_top = (Z_BOT - 12.0) if not compact else -13.0    # 紧凑型只跨过轴线
    z_base_bot = z_base_top - wall

    part = cq.Workplane("XY")

    # --- 臂 A：螺栓锁舵盘（4×M2.5 走 PCD14）---
    arm_a = box(34.0, arm_t, z_top - z_base_bot,
                at=(0, arm_out + arm_t / 2.0, z_base_bot))
    part = part.union(arm_a)
    part = drill(part, bolt_circle(horn["pcd_mm"], horn["hole_count"]),
                 dia=IF["horn"]["hole_dia_mm"], depth=arm_t * 6,
                 z0=-(arm_t * 3), axis="Y")
    part = part.cut(cyl(26.0, arm_t * 4,
                        at=(0, arm_out - arm_t * 2, 0), axis="Y"))

    # --- 臂 B：Φ5.96 h7 轴颈，插进笼子里的轴承内圈 ---
    arm_b_out = -(Y_HALF + b["width_mm"] + 0.4 + arm_t)
    part = part.union(box(34.0, arm_t, z_top - z_base_bot,
                          at=(0, arm_b_out + arm_t / 2.0, z_base_bot)))
    part = part.union(cyl(S["secondary_shaft_dia_mm"] - 0.04,
                          b["width_mm"] + 2.6,
                          at=(0, arm_b_out + arm_t - 1.0, 0), axis="Y"))

    # --- 底座：跨过舵机下方，接子端插接芯棒 ---
    part = part.union(box(38.0, abs(arm_out + arm_t - arm_b_out),
                          wall, at=(0, (arm_out + arm_t + arm_b_out) / 2.0,
                                    z_base_bot)))
    if spigot:
        part = part.union(cyl(SPIGOT_D, SPIGOT_H, at=(0, 0, z_base_bot - SPIGOT_H)))
        part = part.cut(cyl(SPIGOT_BORE, SPIGOT_H + 2,
                            at=(0, 0, z_base_bot - SPIGOT_H - 1)))
        for i in range(3):
            ang = math.radians(90 + 120 * i)
            hx, hy = 20.0 * math.cos(ang), 20.0 * math.sin(ang)
            part = part.cut(
                cq.Workplane("XZ").center(hx, z_base_bot - SPIGOT_H / 2.0)
                .circle(fastener("M3")["tap_drill_mm"] / 2.0)
                .extrude(14.0).translate((0, hy, 0)))

    part = safe_fillet(part, FDM["fillet_min_mm"], "|Y")
    part = orient(part, shaft, parent)
    return sanitize(part)


# --------------------------------------------------------------------------
# 零件 3：连杆管
# --------------------------------------------------------------------------
def limb_tube(length: float = 62.8, lighten: bool = True,
              z0: float = 0.0) -> cq.Workplane:
    """Φ40 / Φ34 承力连杆管：两端插接，径向 3×M3 锁紧。

    管子是**定长件里最容易改的一件**：现场锯短 → 重新打 3 个 Φ3.2 孔即可。
    管身减重窗同时是走线检查窗。
    """
    od = IF["tube"]["od_mm"]
    idia = SPIGOT_D + 0.2                     # 与芯棒留 0.1 单边间隙
    body = tube(od, idia, length, at=(0, 0, 0))
    if lighten:
        for sign in (-1, 1):
            win = (cq.Workplane("XZ")
                   .center(sign * od / 2.0, length / 2.0)
                   .slot2D(length * 0.42, od * 0.26).extrude(od))
            body = body.cut(win)
    for z in (6.0, length - 6.0):
        for i in range(3):
            ang = math.radians(90 + 120 * i)
            body = body.cut(
                cq.Workplane("XZ").center(20.0 * math.cos(ang), z)
                .circle(fastener("M3")["clearance_hole_mm"] / 2.0)
                .extrude(14.0).translate((0, 20.0 * math.sin(ang), 0)))
    if z0:
        body = body.translate((0, 0, z0))
    return sanitize(body)


# --------------------------------------------------------------------------
# 零件 4：紧凑转接块（髋/肩/腰的短链节）
# --------------------------------------------------------------------------
def compact_adapter(in_shaft: str = "+z", out_shaft: str = "+x",
                    drop: float = 19.6, wall: float = PLATE_T
                    ) -> cq.Workplane:
    """紧凑转接块：**锁上一级舵盘 → 托住下一级舵机**，两轴相距 19.6 mm。

    用于关节间距只有 19.6 mm 的短链节（hip_yaw→hip_roll、hip_roll→hip_pitch、
    shoulder_pitch→shoulder_roll、trunk_roll→trunk_pitch）与 27.5 mm 的颈节。
    这种间距放不下连杆管，必须做成一体的 L 形块。

    ⚠️ 这是全机**最挤**的零件（舵机 45.2 mm 长要塞进 37 mm 级包络），
    细节形体建议按 `design/handoff/复杂形体设计Prompt.md` 交给
    SolidWorks / 强模型做二次深化。
    """
    part = cq.Workplane("XY")

    # 输入侧：扣在上一级舵盘上（PCD14）
    horn_t = wall + 1.0
    part = part.union(box(34.0, 30.0, horn_t, at=(0, 0, -horn_t)))
    part = drill(part, bolt_circle(IF["horn"]["pcd_mm"], 4),
                 dia=IF["horn"]["hole_dia_mm"], depth=horn_t * 3,
                 z0=-horn_t * 2)
    part = part.cut(cyl(26.0, horn_t * 3, at=(0, 0, -horn_t * 1.5)))

    # 立板：从舵盘面下探 drop，转 90° 托住下一级
    part = part.union(box(34.0, wall, drop + horn_t + 12.0,
                          at=(0, -15.0 + wall / 2.0, -horn_t - drop - 12.0)))

    # 输出侧：托住下一级舵机（两侧板 + 底板，舵机从 +X 滑入）
    out_top = -drop + Z_TOP
    out_bot = -drop + Z_BOT
    span = 46.0
    for sign in (-1, 1):
        part = part.union(box(span, wall, out_top - out_bot + 6.0,
                              at=(0, sign * PLATE_Y, out_bot - 3.0)))
    part = part.union(box(span, 2 * PLATE_Y + wall, wall, at=(0, 0, out_bot - wall)))
    pitch = S["bottom_hole_pitch_mm"]
    part = drill(part, [(sx * pitch[0] / 2.0, sy * pitch[1] / 2.0)
                        for sx in (-1, 1) for sy in (-1, 1)],
                 dia=fastener("M2.5")["clearance_hole_mm"],
                 depth=wall * 3, z0=out_bot - wall * 2)
    # 输出侧轴承位（副轴第二支点）
    b = bearing(IF["secondary_shaft"]["bearing"])
    part = part.cut(cyl(b["od_mm"] + FDM["bearing_bore_interference_mm"],
                        wall * 4, at=(0, PLATE_Y - wall * 2, -drop), axis="Y"))

    part = safe_fillet(part, FDM["fillet_min_mm"], "|Y")
    part = orient(part, out_shaft, {"+z": "-z", "-z": "+z"}.get(in_shaft, in_shaft))
    return sanitize(part)


# --------------------------------------------------------------------------
# 零件 5：骨盆框架（下半身中枢）
# --------------------------------------------------------------------------
def pelvis_frame(wall: float = PLATE_T) -> cq.Workplane:
    """骨盆：**3 只舵机 + IMU + 分线板**的集中座，是整机走线拓扑的根。

    布局（pelvis link 系）：
        trunk_roll   舵机 (0, 0, +19.6) 轴 X   → 躯干
        左右 hip_yaw 舵机 (±45, −19.6)  轴 Z   → 大腿
        IMU (0, 0, +8) 贴重心，避免头部摆动干扰姿态解算
        分线板 = 4 路菊花链的物理根节点（standards.WIRING）

    轻量化取舍：**不做闭合壳、不做整块底板**，用 4 根 10×10 立柱 + 上下横梁
    ＋侧翼盒。闭合壳按 3 mm 壁算要 137 g，而骨盆预算只有 45 g。
    """
    part = cq.Workplane("XY")
    body_l, body_w, body_h = 96.0, 76.0, 34.0

    # --- 四立柱（10×10 空心腔由走线孔贯通）---
    for sx in (-1, 1):
        for sy in (-1, 1):
            part = part.union(box(10.0, 10.0, body_h,
                                  at=(sx * (body_l / 2 - 5.0),
                                      sy * (body_w / 2 - 5.0), -body_h / 2)))
    # --- 上环 + 下横梁（不封底，留出髋部舵机与走线空间）---
    part = part.union(box(body_l, body_w, wall, at=(0, 0, body_h / 2 - wall)))
    for sy in (-1, 1):
        part = part.union(box(body_l, wall, 10.0, at=(0, sy * (body_w / 2 - 5.0),
                                                       -body_h / 2 + 5.0)))
    part = part.union(box(wall, body_w, 10.0, at=(body_l / 2 - wall, 0,
                                                  -body_h / 2 + 5.0)))

    # --- 上表面：trunk_roll 舵机笼的 Ø34 插接座（轴 X）---
    part = part.union(box(34.0, 34.0, 8.0, at=(0, 0, body_h / 2)))
    part = part.union(cyl(SPIGOT_D, 12.0, at=(0, 0, -6.0), axis="X")
                      .translate((0, 0, 19.6 - body_h / 2 + 4.0)))

    # --- 左右翼：hip_yaw 舵机笼座（轴 Z，向下）---
    for sign in (-1, 1):
        part = part.union(box(46.0, 30.0, 9.0, at=(0, sign * 45.0, -14.0)))
        part = part.union(cyl(SPIGOT_D, 12.0, at=(0, sign * 45.0, -21.6)))

    # --- IMU 座 ---
    part = part.union(box(22.0, 18.0, 2.5, at=(0, 0, 6.0)))
    for pt in bolt_circle(16.0, 4):
        part = part.union(bosses([pt], od=4.5, height=5.0, bore_dia=1.6,
                                 bore_depth=6.0, z0=5.0))

    # --- 分线板座（4 路菊花链的根）---
    part = part.union(box(42.0, 28.0, 2.5, at=(0, 0, -body_h / 2 + 6.0)))

    # --- 走线与减重孔 ---
    for sy in (-1, 1):
        part = part.cut(cyl(8.5, 40.0, at=(18.0, sy * 28.0, -body_h / 2)))
    for dx in (-30.0, 30.0):
        part = part.cut(box(16.0, 40.0, 20.0, at=(dx, 0, -4.0), centered_z=True))

    part = safe_fillet(part, FDM["fillet_struct_mm"], "|Z")
    return sanitize(part)


# --------------------------------------------------------------------------
# 零件 6：躯干框架（上半身中枢）
# --------------------------------------------------------------------------
def torso_frame(wall: float = PLATE_T) -> cq.Workplane:
    """躯干：**树莓派 + 电池 + 3 块电控板 + 双肩 + 颈柱**的集成框架。

    竖向布局（torso_upper link 系，原点 = trunk_pitch 关节）：
        z ∈ [−27, +27]   主舱：电池仓在下、电控托盘在上、树莓派悬于中部
        z ∈ [+27, +78]   胸段 + 颈柱，把 head_yaw 舵机顶到 z = 82.4
        y = ±75          双肩 pylon（shoulder_pitch 舵机笼座）

    ⚠️ 原模型里躯干顶面（z=+27.5）到头部偏航关节（z=82.4）之间有 **55 mm 结构空白**，
    这段"脖子"必须由骨架补上，否则头是悬空的——这是 v2 基元模型看不到的问题。
    """
    part = cq.Workplane("XY")
    tl, tw, th = 96.0, 86.0, 54.0
    z_lift = 17.0                     # 主舱底面抬到叉的上方

    # --- 底部：trunk_pitch 舵盘面（自带紧凑叉，子端朝上）---
    part = part.union(limb_fork(shaft="+y", parent="-z", compact=True,
                                spigot=False))

    # --- 主舱：4 立柱 + 上环 + 前后横梁 ---
    for sx in (-1, 1):
        for sy in (-1, 1):
            part = part.union(box(11.0, 11.0, th, at=(sx * (tl / 2 - 5.5),
                                                       sy * (tw / 2 - 5.5), z_lift),
                                  centered_z=True))
    part = part.union(box(tl, tw, wall, at=(0, 0, z_lift + th / 2 - wall)))
    for sx in (-1, 1):
        part = part.union(box(wall, tw, 12.0, at=(sx * (tl / 2 - wall), 0, z_lift),
                              centered_z=True))

    # --- 树莓派托盘（85 边沿 Y）+ 4×M2.5 柱（58×49）---
    rpi_z = z_lift - 8.0
    part = part.union(box(64.0, 88.0, 2.6, at=(0, 0, rpi_z - 2.6)))
    for sx in (-1, 1):
        for sy in (-1, 1):
            part = part.union(bosses([(sx * 29.0, sy * 24.5)], od=5.5, height=5.0,
                                     bore_dia=2.2, bore_depth=5.0, z0=rpi_z - 1.0))
    for dx in (-20.0, 0.0, 20.0):
        part = part.cut(box(14.0, 20.0, 6.0, at=(dx, 0, rpi_z - 3.0)))

    # --- 电控托盘（z=+14），与立柱搭接 ---
    part = part.union(box(88.0, 68.0, 2.6, at=(0, 0, z_lift + 14.0)))
    for dx in (-28.0, 0.0, 28.0):
        part = part.cut(box(16.0, 16.0, 6.0, at=(dx, 24.0, z_lift + 14.0)))

    # --- 电池框：88×34×19，从 −X 后背插入 ---
    bat_z = z_lift - 29.0
    part = part.union(box(40.0, 92.0, 2.6, at=(0, 0, bat_z)))
    for sx in (-1, 1):
        part = part.union(box(28.0, 92.0, 2.6, at=(sx * 31.0, 0, bat_z)))
    for sy in (-1, 1):
        part = part.union(box(40.0, 2.6, 22.0, at=(0, sy * 45.0, bat_z + 12.0)))
    part = part.union(box(2.6, 92.0, 22.0, at=(19.0, 0, bat_z + 12.0)))
    for dx in (-11.0, 11.0):
        part = part.cut(box(3.0, 96.0, 3.0, at=(dx, 0, bat_z - 1.0)))

    # --- 双肩 pylon（薄壳 + Ø34 笼座，轴 Y）---
    for sign in (-1, 1):
        part = part.union(box(40.0, 26.0, 34.0, at=(0, sign * 54.0, z_lift + 11.8),
                              centered_z=True))
        part = part.union(cyl(SPIGOT_D, 14.0, at=(0, sign * 66.0, z_lift + 11.8), axis="Y"))
        part = part.cut(box(22.0, 20.0, 22.0, at=(0, sign * 54.0, z_lift + 11.8),
                            centered_z=True))

    # --- 胸段 + 颈柱：升到 head_yaw（z = 82.4）---
    part = part.union(box(70.0, 58.0, 6.0, at=(0, 0, z_lift + th / 2 - 3.0)))
    for sx in (-1, 1):
        for sy in (-1, 1):
            part = part.union(box(9.0, 9.0, 52.0, at=(sx * 29.0, sy * 22.0,
                                                       z_lift + th / 2 + 25.0),
                                  centered_z=True))
    part = part.union(box(70.0, 52.0, wall, at=(0, 0, z_lift + th / 2 + 48.0)))
    part = part.union(cyl(SPIGOT_D, 10.0, at=(0, 0, z_lift + th / 2 + 48.0 + wall)))
    for sy in (-1, 1):
        part = part.cut(box(56.0, 16.0, 34.0, at=(0, sy * 20.0, z_lift + th / 2 + 24.0)))

    part = safe_fillet(part, FDM["fillet_min_mm"], "|Z")
    return sanitize(part)


# --------------------------------------------------------------------------
# 零件 7：头壳
# --------------------------------------------------------------------------
def head_shell(wall: float = 2.4) -> cq.Workplane:
    """头壳：**摄像头 + 麦克风 + 随动俯仰**的一体壳。

    底面自带连杆叉（锁 head_pitch 舵盘 + 套副轴轴承），所以头部
    不是"挂在脖子上"，而是被两个支点夹住——摔倒时不会掰断舵机轴。
    """
    part = cq.Workplane("XY")
    hl, hw, hh = 76.0, 68.0, 43.0
    z0 = 22.0                                  # 头壳相对 head_pitch 轴线抬高

    # --- 壳身：前脸 + 顶 + 侧壁（后部开口散热走线）---
    part = part.union(box(hl, hw, wall, at=(0, 0, z0 - hh / 2)))         # 底
    part = part.union(box(hl, hw, wall, at=(0, 0, z0 + hh / 2 - wall)))  # 顶
    part = part.union(box(wall, hw, hh, at=(hl / 2 - wall, 0, z0 - hh / 2)))
    for sign in (-1, 1):
        part = part.union(box(hl, wall, hh, at=(0, sign * (hw / 2 - wall / 2),
                                                z0 - hh / 2)))

    # --- 摄像头座：前脸 Ø38 模组，镜头 Ø18 外露 ---
    part = part.union(box(6.0, 44.0, 44.0, at=(hl / 2 - 3.0, 0, z0 + 6.0),
                          centered_z=True))
    part = part.cut(cyl(18.5, 14.0, at=(hl / 2 - 6.0, 0, z0 + 6.0), axis="X"))
    part = part.cut(box(20.0, 40.0, 17.0, at=(hl / 2 - 12.0, 0, z0 + 6.0),
                        centered_z=True))

    # --- 麦克风座（底部前缘）---
    part = part.union(box(28.0, 18.0, 8.0, at=(6.0, 0, z0 - hh / 2 - 4.0)))
    part = part.cut(box(26.0, 16.0, 3.0, at=(6.0, 0, z0 - hh / 2 - 6.0)))

    # --- 扬声器孔（侧面阵列）---
    for sign in (-1, 1):
        for i in range(3):
            part = part.cut(cyl(4.0, wall * 4,
                                at=(sign * 12.0, sign * hw / 2, z0 + 8.0),
                                axis="Y").translate((0, -0.5 * sign, 0)))
        for i in range(3):
            part = part.cut(cyl(4.0, wall * 4,
                                at=(sign * 4.0, sign * hw / 2, z0 + 16.0),
                                axis="Y").translate((0, -0.5 * sign, 0)))

    # --- 底部：head_pitch 连杆叉（舵盘 + 副轴）---
    fork = limb_fork(shaft="+y", parent="+z")
    part = part.union(fork.translate((0, 0, z0 - hh / 2 - 3.0)))

    part = safe_fillet(part, 3.0, "|Z")
    return sanitize(part)


# --------------------------------------------------------------------------
# 零件 8：足板（含踝部叉）
# --------------------------------------------------------------------------
def foot_plate(length: float = 110.0, width: float = 60.0, sole_t: float = 3.5,
               rib_h: float = 11.0) -> cq.Workplane:
    """足底板：踝关节在足底后 1/3，**紧凑俯仰叉 + 薄板 + 放射筋 + 大掏空**。

    实心块 181 cm³ ≈ 225 g/只，两只 450 g 直接吃掉整机结构预算的 90%。
    v2 的足部结构预算只有 31 g/只，所以必须是"3.5 mm 薄板 + 筋 + 掏空窗"，
    这也是唯一需要按"面接触受压"来设计、而不是按"承弯梁"设计的零件。
    """
    part = cq.Workplane("XY")
    ankle_x = length / 3.0
    x_rear = -ankle_x
    x_front = length - ankle_x

    # --- 踝部叉（锁踝舵盘 + 副轴轴承），轴线在 x=0 ---
    fork = limb_fork(shaft="+y", parent="+z", compact=True, spigot=False)
    part = part.union(fork)

    # --- 鞋底板 ---
    x_mid = (x_rear + x_front) / 2.0
    part = part.union(box(length, width, sole_t, at=(x_mid, 0, -sole_t)))

    # --- 放射筋（全部落在足底轮廓内）---
    spans = [(x_rear, -16.0), (16.0, ankle_x + 12.0), (ankle_x + 12.0, x_front)]
    for x0, x1 in spans:
        if x1 - x0 < 4.0:
            continue
        part = part.union(box(x1 - x0, 5.0, rib_h,
                              at=(x0, 0, -sole_t - 1.0)))
    for sign in (-1, 1):
        part = part.union(box(length * 0.92, 4.0, rib_h * 0.8,
                              at=(x_mid, sign * (width / 2 - 2.0), -sole_t - 1.0)))

    # --- 掏空窗（足底是受压面，可以开大孔）---
    for i in range(4):
        x = x_rear + length * (i + 0.5) / 4.0
        if abs(x) < 22.0:
            continue
        part = part.cut(box(length / 4.0 * 0.52, width * 0.34, sole_t * 3,
                            at=(x, 0, -sole_t * 2)))
    for sign in (-1, 1):
        part = part.cut(box(length * 0.22, width * 0.16, sole_t * 3,
                            at=(x_front - 18.0, sign * 15.0, -sole_t * 2)))

    # --- 防滑槽 ---
    for i in range(7):
        x = x_rear + length * (i + 0.5) / 7.0
        part = part.cut(box(4.0, width * 0.86, 2.0, at=(x, 0, -sole_t - 0.5)))

    part = safe_fillet(part, 1.5, "|Z")
    return sanitize(part)


# --------------------------------------------------------------------------
# 零件 9/10：夹爪（本体 + 动指）
# --------------------------------------------------------------------------
def gripper_body(wall: float = PLATE_T) -> cq.Workplane:
    """夹爪本体：锁舵盘 + 定指 + 副轴支撑，末端 50×30×20 包络。"""
    part = limb_fork(shaft="+y", parent="+z")
    part = part.cut(cyl(SPIGOT_D + 0.6, SPIGOT_H + 12.0,
                        at=(0, 0, -62.0)))
    # 定指
    part = part.union(box(26.0, 10.0, 18.0, at=(0, -20.0, -46.0)))
    part = safe_fillet(part, 2.0, "|Z")
    return sanitize(part)


def gripper_jaw() -> cq.Workplane:
    """夹爪动指：直接锁在舵盘上，随舵机开合（0–60°）。"""
    part = cq.Workplane("XY")
    part = part.union(box(24.0, 8.0, 16.0, at=(0, 0, -16.0)))
    part = part.union(box(30.0, 8.0, 10.0, at=(0, 0, 0)))
    part = drill(part, bolt_circle(IF["horn"]["pcd_mm"], 4),
                 dia=IF["horn"]["hole_dia_mm"], depth=30.0, z0=-1.0)
    part = part.cut(cyl(22.0, 12.0, at=(0, 0, -1.0)))
    part = part.cut(cyl(S["secondary_shaft_dia_mm"] / 2.0, 12.0,
                        at=(0, 0, -8.0)))
    return sanitize(part)


# --------------------------------------------------------------------------
# 零件 11-14：集成件
# --------------------------------------------------------------------------
def battery_tray() -> cq.Workplane:
    """电池仓抽屉：88×34×19 电池 + 绑带槽 + XT60 出线口。"""
    part = cq.Workplane("XY")
    part = part.union(box(92.0, 38.0, 3.0, at=(0, 0, 0)))
    for sign in (-1, 1):
        part = part.union(box(92.0, 3.0, 22.0, at=(0, sign * 17.5, 3.0)))
    part = part.union(box(3.0, 38.0, 22.0, at=(-44.5, 0, 3.0)))
    for dx in (-20.0, 20.0):
        part = part.cut(box(3.0, 40.0, 3.0, at=(dx, 0, 1.5)))
    part = part.cut(cyl(8.0, 6.0, at=(42.0, 0, 3.0), axis="X"))
    return sanitize(part)


def electronics_deck() -> cq.Workplane:
    """电控托盘：STM32 + URT-1 + XL4015 + 功放，带散热开窗与线卡。"""
    part = cq.Workplane("XY")
    part = part.union(box(100.0, 64.0, 3.0, at=(0, 0, 0)))
    for (x, y, l, w) in [(-22.0, 0.0, 52.0, 24.0), (28.0, 0.0, 40.0, 25.0),
                         (0.0, -20.0, 65.0, 25.0)]:
        for sx in (-1, 1):
            for sy in (-1, 1):
                part = part.union(bosses([(x + sx * (l / 2 - 4), y + sy * (w / 2 - 4))],
                                         od=5.5, height=6.0, bore_dia=2.2,
                                         bore_depth=5.0, z0=2.0))
    for dx in (-24.0, 0.0, 24.0):
        part = part.cut(box(14.0, 14.0, 6.0, at=(dx, 24.0, 0)))
    return sanitize(part)


def pdb_mount() -> cq.Workplane:
    """分线板座：4 路菊花链的物理根节点（standards.WIRING）。"""
    part = cq.Workplane("XY")
    part = part.union(box(46.0, 30.0, 3.0, at=(0, 0, 0)))
    for pt in [(-18.0, -11.0), (18.0, -11.0), (-18.0, 11.0), (18.0, 11.0)]:
        part = part.union(bosses([pt], od=5.0, height=3.0, bore_dia=2.2,
                                 bore_depth=4.0, z0=3.0))
    for dx in (-12.0, 0.0, 12.0):
        part = part.cut(box(6.0, 8.0, 6.0, at=(dx, 15.0, 0)))
    return sanitize(part)


def cable_clip() -> cq.Workplane:
    """走线夹：Φ6 线束，卡在 3 mm 板上，不用螺钉（一件 0.4 g）。"""
    part = cq.Workplane("XY")
    part = part.union(box(16.0, 10.0, 3.0, at=(0, 0, 0)))
    part = part.union(cyl(10.0, 8.0, at=(0, 0, 3.0)))
    part = part.cut(cyl(6.4, 9.0, at=(0, 0, 2.5)))
    part = part.cut(box(4.0, 12.0, 9.0, at=(0, 0, 3.0)))
    return sanitize(part)


# --------------------------------------------------------------------------
# 零件登记表
# --------------------------------------------------------------------------
SKELETON_PARTS: Dict[str, Dict[str, Any]] = {
    "joint_cage": {
        "builder": joint_cage, "count": 13, "material": "PETG", "infill": 0.55,
        "desc": "关节笼（舵机固定 + 副轴轴承位 + Ø34 母端插接）",
        "used_by": "膝/踝/肘/夹爪 各 2 只 + trunk_roll + 左右肩",
    },
    "joint_cage_yaw": {
        "builder": joint_cage_yaw, "count": 3, "material": "PETG", "infill": 0.55,
        "desc": "偏转关节笼（轴 Z，母端同轴；含副轴轴承座）",
        "used_by": "hip_yaw ×2、head_yaw",
    },
    "limb_fork": {
        "builder": limb_fork, "count": 12, "material": "PETG", "infill": 0.55,
        "desc": "连杆叉（锁舵盘 + 副轴轴颈 + Ø34 子端插接）",
        "used_by": "hip_pitch/knee/ankle/shoulder_roll/elbow/gripper 各 2 只",
    },
    "limb_tube": {
        "builder": limb_tube, "count": 8, "material": "PETG", "infill": 0.50,
        "desc": "Φ40/Φ34 连杆管（大腿/小腿 62.8、上臂 47.1、前臂 39.2）",
        "used_by": "四肢主承力段",
    },
    "compact_adapter": {
        "builder": compact_adapter, "count": 8, "material": "PETG", "infill": 0.60,
        "desc": "紧凑转接块（19.6/27.5 mm 短链节，一体 L 形）",
        "used_by": "hip_yaw/hip_roll/shoulder_pitch/trunk_roll/head 短链节",
    },
    "pelvis_frame": {
        "builder": pelvis_frame, "count": 1, "material": "PETG", "infill": 0.45,
        "desc": "骨盆框架（3 舵机 + IMU + 分线板）",
    },
    "torso_frame": {
        "builder": torso_frame, "count": 1, "material": "PETG", "infill": 0.45,
        "desc": "躯干框架（树莓派 + 电池 + 电控 + 双肩 + 颈座）",
    },
    "head_shell": {
        "builder": head_shell, "count": 1, "material": "PLA", "infill": 0.20,
        "desc": "头壳（摄像头 + 麦克风 + 自带俯仰叉）",
    },
    "foot_plate": {
        "builder": foot_plate, "count": 2, "material": "PETG", "infill": 0.40,
        "desc": "足板（踝座 + 放射筋 + 防滑槽）",
    },
    "gripper_body": {
        "builder": gripper_body, "count": 2, "material": "PETG", "infill": 0.50,
        "desc": "夹爪本体（锁舵盘 + 定指）",
    },
    "gripper_jaw": {
        "builder": gripper_jaw, "count": 2, "material": "PETG", "infill": 0.50,
        "desc": "夹爪动指（随舵盘 0–60° 开合）",
    },
    "battery_tray": {
        "builder": battery_tray, "count": 1, "material": "PETG", "infill": 0.35,
        "desc": "电池仓抽屉（3S 2000mAh + 绑带槽 + XT60 出线）",
    },
    "electronics_deck": {
        "builder": electronics_deck, "count": 1, "material": "PETG", "infill": 0.35,
        "desc": "电控托盘（STM32 / URT-1 / XL4015 / 功放）",
    },
    "pdb_mount": {
        "builder": pdb_mount, "count": 1, "material": "PETG", "infill": 0.35,
        "desc": "分线板座（4 路菊花链根节点）",
    },
    "cable_clip": {
        "builder": cable_clip, "count": 16, "material": "PETG", "infill": 0.30,
        "desc": "走线夹（Φ6 线束，免螺钉卡装）",
    },
}


def build(name: str, **kwargs: Any) -> cq.Workplane:
    if name not in SKELETON_PARTS:
        raise KeyError(f"未登记骨架零件 {name}；可选 {sorted(SKELETON_PARTS)}")
    return SKELETON_PARTS[name]["builder"](**kwargs)


def report(name: str, shape: cq.Workplane) -> Dict[str, Any]:
    spec = SKELETON_PARTS[name]
    rep = part_report(name, shape, material=spec["material"],
                      infill=spec["infill"])
    rep["desc"] = spec["desc"]
    rep["count"] = spec.get("count", 1)
    rep["warnings"] = needs_support(shape)
    return rep
