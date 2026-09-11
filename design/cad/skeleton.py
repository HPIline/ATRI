"""3D 打印件骨架结构：零件库（CadQuery / OpenCASCADE 真 B-rep）。

设计原则（与 `standards.py` 的 ASSEMBLY 章、`kit.py` 的 IF 表配套）：

1. **骨架不是盒子**：所有大件都是"框 + 筋 + 减重窗"，不是闭合薄壳。
   闭合薄壳按 3 mm 壁算，一个 100×90×55 的躯干壳就是 137 g，
   而 v2 给整机结构的预算是 **500 g / 23 个 link** —— 壳体方案必然超支。
2. **模块化**：膝/踝/肘仍是笼+叉+管；髋/肩 19.6 mm 簇改走
   `cluster_horn_arm` + `cluster_outrigger`（不对称 C 臂，机体沿轴抽出）。
   `compact_adapter` 只留给颈/腰 27.5 mm 短链。
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
                 safe_chamfer, safe_fillet, servo_frame, tube)
from parts import sanitize
from standards import (ASSEMBLY, WIRING, bearing, fastener, servo,
                       servo_horn_interface)

SERVO_NAME = "STS3215"

# --------------------------------------------------------------------------
# 舵机几何（所有关节模块的唯一真值来源）
# --------------------------------------------------------------------------
S = servo(SERVO_NAME)

# --------------------------------------------------------------------------
# 舵机在**标准姿态**下的包络（唯一真值来源：kit.servo_frame）
#   标准姿态：输出轴 +Y、母端接口 +Z、机身长度沿 X（见 kit.orient）
#
# ⚠️ 2026-09-11 修正（此前把 35 与 24.7 用反，导致整机预览大面积穿模）：
#     机身长度 45.2 沿 X（且**轴心不在中点**：+X 侧 10.2、−X 侧 35.0）
#     机身厚度 35.0 沿 Y（＝输出轴方向），两侧板净距 = 35.0 + 0.5 间隙
#     机身宽度 24.7 沿 Z（轴线在宽度方向**居中**，不是"偏上 6.5"）
# --------------------------------------------------------------------------
SF = servo_frame(SERVO_NAME)
X_MIN, X_MAX = SF["x_min"], SF["x_max"]      # −35.0 … +10.2（轴心为原点）
Z_HALF = SF["z_half"]                        # 12.35：宽度方向半宽
Y_HALF = SF["y_half"]                        # 17.5：机壳沿轴半厚
BOSS_FACE = SF["boss_face"]                  # +20.0：输出端 Φ20 凸台面
HORN_FACE = SF["horn_face"]                  # +24.0：金属舵盘外表面
GAP = SF["axial"] + SF["clearance"]          # 35.5：两侧板（⊥输出轴）净距
Z_TOP, Z_BOT = Z_HALF, -Z_HALF               # ±12.35：机体上/下表面（轴线为 0）
X_HALF = (X_MAX - X_MIN) / 2.0               # 22.6：长度方向半长（参考值）
X_CTR = (X_MIN + X_MAX) / 2.0                # −12.4：机身长度方向中心
PLATE_T = FDM["wall_mm"]                     # 3.0
PLATE_Y = GAP / 2.0 + PLATE_T / 2.0          # 19.25：两侧板中心
SPAN_X = (X_MAX - X_MIN) + 8.0               # 53.2：侧板长（含端部包边）
SPIGOT_D, SPIGOT_H, SPIGOT_BORE = 34.0, 12.0, 26.0

# --------------------------------------------------------------------------
# 躯干内部层高 —— **唯一真值来源**
#   三处必须一致，过去各写一份，导致"两个打印件自己先撞上"（9 942 mm³，重合率 53%）：
#     ① torso_frame 的内建层板
#     ② battery_tray / electronics_deck 这两个独立零件的自身标高
#     ③ assembly 里电子件的落座标高（ELEC_DECK_TOP）
# --------------------------------------------------------------------------
TORSO_PLATE_T = 2.6
TORSO_BAY_FLOOR_Z = 18.0          # 电池仓层板底面（下层）
TORSO_DECK_FLOOR_Z = 42.0         # 电控层层板底面（上层）
TORSO_BAY_TOP_Z = TORSO_BAY_FLOOR_Z + TORSO_PLATE_T     # 20.6：层板上表面
TORSO_DECK_TOP_Z = TORSO_DECK_FLOOR_Z + TORSO_PLATE_T   # 44.6：层板上表面
# 插入件（电池仓抽屉 / 电控托盘）自己还有一层 3 mm 底板 —— 承放电子件的是**它们**的上表面。
# 只算框架层板会低 3 mm，实测导致电池顶进托盘（11 937 mm³）。
INSERT_PLATE_T = 3.0
TORSO_BAY_LOAD_Z = TORSO_BAY_TOP_Z + INSERT_PLATE_T     # 23.6：电池坐在这个面上
TORSO_DECK_LOAD_Z = TORSO_DECK_TOP_Z + INSERT_PLATE_T   # 47.6：树莓派坐在这个面上


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
    # ⚠️ 芯棒必须**坐在顶板上**：原为 z_cap_bot + wall + 2.0，凭空多出 2 mm 空隙，
    #    使 Φ34 芯棒成为与本体不相连的独立实体（预览里就是"飘着一块"）。
    z_cap_top = z_cap_bot + wall             # 顶板上表面 = 母端插接座面

    part = cq.Workplane("XY")

    # --- 两侧板（⊥ 输出轴）---
    for sign in (-1, 1):
        p = box(SPAN_X, wall, z_cap_top - z_floor_bot,
                at=(0, sign * PLATE_Y, z_floor_bot))
        part = part.union(p)

    # --- 底板（托住舵机底面，同时把两块侧板连成一体）---
    floor = box(SPAN_X, GAP + 2 * wall, wall, at=(0, 0, z_floor_bot))
    for dx in (-9.0, 9.0):
        floor = floor.cut(box(12.0, GAP - 6.0, wall * 4,
                              at=(dx, 0, z_floor_bot - wall)))
    part = part.union(floor)

    # --- 顶板（母端接口的基座 + 抗扭）：开中央大窗 ---
    cap = box(SPAN_X, GAP + 2 * wall, wall, at=(0, 0, z_cap_bot))
    cap = cap.cut(box(30.0, GAP - 8.0, wall * 4, at=(0, 0, z_cap_bot - wall)))
    part = part.union(cap)

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

    # --- 舵机 4×M2.5 安装孔（**沿输出轴方向**穿过两块侧板）---
    #     实测：舵机两个轴向端面各有 4×Φ2.5，方形 9.9×9.9（= 节圆 Φ14），
    #     孔阵中心就是输出轴心。所以螺钉走 ±Y，不是"从底部往上拧"。
    pitch = SF["mount_pitch"]
    part = drill(part, [(sx * pitch[0] / 2.0, sy * pitch[1] / 2.0)
                        for sx in (-1, 1) for sy in (-1, 1)],
                 dia=fastener("M2.5")["clearance_hole_mm"],
                 depth=2 * (PLATE_Y + PLATE_T) + 2.0,
                 z0=-PLATE_Y - PLATE_T - 1.0, axis="Y")

    # --- 母端插接芯棒的 3×M3 径向螺钉（120°，攻丝底孔，现场攻丝或热熔）---
    for i in range(3):
        ang = math.radians(90 + 120 * i)
        hx, hy = 20.0 * math.cos(ang), 20.0 * math.sin(ang)
        hole = (cq.Workplane("XZ").center(hx, z_cap_top + SPIGOT_H / 2.0)
                .circle(fastener("M3")["tap_drill_mm"] / 2.0)
                .extrude(14.0).translate((0, hy, 0)))
        part = part.cut(hole)

    # --- 减重窗 ---
    #     ⚠️ 原窗口高 30 且从 z_floor_bot+8 起，会切穿顶板、把侧板切成孤岛
    #     （预览里表现为"多出来两块碎料"）。现在窗口两端各留 6/3 mm 连续材料，
    #     并避开 4×M2.5 安装孔带（|X| ≤ 6.3、|Z| ≤ 6.3）。
    if lighten:
        wz0, wz1 = z_floor_bot + 6.0, z_cap_bot - 3.0
        for sign in (-1, 1):
            for dx in (-13.0, 13.0):
                part = part.cut(box(11.0, wall * 4, wz1 - wz0,
                                    at=(dx, sign * PLATE_Y, wz0)))
            part = part.cut(box(24.0, wall * 4, 4.0,
                                at=(0, sign * PLATE_Y, 7.5)))

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
    # ⚠️ 2026-09-11 订正：两端面位置必须按**真实轴向尺寸链**取
    #    输出侧板内表面 = −(机壳半厚 17.5 + 凸台 2.5) = −20.0（让开 Φ20 凸台）
    #    副轴侧板内表面 = +机壳半厚 17.5（贴住舵机副轴端面，4×M2.5 就拧在这里）
    z_out = -BOSS_FACE              # −20.0：输出面（−Z）
    z_sec = +Y_HALF                 # +17.5：副轴面（+Z）

    plate_t = wall
    span_x, span_y = 56.0, 46.0
    post_h = (z_sec + plate_t) - (z_out - plate_t) or 1.0

    # 输出侧板（开 Ø21 舵盘避空 + 四角挖窗）
    part = part.union(box(span_x, span_y, plate_t, at=(0, 0, z_out - plate_t)))
    part = part.cut(cyl(21.0, plate_t * 3, at=(0, 0, z_out - plate_t * 2)))
    for sx in (-1, 1):
        for sy in (-1, 1):
            part = part.cut(box(12.0, 10.0, plate_t * 3,
                                at=(sx * 21.0, sy * 16.0, z_out - plate_t * 2)))
    # 母端侧板（副轴轴承 + 4×M3 与骨架对接）
    part = part.union(box(span_x, span_y, plate_t, at=(0, 0, z_sec)))
    for sx in (-1, 1):
        for sy in (-1, 1):
            part = part.cut(box(12.0, 10.0, plate_t * 3,
                                at=(sx * 21.0, sy * 16.0, z_sec - plate_t)))
    b = bearing(IF["secondary_shaft"]["bearing"])
    part = part.cut(cyl(b["od_mm"] + FDM["bearing_bore_interference_mm"],
                        plate_t * 3, at=(0, 0, z_sec - plate_t)))
    part = drill(part, bolt_circle(IF["cage_flange"]["pcd_mm"], 4),
                 dia=IF["cage_flange"]["hole_dia_mm"], depth=plate_t * 3,
                 z0=z_sec - plate_t)
    # 4 根角柱（高度按两端板外表面实际跨度，旧式 2*z_sec 假设两端对称 → 会差 3.5 mm）
    for sx in (-1, 1):
        for sy in (-1, 1):
            part = part.union(box(8.0, 8.0, post_h,
                                  at=(sx * (span_x / 2 - 4.0),
                                      sy * (span_y / 2 - 4.0), z_out - plate_t)))
    # 舵机 4×M2.5 安装孔：沿输出轴方向贯穿两块端板（方形 9.9×9.9 = 节圆 Φ14）
    pitch = SF["mount_pitch"]
    part = drill(part, [(sx * pitch[0] / 2.0, sy * pitch[1] / 2.0)
                        for sx in (-1, 1) for sy in (-1, 1)],
                 dia=fastener("M2.5")["clearance_hole_mm"],
                 depth=post_h + 2.0, z0=z_out - plate_t - 1.0, axis="Z")
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
    """连杆叉：一侧螺栓锁在金属舵盘上，另一侧托住下一级连杆管。

    ⚠️ 2026-09-11 订正：本件原来还有"臂 B + Φ5.96 轴颈"（插进笼子里的轴承内圈）。
    但**舵机副轴 Φ6 与它同轴**、且副轴本身要穿过那个轴承 —— 二者不可能同时占
    同一条轴线（轴颈 Φ5.96 套不进 Φ6 的副轴）。按实物结论：
        **第二支点 = 笼子 −Y 板里的 MF106ZZ 骑在舵机副轴上**（副轴随输出一起转），
    故本件不再做轴颈，臂 B 取消，载荷路径改为：
        舵盘（臂 A）→ 底座 → 子端插接芯棒。
    """
    horn = servo_horn_interface(SERVO_NAME)

    arm_out = HORN_FACE + 0.05              # 24.05：臂 A 内表面（贴舵盘外表面）
    arm_t = wall

    z_top = (Z_TOP + 2.0) if not compact else 16.0
    z_base_top = (Z_BOT - 12.0) if not compact else -13.0    # 紧凑型只跨过轴线
    z_base_bot = z_base_top - wall
    y_sec_out = -(Y_HALF + 1.0)             # 底座副轴侧收边（不越过副轴）

    part = cq.Workplane("XY")

    # --- 臂 A：螺栓锁舵盘（4×M2.5 走 PCD14）---
    arm_a = box(34.0, arm_t, z_top - z_base_bot,
                at=(0, arm_out + arm_t / 2.0, z_base_bot))
    _wb = z_base_bot + 2.0
    _wt = min(_wb + 0.36 * (z_top - z_base_bot), -6.0)   # 窗顶不得越过副轴轴颈（z≈0）
    if _wt - _wb > 4.0:
        arm_a = arm_a.cut(box(18.0, arm_t * 4, _wt - _wb,
                              at=(0, arm_out + arm_t / 2.0, _wb)))
    part = part.union(arm_a)
    part = drill(part, bolt_circle(horn["pcd_mm"], horn["hole_count"]),
                 dia=IF["horn"]["hole_dia_mm"], depth=arm_t * 6,
                 z0=-(arm_t * 3), axis="Y")
    part = part.cut(cyl(26.0, arm_t * 4,
                        at=(0, arm_out - arm_t * 2, 0), axis="Y"))

    # --- 底座：从舵盘侧跨到副轴侧收边，下挂子端插接芯棒 ---
    y_a_out = arm_out + arm_t
    base = box(38.0, y_a_out - y_sec_out, wall,
               at=(0, (y_a_out + y_sec_out) / 2.0, z_base_bot))
    base = base.cut(box(14.0, 16.0, wall,
                        at=(0, (y_a_out + y_sec_out) / 2.0, z_base_bot)))
    part = part.union(base)
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
                   .slot2D(length * 0.62, od * 0.30).extrude(od))
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

    # 输出侧：托住下一级舵机（两侧板 ⊥ 输出轴 + 底板，舵机从 +X 滑入）
    out_top = -drop + Z_TOP
    out_bot = -drop + Z_BOT
    span = 46.0
    for sign in (-1, 1):
        part = part.union(box(span, wall, out_top - out_bot + 6.0,
                              at=(0, sign * PLATE_Y, out_bot - 3.0)))
    part = part.union(box(span, 2 * PLATE_Y + wall, wall, at=(0, 0, out_bot - wall)))
    # 下一级舵机 4×M2.5：沿输出轴方向穿过两块侧板（方形 9.9×9.9 = 节圆 Φ14）
    pitch = SF["mount_pitch"]
    part = drill(part, [(sx * pitch[0] / 2.0, -drop + sy * pitch[1] / 2.0)
                        for sx in (-1, 1) for sy in (-1, 1)],
                 dia=fastener("M2.5")["clearance_hole_mm"],
                 depth=2 * (PLATE_Y + wall) + 2.0,
                 z0=-PLATE_Y - wall - 1.0, axis="Y")
    # 输出侧（+Y 板）：让舵机 Φ20 凸台与花键穿出的避空
    part = part.cut(cyl(26.0, wall * 4, at=(0, PLATE_Y - wall, -drop), axis="Y"))
    # 副轴侧（−Y 板）：MF106ZZ 压入孔（第二支点骑在下一级舵机副轴上）
    b = bearing(IF["secondary_shaft"]["bearing"])
    part = part.cut(cyl(b["od_mm"] + FDM["bearing_bore_interference_mm"],
                        wall * 4, at=(0, -PLATE_Y - wall * 2, -drop), axis="Y"))

    part = safe_fillet(part, FDM["fillet_min_mm"], "|Y")
    part = orient(part, out_shaft, {"+z": "-z", "-z": "+z"}.get(in_shaft, in_shaft))
    return sanitize(part)


# --------------------------------------------------------------------------
# 零件 4b：髋/肩错轴族（第 5 轮）
#   轴距 19.6 mm 只给「输出轴 + 薄臂」住；机体沿自身轴甩到外侧。
#   compact_adapter 仍留给颈/腰 27.5 mm 短链，禁止在这里改回去。
# --------------------------------------------------------------------------
def cluster_horn_arm(in_shaft: str = "+z", out_shaft: str = "+x",
                     drop: float = 19.6, stagger: float = 0.0,
                     parent_stagger: float = 0.0,
                     wall: float = PLATE_T) -> cq.Workplane:
    """单侧臂：锁上一级金属舵盘（I2），把下一级轴线拉到 `drop`。

    标准姿态下：上一级输出沿 +Z，下一级输出沿 +Y，下一级原点在 (0,0,-drop)。
    `parent_stagger`：上一级机体沿自身轴（本地 +Z）的偏置，法兰跟着舵盘走。
    `stagger`：下一级机体沿 +Y 的偏置。两者都来自 fit_stagger.py。
    臂走 −X 侧，躲开轴距核心；弯矩走支架，不走舵机壳体。

    承力目标：6061-T6 2–3 mm 激光/CNC（Gemini S4，provisional）。
    现几何按 PETG `wall` 占位，改铝板厚前不要用铝密度去乘本实体体积。
    """
    horn = servo_horn_interface(SERVO_NAME)
    horn_t = wall + 1.0
    z_flange = parent_stagger
    z_bot = -max(drop, 12.0) - 8.0
    z_height = (z_flange + horn_t) - z_bot
    # 子级机体 x ∈ [x_min, x_max] = [-35, +10.2]，立柱必须在其外侧
    x_spine = X_MIN - 6.0                 # −41：机身 −X 端面再留 6 mm
    y_spine = -10.0                       # 躲开子级沿 +Y 甩出的机体

    part = cq.Workplane("XY")
    # 舵盘法兰（I2）——跟父舵机 stagger 走
    part = part.union(box(24.0, 24.0, horn_t, at=(0, 0, z_flange - horn_t)))
    part = drill(part, bolt_circle(horn["pcd_mm"], horn["hole_count"]),
                 dia=IF["horn"]["hole_dia_mm"], depth=horn_t * 3,
                 z0=z_flange - horn_t * 2)
    part = part.cut(cyl(16.0, horn_t * 3, at=(0, 0, z_flange - horn_t * 1.5)))

    # 外侧立柱（C 形的背）
    part = part.union(box(wall, 22.0, z_height,
                          at=(x_spine, y_spine, z_bot)))
    # 上桥：法兰 → 立柱（z ≈ 父舵盘，y 走外侧，不穿子级机体）
    part = part.union(box(abs(x_spine) + 8.0, wall, wall,
                          at=(x_spine / 2.0, y_spine, z_flange - wall)))
    # 下桥：立柱 → 子级原点（只托轴）
    part = part.union(box(abs(x_spine) + 8.0, wall, wall,
                          at=(x_spine / 2.0, y_spine, -drop - wall / 2.0)))

    # drop≈0 时立板与法兰几乎共面，圆角会把实体打成 Compound
    if drop >= 8.0:
        part = safe_fillet(part, FDM["fillet_min_mm"], "|Y")
    parent_dir = {"+z": "-z", "-z": "+z"}.get(in_shaft, in_shaft)
    part = orient(part, out_shaft, parent_dir)
    return sanitize(part)


def cluster_outrigger(shaft: str = "+y", parent: str = "+z",
                      stagger: float = 0.0,
                      wall: float = PLATE_T) -> cq.Workplane:
    """外侧抱箍：在轴距外侧夹住错开后的舵机两端面 4×M2.5，副轴侧保留 MF106ZZ。

    关节原点仍在 (0,0,0)；机体中心沿 +Y 移了 `stagger`。
    两块端板跟着 stagger 走，轴距核心不再被 35 mm 机体占据。
    """
    y_c = stagger                         # 机体沿轴中心
    y_out = y_c + Y_HALF                  # 输出端面（机壳，不含凸台）
    y_sec = y_c - Y_HALF                  # 副轴端面
    z_floor_bot = Z_BOT - wall
    z_cap_top = Z_TOP + wall

    part = cq.Workplane("XY")
    # 输出侧端板（+Y）：4×M2.5 对穿，中心让开 Φ20 凸台
    p_out = box(SPAN_X, wall, z_cap_top - z_floor_bot,
                at=(0, y_out + wall / 2.0, z_floor_bot))
    p_out = p_out.cut(cyl(26.0, wall * 4,
                          at=(0, y_out - wall, 0), axis="Y"))
    part = part.union(p_out)

    # 副轴侧端板（−Y）：MF106ZZ 压入
    p_sec = box(SPAN_X, wall, z_cap_top - z_floor_bot,
                at=(0, y_sec - wall / 2.0, z_floor_bot))
    b = bearing(IF["secondary_shaft"]["bearing"])
    bore = b["od_mm"] + FDM["bearing_bore_interference_mm"]
    p_sec = p_sec.cut(cyl(bore, wall * 4,
                          at=(0, y_sec - wall * 2, 0), axis="Y"))
    if {"flange_od_mm", "flange_width_mm"} <= set(b):
        # 法兰沉台在副轴板外侧（与 joint_cage 同源，S6#07 径向搭边）
        p_sec = p_sec.cut(cyl(b["flange_od_mm"] + FDM["clearance_snug_mm"],
                              b["flange_width_mm"] + 0.2,
                              at=(0, y_sec - wall, 0), axis="Y")
                          .translate((0, -0.1, 0)))
    part = part.union(p_sec)

    # 底板把两块端板连成一体（走在机体 −Z 外侧，不进轴距核心）
    y_mid = (y_out + y_sec) / 2.0
    part = part.union(box(SPAN_X, abs(y_out - y_sec) + wall, wall,
                          at=(0, y_mid, z_floor_bot)))

    # 端面 4×M2.5，孔阵中心 = 机体轴心（随 stagger 平移）
    pitch = SF["mount_pitch"]
    part = drill(part, [(sx * pitch[0] / 2.0, sy * pitch[1] / 2.0)
                        for sx in (-1, 1) for sy in (-1, 1)],
                 dia=fastener("M2.5")["clearance_hole_mm"],
                 depth=abs(y_out - y_sec) + 2 * wall + 2.0,
                 z0=min(y_out, y_sec) - wall - 1.0, axis="Y")

    part = safe_fillet(part, FDM["fillet_min_mm"], "|Y")
    part = orient(part, shaft, parent)
    return sanitize(part)


def backpack_plate(wall: float = 3.0) -> cq.Workplane:
    """背挂板：5 件电子件的公共座（选项 A，接受整机深度 ~198 mm）。

    板面在躯干局部 x = −60，z 从约 −10 到 +90，与 assembly.ELEC_BACKPACK 对齐。
    """
    part = cq.Workplane("XY")
    # 板在电子件 +X 面（x=−60）与躯干（x≥−48）之间，电子件坐在板的 −X 面
    part = part.union(box(3.0, 72.0, 140.0, at=(-58.5, 0.0, -50.0)))
    for sy in (-1, 1):
        for sz in (-40.0, 80.0):
            part = part.union(box(8.0, 8.0, 6.0, at=(-53.0, sy * 28.0, sz)))
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

    # --- 四立柱（7×7 + Ø4 走线孔贯通）---
    for sx in (-1, 1):
        for sy in (-1, 1):
            post = box(7.0, 7.0, body_h, at=(sx * (body_l / 2 - 4.0),
                                             sy * (body_w / 2 - 4.0), -body_h / 2))
            post = post.cut(cyl(4.0, body_h + 6, at=(sx * (body_l / 2 - 4.0),
                                                     sy * (body_w / 2 - 4.0),
                                                     -body_h / 2 - 3)))
            part = part.union(post)
    # --- 上环改"边框 + 横梁"（整面板 31 g → 框 12 g）---
    ring = box(body_l, body_w, wall, at=(0, 0, body_h / 2 - wall))
    ring = ring.cut(box(body_l - 22.0, body_w - 22.0, wall * 4,
                        at=(0, 0, body_h / 2 - wall * 2)))
    part = part.union(ring)
    part = part.union(box(12.0, body_w - 20.0, wall,
                          at=(0, 0, body_h / 2 - wall)))
    for sy in (-1, 1):
        part = part.union(box(body_l, wall, 10.0, at=(0, sy * (body_w / 2 - 5.0),
                                                       -body_h / 2 + 5.0)))
    part = part.union(box(wall, body_w, 10.0, at=(body_l / 2 - wall, 0,
                                                  -body_h / 2 + 5.0)))

    # --- 上表面：trunk_roll 舵机笼的 Ø34 插接座（轴 X）---
    part = part.union(box(34.0, 34.0, 4.0, at=(0, 0, body_h / 2)))
    part = part.union(cyl(SPIGOT_D, 12.0, at=(0, 0, -6.0), axis="X")
                      .translate((0, 0, 19.6 - body_h / 2 + 4.0)))

    # --- 左右翼：hip_yaw 舵机笼座（两片板 + 筋，不做整块）---
    for sign in (-1, 1):
        for dx in (-17.0, 17.0):
            part = part.union(box(6.0, 30.0, 12.0,
                                  at=(dx, sign * 45.0, -15.0)))
        part = part.union(box(40.0, 30.0, 5.0, at=(0, sign * 45.0, -9.0)))
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

    # --- 舵机让位切口（按 kit.servo_frame 实测包络 + 1.5 mm 单边余量，
    #     取「框架实体 ∩ 舵机包络」的实际重叠区，不碰四根承力立柱）---
    # kit.box 的 at=(cx, cy, z底面)：x/y 是几何中心、z 是底面。
    #   trunk_roll（轴 X，长 45.2 沿 Y）：横穿上环/横梁/笼座顶部。
    part = part.cut(box(38.0, 48.2, 16.8, at=(0.0, -12.4, 5.7)))
    #   左右 hip_yaw（轴 Z，长 45.2 沿 X）：横穿左右翼座板。
    for sign in (-1, 1):
        part = part.cut(box(48.2, 27.7, 22.5, at=(12.4, sign * 45.0, -23.1)))

    part = safe_fillet(part, FDM["fillet_struct_mm"], "|Z")
    return sanitize(part)


# --------------------------------------------------------------------------
# 零件 6：躯干框架（上半身中枢）
# --------------------------------------------------------------------------
def torso_frame(wall: float = PLATE_T) -> cq.Workplane:
    """躯干桁架：**俯仰叉 → 电池仓 → 树莓派 → 颈座**（绝对坐标，无浮动件）。

    竖向布局（torso_upper link 系，原点 = trunk_pitch 关节）：
        z ∈ [−16, +16]  trunk_pitch 舵盘叉（子端朝上）
        z ∈ [+18, +40]  3S 电池（88×34×19，88 边沿 Y）
        z ∈ [+42, +62]  树莓派 4B（85 边沿 Y，上方留 15 mm 散热）
        z ∈ [+66, +69]  颈座顶板（4×M3 热熔铜螺母 @PCD26，接 head_yaw 舵机笼）
        y = ±75         双肩 pylon

    **容积是超额订阅的（实测结论）**：俯仰叉 32 + 电池 19 + 树莓派 17 = 68 mm，
    而到 head_yaw 轴线只有 82.4 mm（还要留给颈座与舵机笼）。
    因此 STM32/驱动板/XL4015/功放**塞不进躯干**，必须外挂（见
    `design/cad/README.md` 的集成约定）。
    """
    part = cq.Workplane("XY")
    # ⚠️ 2026-09-11 加宽：净距 80×70 装不下长边 88 的电池与 85 的树莓派（实测）。
    #    整机宽度由手臂决定（y=±75），躯干加宽**不改整机包络**；代价只是这一件重约 20 g。
    tl, tw = 108.0, 104.0
    post_x, post_y = tl / 2 - 4.0, tw / 2 - 4.0     # 立柱中心（8×8 → 内表面 ±(半宽−8)）

    # --- 1. trunk_pitch 舵盘叉（自带，子端朝上）---
    part = part.union(limb_fork(shaft="+y", parent="-z", compact=True,
                                spigot=False))

    # --- 2. 叉 → 电池仓的连接柱（四根，穿在叉臂外侧）---
    for sx in (-1, 1):
        for sy in (-1, 1):
            part = part.union(box(8.0, 8.0, 12.0, at=(sx * 14.0, sy * 20.0, 8.0)))

    # --- 3. 电池仓底板（边框 + 两条横梁，电池坐在框上）---
    deck = box(tl, tw, TORSO_PLATE_T, at=(0, 0, TORSO_BAY_FLOOR_Z))
    deck = deck.cut(box(60.0, 56.0, 8.0,
                        at=(0, 0, TORSO_BAY_FLOOR_Z - 2.0)))
    part = part.union(deck)
    for sy in (-1, 1):
        part = part.union(box(80.0, 8.0, TORSO_PLATE_T,
                              at=(0, sy * 16.0, TORSO_BAY_FLOOR_Z)))
    for sy in (-1, 1):
        part = part.union(box(38.0, 3.0, 22.0, at=(0, sy * (tw / 2 + 1.0), 20.6)))
    for dx in (-11.0, 11.0):
        part = part.cut(box(3.0, 92.0, 3.0, at=(dx, 0, 17.0)))

    # --- 4. 主舱四立柱（8×8 + Ø5 走线孔）---
    for sx in (-1, 1):
        for sy in (-1, 1):
            post = box(8.0, 8.0, 48.0, at=(sx * post_x, sy * post_y, 18.0))
            post = post.cut(cyl(5.0, 54.0, at=(sx * post_x, sy * post_y, 16.0)))
            part = part.union(post)

    # --- 5. 树莓派托盘（外框 + 4×M2.5 柱，85 边沿 Y）---
    tray = box(tl, tw, TORSO_PLATE_T, at=(0, 0, TORSO_DECK_FLOOR_Z))
    tray = tray.cut(box(52.0, 60.0, 8.0,
                        at=(0, 0, TORSO_DECK_FLOOR_Z - 2.0)))
    for sy in (-1, 1):
        tray = tray.cut(box(20.0, 18.0, 8.0,
                            at=(0, sy * 30.0, TORSO_DECK_FLOOR_Z - 2.0)))
    part = part.union(tray)
    for sx in (-1, 1):
        for sy in (-1, 1):
            part = part.union(bosses([(sx * 29.0, sy * 24.5)], od=5.5, height=6.0,
                                     bore_dia=2.2, bore_depth=5.0, z0=40.5))

    # --- 6. 上环（边框 + 横梁）---
    ring = box(tl, tw, wall, at=(0, 0, 63.0))
    ring = ring.cut(box(tl - 20.0, tw - 20.0, wall * 4, at=(0, 0, 62.0)))
    part = part.union(ring)

    # --- 7. 胸段立柱 + 颈座顶板（4×M3 铜螺母 @PCD26）---
    for sx in (-1, 1):
        for sy in (-1, 1):
            part = part.union(box(7.0, 7.0, 12.0, at=(sx * 26.0, sy * 20.0, 57.0)))
    shelf = box(60.0, 44.0, 2.6, at=(0, 0, 60.0))
    shelf = shelf.cut(box(40.0, 26.0, 8.0, at=(0, 0, 58.0)))
    part = part.union(shelf)
    for sx in (-1, 1):
        for sy in (-1, 1):
            part = part.union(box(18.0, 6.0, 3.0, at=(sx * 32.0, sy * 20.0, 60.0)))
    top = box(64.0, 48.0, 5.0, at=(0, 0, 64.0))
    for pt in bolt_circle(IF["cage_flange"]["pcd_mm"], 4):
        top = top.cut(cyl(3.4, 10.0, at=(pt[0], pt[1], 62.0)))
    top = top.cut(cyl(10.0, 10.0, at=(0, 0, 62.0)))
    part = part.union(top)

    # --- 8. 双肩 pylon（两片竖板 + 上下筋 + Ø34 笼座，轴 Y）---
    for sign in (-1, 1):
        for dx in (-16.0, 16.0):
            part = part.union(box(4.0, 26.0, 34.0,
                                  at=(dx, sign * 54.0, 11.8), centered_z=True))
        for dz in (-13.0, 13.0):
            part = part.union(box(88.0, 12.0, 4.0,
                                  at=(0, sign * 54.0, 11.8 + dz)))
        part = part.union(cyl(SPIGOT_D, 14.0, at=(0, sign * 66.0, 11.8), axis="Y"))

    # --- 舵机让位切口（按 kit.servo_frame 实测包络 + 1.5 mm 单边余量，
    #     取「框架实体 ∩ 舵机包络」的实际重叠区，不碰四根承力立柱）---
    #   左右 shoulder_roll（轴 X，长 45.2 沿 Z）：穿双肩 pylon 的 Ø34 笼座圆柱与筋板。
    for sign in (-1, 1):
        part = part.cut(box(38.5, 20.4, 30.2, at=(-0.2, sign * 71.3, 0.1)))

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
    base = box(hl, hw, wall, at=(0, 0, z0 - hh / 2))                     # 底
    base = base.cut(box(32.0, 26.0, wall * 1.2,
                        at=(0, 0, z0 - hh / 2 - 0.2 * wall)))
    part = part.union(base)
    top = box(hl, hw, wall, at=(0, 0, z0 + hh / 2 - wall))               # 顶
    top = top.cut(box(hl - 24.0, hw - 24.0, wall * 1.2,
                      at=(0, 0, z0 + hh / 2 - 1.2 * wall)))
    part = part.union(top)
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

    # --- 舵机让位切口（按 kit.servo_frame 实测包络 + 1.5 mm 单边余量，
    #     取「框架实体 ∩ 舵机包络」的实际重叠区）---
    #   head_pitch（轴 Y，长 45.2 沿 X）：穿壳底与底部叉。
    part = part.cut(box(48.2, 46.1, 18.8, at=(12.4, -0.1, -5.0)))
    #   head_yaw（轴 Z，长 45.2 沿 X）：在壳底下方穿过。
    part = part.cut(box(32.2, 27.7, 18.0, at=(-4.4, 0.0, -43.3)))

    part = safe_fillet(part, 3.0, "|Z")
    return sanitize(part)


# --------------------------------------------------------------------------
# 零件 8：足板（含踝部叉）
# --------------------------------------------------------------------------
def foot_plate(length: float = 110.0, width: float = 60.0, sole_t: float = 3.0,
               rib_h: float = 9.0) -> cq.Workplane:
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
    # 站在电池仓层板上表面（唯一真值来源，见 TORSO_BAY_TOP_Z）
    part = part.translate((0.0, 0.0, TORSO_BAY_TOP_Z))
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
    # 站在**电池仓层板**上表面（唯一真值来源）。
    # ⚠️ 2026-09-11 从上层改到下层：上层净高 18.4 mm，树莓派(17)坐它上面会顶到顶环(63)；
    #    改到下层后，上层让给树莓派直接坐框架层板，本托盘在下层托 STM32/URT-1/功放。
    part = part.translate((0.0, 0.0, TORSO_BAY_TOP_Z))
    return sanitize(part)


def pdb_mount() -> cq.Workplane:
    """分线板座：4 路菊花链的物理根节点（standards.WIRING）。

    ⚠️ 2026-09-11：原来建在 link 原点 → 与 trunk_pitch 舵机 71% 重合（2 925 mm³）。
    现在挪到下舱**副轴侧空带**（电池占 y ±17，净宽 ±44），坐在框架层板上。
    """
    part = cq.Workplane("XY")
    part = part.union(box(46.0, 30.0, 3.0, at=(0, 0, 0)))
    for pt in [(-18.0, -11.0), (18.0, -11.0), (-18.0, 11.0), (18.0, 11.0)]:
        part = part.union(bosses([pt], od=5.0, height=3.0, bore_dia=2.2,
                                 bore_depth=4.0, z0=3.0))
    for dx in (-12.0, 0.0, 12.0):
        part = part.cut(box(6.0, 8.0, 6.0, at=(dx, 15.0, 0)))
    # 坐进下舱副轴侧空带（y = −30，净宽 ±44；46 mm 长边沿 X）
    part = part.translate((20.0, -30.0, TORSO_BAY_TOP_Z))
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
        "builder": compact_adapter, "count": 2, "material": "PETG", "infill": 0.60,
        "desc": "紧凑转接块（仅颈/腰 27.5 mm 短链）",
        "used_by": "head_yaw_link / trunk_roll_link",
    },
    "cluster_horn_arm": {
        "builder": cluster_horn_arm, "count": 6, "material": "PETG", "infill": 0.55,
        "intended_material": "6061-T6",
        "desc": "髋/肩错轴单侧臂（锁上一级舵盘，轴距 19.6 mm；承力目标 6061-T6）",
        "used_by": "hip_yaw→roll、hip_roll→pitch、shoulder_pitch→roll",
    },
    "cluster_outrigger": {
        "builder": cluster_outrigger, "count": 8, "material": "PETG", "infill": 0.55,
        "desc": "髋/肩外侧抱箍（端面 4×M2.5 + 副轴 MF106ZZ）",
        "used_by": "hip_roll/pitch ×2、shoulder_pitch/roll ×2",
    },
    "backpack_plate": {
        "builder": backpack_plate, "count": 1, "material": "PETG", "infill": 0.35,
        "desc": "背挂板（STM32 / URT-1 / XL4015 / 功放 / 喇叭）",
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
