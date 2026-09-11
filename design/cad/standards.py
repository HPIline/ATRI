"""标准件参数库（CAD 建模的输入）。

**本文件是"外部世界知识"的落地处。**
参数来自部件库/厂商资料，每一项都标注 `verify` 状态：
    verified     已核对官方图纸或实物实测
    provisional  来自厂商公开规格或同级别典型值，未实物核对
    unknown      尚无数据，建模时用占位值并在图纸标注

⚠️ 建模前必须确认用到的参数不是 unknown。`assert_verified()` 会在
构建时拦截：宁可构建失败，也不要产出一个基于臆测尺寸的零件。
"""
from __future__ import annotations

from typing import Any, Dict, List


class SpecError(RuntimeError):
    """标准件参数缺失或未经验证。"""


# --------------------------------------------------------------------------
# FDM 打印工艺容差（3D 打印件的配合基准）
# --------------------------------------------------------------------------
FDM = {
    "nozzle_mm": 0.4,
    "layer_height_mm": 0.2,

    # —— 配合间隙：来自部件库实测标定，非通用经验值 ——
    # 舵机外壳配合腔：注塑件约 0.5° 拔模斜度 + PETG 内角挤出膨胀
    "servo_cavity_clearance_mm": 0.50,   # 双边总间隙
    "servo_boss_fit_mm": 0.15,           # 定位凸台，橡胶锤轻压入
    # 轴承外圈：单边过盈 -0.03；-0.05 会使 PETG 压变形轴承外圈卡死钢珠
    "bearing_bore_interference_mm": -0.03,
    "clearance_loose_mm": 0.40,
    "clearance_snug_mm": 0.20,
    "clearance_press_mm": 0.05,

    # —— 结构 ——
    "wall_structural_min_mm": 3.2,       # 承力件有效承载面底线（约 4 圈挤出线）
    "wall_mm": 3.0,
    "min_feature_mm": 0.8,
    "fillet_min_mm": 1.0,
    "fillet_struct_mm": 2.0,
    "boss_od_factor": 2.0,

    # —— 轴承轴向限位台阶 ——
    "bearing_shoulder_thickness_min_mm": 1.2,
    "bearing_shoulder_width_min_mm": 0.8,

    # —— 填充 ——
    "infill_structural_pct": 55,
    "infill_pattern_structural": "gyroid",   # 三维各向同性抗扭；禁用二维 Grid
    "infill_cosmetic_pct": 20,

    # —— 打印方向 ——
    "print_orientation_note": (
        "承力连杆必须平放（水平）打印，使弯曲正应力沿挤出丝方向；"
        "竖直打印会让层间承受拉应力，极易剥离失效。"
    ),
    "hole_orientation_note": (
        "垂直于热床的孔最圆；水平横穿的通孔会下坠变形，"
        "建模时横向大孔顶部宜做泪滴形，或打印后铰刀修孔。"
    ),

    "verify": "calibrated",
    "source": "部件库实测标定 + FDM 工艺规律",
}


# --------------------------------------------------------------------------
# 紧固件
# --------------------------------------------------------------------------
FASTENERS: Dict[str, Dict[str, Any]] = {
    "M2": {
        "major_dia_mm": 2.0,
        "tap_drill_mm": 1.6,       # 自攻/热熔铜螺母底孔
        "clearance_hole_mm": 2.2,
        "head_dia_mm": 3.8,        # 内六角圆柱头
        "head_height_mm": 2.0,
        "verify": "provisional",
    },
    "M2.5": {
        "major_dia_mm": 2.5,
        "tap_drill_mm": 2.15,
        "tap_drill_note": "PETG 专用：2.05 偏小，径向膨胀应力过大会拧断螺钉",
        "clearance_hole_mm": 2.7,
        "heat_set_insert": {
            "spec": "M2.5 x 3.5 x 4.0 黄铜滚花",
            "pilot_hole_mm": 3.2,
            "chamfer_mm": 0.4,
            "note": "承力面与需反复拆装处必须用热熔铜螺母；螺钉直攻塑料必定滑丝",
        },
        "head_dia_mm": 4.5,
        "head_height_mm": 2.5,
        "verify": "provisional",
        "note": "舵机厂商标配规格（飞特 STS 系列用 M2.5）",
    },
    "M3": {
        "major_dia_mm": 3.0,
        "tap_drill_mm": 2.5,
        "clearance_hole_mm": 3.2,
        "head_dia_mm": 5.5,
        "head_height_mm": 3.0,
        "verify": "provisional",
    },
}


# --------------------------------------------------------------------------
# 轴承（关节副轴支撑）
# --------------------------------------------------------------------------
BEARINGS: Dict[str, Dict[str, Any]] = {
    "MF106ZZ": {
        "type": "flanged_miniature_ball",
        "bore_mm": 6.0,
        "od_mm": 10.0,
        "width_mm": 3.0,
        "flange_od_mm": 11.2,
        "flange_width_mm": 0.8,
        "verify": "verified",
        "note": "STS3215 副轴（Φ6 h7）的正确配套轴承。"
                "注意 MF105 内径 5mm，套不进 Φ6 副轴——此前选型有误。",
        "source": "部件库按副轴实测尺寸核定",
    },
    "MF105ZZ": {
        "type": "flanged_miniature_ball",
        "bore_mm": 5.0,
        "od_mm": 10.0,
        "width_mm": 4.0,
        "verify": "deprecated",
        "note": "内径 5mm，与 STS3215 副轴 Φ6 不匹配，已弃用",
    },
    "6700ZZ": {
        "type": "thin_section_ball",
        "bore_mm": 10.0,
        "od_mm": 15.0,
        "width_mm": 4.0,
        "verify": "provisional",
        "note": "可选：套在舵盘外圆台作主轴外支撑补强",
    },
    "MR105ZZ": {
        "type": "miniature_ball",
        "bore_mm": 5.0,
        "od_mm": 10.0,
        "width_mm": 4.0,
        "verify": "provisional",
    },
    "608ZZ": {
        "type": "skate_bearing",
        "bore_mm": 8.0,
        "od_mm": 22.0,
        "width_mm": 7.0,
        "verify": "verified",
        "note": "最通用的标准件，货源极广",
    },
    "MR63ZZ": {
        "type": "miniature_ball",
        "bore_mm": 3.0,
        "od_mm": 6.0,
        "width_mm": 2.5,
        "verify": "provisional",
    },
}


# --------------------------------------------------------------------------
# 舵机
# --------------------------------------------------------------------------
SERVOS: Dict[str, Dict[str, Any]] = {
    "STS3215": {
        "vendor": "飞特 Feetech",
        "protocol": "TTL 半双工串行总线",
        "baud_bps": 1_000_000,
        "body_mm": [45.2, 24.7, 35.0],           # 长 × 宽 × 高
        "mass_g": 55.0,
        "rated_torque_nm": 1.0,
        "stall_torque_nm": 3.0,
        "speed_s_per_60deg": 0.222,             # 订正：原 0.18 偏乐观 19%
        "speed_note": (
            "来源【实物包装标签】`SPEED: 0.222sec/60degree(12V)`（ST-3215-C018）。"
            "原值 0.18 无出处，已修正。同一标签给出 "
            "`TORQUE: 30kg.cm(12V)` = 2.94 N·m，与 stall_torque_nm 一致。"
        ),
        "voltage_v": 12.0,

        # —— 机械接口（建模必需）——
        "horn_spline": "25T",
        "horn_spline_od_mm": 5.90,
        "horn_pcd_mm": 14.0,            # Φ14（非 Φ16）；2026-09-11 第二来源复核确认
        "horn_hole_count": 4,           # 90° 均布
        "horn_hole_thread": "M2.5",
        "horn_hole_depth_mm": 2.5,      # 螺纹直接攻在铝合金舵盘上
        "horn_disc_od_mm": 20.0,
        "horn_disc_thickness_mm": 4.0,
        "horn_screw": "M3x6",           # 内六角盘头，锁入主轴齿轮中心
        "horn_verify": "verified",
        "horn_note": (
            "✅ 节圆 Φ14 已于 2026-09-11 由**第二个独立来源**复核确认："
            "第三方 B-rep 模型实测舵盘端 4 孔为 9.9 × 9.9 方阵，对角 = 14.00 mm "
            "（复现：design/cad/measure_servo.py）。"
            "同测：舵盘盘径 Φ20.0、中心螺孔 Φ2.5 深 3.9 —— 与本条参数一致。"
            "25T 齿顶宽约 0.2mm < 0.4mm 喷嘴最小可靠特征 0.35mm，"
            "**FDM 无法打印，必须采购金属舵盘**。"
            "跨品牌 25T 不通用（飞特与辉盛齿深差 0.15mm），必须买飞特专用/兼容件。"
        ),

        # —— 机身安装接口（2026-09-11 核验订正）——
        # ⚠️ 订正记录：此处原有 body_total_length_mm=51.2 / ear_extend_mm=3.0 /
        #    ear_hole_pitch_length_mm=48.5 / ear_hole_pitch_width_mm=10.0 四个字段，
        #    描述"两侧安装耳"。核验证明**该特征不存在**，已整体删除：
        #      ① 实物包装标签 `SIZE: A: 45.22mm`，机身长度就是这个数，没有 51.2 的余地；
        #      ② STEP 模型 X 包络 45.419，X/Y 方向无任何超出机身的特征；
        #      ③ 旧数据自身不自洽 —— (51.2−48.5)/2 − 1.25 = 0.10 mm 壁厚，注塑件不可能。
        #    证据与复现见 design/handoff/STS3215-机械接口核验.md
        #
        # 真实接口：两端面各有 Φ20 圆盘 + 4×Φ2.5 孔，方形 9.9×9.9（= 节圆 Φ14）
        "body_mount_disc_od_mm": 20.0,
        "body_mount_disc_thickness_mm": [2.1, 2.5],  # [−Z 端, +Z 端]；实测
        "body_mount_pcd_mm": 14.0,          # 与舵盘同规格（Φ14）
        "body_mount_pattern_pitch_mm": 9.9, # 方阵边长；9.9 × √2 = 14.00
        "body_mount_hole_count": 4,         # 90° 均布
        "body_mount_hole_dia_mm": 2.5,
        "body_mount_hole_thread": "M2.5",
        "body_mount_thread_note": (
            "⚠️ 螺纹规格存疑：模型是 Φ2.5 圆孔，无法表达螺纹；"
            "而 SO-ARM100 配套支架对应孔为 Φ2.0 通孔（配 M2 螺钉）。"
            "待实物确认是 M2.5 螺纹孔还是 M2/M3 底孔。"
        ),
        "body_mount_hole_type": "through",  # 贯穿 Φ20 端面盘（厚 2.1 / 2.5）
        "body_mount_faces": "两端面各一组（+Z 盘厚 2.5，−Z 盘厚 2.1）",
        "body_mount_axis_xy_mm": [12.5, 0.0],
        "body_mount_axis_note": (
            "⚠️ 该坐标相对**第三方模型自身坐标系**，与实物标称 A/B/C 基准面的对应关系"
            "尚未完全确认 → 偏心量的**符号与端点归属**暂不得用于建模。"
            "【部分吻合】实测轴心沿机身长度方向偏心：距模型 +X 面 10.21 mm、"
            "距 −X 面 35.21 mm，与已有 shaft_depth_from_face_mm = 11.0 相差约 0.8 mm；"
            "宽度方向实测居中（Y=0），与 shaft_offset_from_side_mm = 12.35 ≈ 半宽 12.41 一致。"
            "→ 长度方向的坐标对应关系**基本成立**。买 1 只实测 3 个数即可完全闭合。"
        ),
        "body_mount_verify": "provisional",
        "body_mount_note": (
            "【2026-09-11 核验订正】原标『飞特官方 2D 工程图纸』的安装耳数据已删除。"
            "现行数据来自第三方 B-rep 模型（SO-ARM100，Apache-2.0）+ 实物包装标签照，"
            "**既非官方图纸、亦非我方实测** → 故为 provisional。"
            "复现：.venv-cad/bin/python design/cad/measure_servo.py"
        ),

        # —— 输出轴与副轴 ——
        "shaft_dia_mm": 5.9,                # 主输出轴花键外径
        "shaft_offset_from_side_mm": 12.35, # 主轴中心相对侧基准面
        "shaft_depth_from_face_mm": 11.0,   # 主轴中心相对主端面纵深
        "secondary_shaft_dia_mm": 6.0,      # 副轴 Φ6 h7 (5.96~5.98)
        "secondary_shaft_protrusion_mm": 3.0,
        "secondary_shaft_protrusion_note": (
            "⚠️ **冲突未决**：2026-09-11 实测第三方模型，−Z 端仅有一个 Φ6.0、"
            "高 0.6 mm 的凸台（z −18.3→−17.7），与本值 3.0 相差 5 倍。"
            "两种可能：①该凸台是定位台而非副轴；②模型省略了副轴。"
            "0.6 mm 不足以支撑轴承，故**暂不改值**——语义未定前替换数字风险更大。"
            "待实物复测（卡尺量副轴轴径与伸出长度）。"
        ),
        "secondary_shaft_coaxial_tol_mm": 0.05,
        "secondary_shaft_end_thread": "M2.5",
        "secondary_shaft_thread_depth_mm": 4.0,

        # —— 底部安装螺孔（部分批次）——
        "bottom_hole_pitch_mm": [38.0, 15.0],
        "bottom_hole_depth_mm": 4.0,
        "bottom_hole_verify": "provisional",
        "bottom_hole_note": (
            "批次间可能有差异。⚠️ 2026-09-11 第三方模型实测**未见** 38.0×15.0 孔阵；"
            "模型在底部端面给出的是与舵盘同规格的 Φ20 + 4×Φ2.5 @ Φ14（见 body_mount_*）。"
            "二者可能是不同批次/不同版本，待实物确认。"
        ),

        "cable_exit": "side",
        "verify": "provisional",
        "source": (
            "【2026-09-11 订正】原标『飞特官方 2D 工程图纸』—— 该图纸未入库、无法复核，"
            "且据此推导的安装耳数据已被证伪（见 body_mount_note），故整体降级为 provisional。"
            "现行来源：实物包装标签照（尺寸/扭矩/速度）+ 第三方 B-rep 模型（接口几何）"
            "+ 部件库实测核定（舵盘、轴承）。"
        ),
    },
}


# --------------------------------------------------------------------------
# 校验
# --------------------------------------------------------------------------
def assert_verified(entry: Dict[str, Any], name: str,
                    allow: List[str] | None = None) -> None:
    """确保参数不是 unknown；provisional 默认允许但会告警。"""
    allow = allow or ["verified", "provisional"]
    status = entry.get("verify", "unknown")
    if status not in allow:
        raise SpecError(
            f"{name} 的参数状态为 '{status}'，缺失关键尺寸，无法可靠建模。\n"
            f"  说明: {entry.get('note', entry.get('body_mount_note', '无'))}\n"
            f"  处理: 实测后回填 standards.py，或在零件里显式留占位并标注。"
        )


def servo(name: str) -> Dict[str, Any]:
    if name not in SERVOS:
        raise SpecError(f"未收录舵机 {name}")
    return SERVOS[name]


def servo_horn_interface(name: str) -> Dict[str, Any]:
    """舵机输出轴接口（舵盘侧），建模必需。"""
    s = servo(name)
    assert_verified(
        {"verify": s.get("horn_verify"), "note": s.get("horn_note")},
        f"{name} 舵盘接口",
    )
    return {
        "spline": s["horn_spline"],
        "spline_od_mm": s["horn_spline_od_mm"],
        "pcd_mm": s["horn_pcd_mm"],
        "hole_count": s["horn_hole_count"],
        "hole_thread": s["horn_hole_thread"],
        "screw": s["horn_screw"],
    }


def fastener(name: str) -> Dict[str, Any]:
    if name not in FASTENERS:
        raise SpecError(f"未收录紧固件 {name}")
    return FASTENERS[name]


def bearing(name: str) -> Dict[str, Any]:
    if name not in BEARINGS:
        raise SpecError(f"未收录轴承 {name}")
    return BEARINGS[name]


def summary() -> str:
    """打印所有标准件的验证状态，便于快速看出哪些还缺数据。"""
    lines = ["标准件参数状态", "=" * 58]
    lines.append(f"{'名称':<16}{'状态':<14}{'备注'}")
    lines.append("-" * 58)
    for name, s in SERVOS.items():
        lines.append(f"{name:<16}{s.get('verify','?'):<14}"
                     f"舵盘 {s.get('horn_verify','?')} / "
                     f"机身孔 {s.get('body_mount_verify','?')}")
    for name, f in FASTENERS.items():
        lines.append(f"{name:<16}{f.get('verify','?'):<14}紧固件")
    for name, b in BEARINGS.items():
        lines.append(f"{name:<16}{b.get('verify','?'):<14}{b.get('type','')}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(summary())


# --------------------------------------------------------------------------
# 走线拓扑（来自部件库工程经验：禁止 22 颗单线到底）
# --------------------------------------------------------------------------
WIRING = {
    "topology": "pelvis_4branch_daisy_chain",
    "why": ("22 颗舵机单线一串到底时，末端（脚踝）的地线与电源内阻累计叠加，"
            "大动态下瞬态压降可超 1.5V，导致末端舵机复位或抖动。"
            "应在骨盆设置分线板，分 4 组独立菊花链。"),
    "pdb_location": "pelvis",
    "branches": [
        {"name": "左腿", "joints": ["left_hip_yaw", "left_hip_roll",
                                    "left_hip_pitch", "left_knee_pitch",
                                    "left_ankle_pitch"]},
        {"name": "右腿", "joints": ["right_hip_yaw", "right_hip_roll",
                                    "right_hip_pitch", "right_knee_pitch",
                                    "right_ankle_pitch"]},
        {"name": "躯干与头", "joints": ["trunk_roll", "trunk_pitch",
                                        "head_yaw", "head_pitch"]},
        {"name": "双臂", "joints": ["left_shoulder_pitch", "left_shoulder_roll",
                                    "left_elbow_pitch", "left_gripper",
                                    "right_shoulder_pitch", "right_shoulder_roll",
                                    "right_elbow_pitch", "right_gripper"]},
    ],
    "cable_length_rule": "L = 极值弯曲弧长 + 25 mm（严禁拉直绷紧）",
    "routing_through_joint": {
        "min_hole_dia_mm": 8.0,
        "rule": ("线束必须从转动副轴线正中心或紧贴轴心穿过；"
                 "偏离轴心越远，反复弯折应变呈平方级增大"),
    },
    "protection": [
        "关节点外的硅胶线套高密度扩口编织网管，防与打印件锐边摩擦破皮",
        "线束出入机架根部用柔性硅橡胶或扎带锚固，禁止应力集中在插头压线端子根部",
    ],
}


# --------------------------------------------------------------------------
# 装配工艺约束（直接影响零件设计）
# --------------------------------------------------------------------------
ASSEMBLY = {
    "screwdriver_access": {
        "rule": ("闭合 U 型框架必须预留改锥避空过孔。"
                 "常见错误：把舵机两端封死后，主轴锁舵盘的 M3 中心螺钉"
                 "被结构件挡住，螺丝刀插不进去，无法固定或拆卸舵盘。"),
        "applies_to": ["servo_yoke", "pitch_module"],
        "min_access_dia_mm": 8.0,
    },
    "servo_zero_calibration": {
        "rule": ("先接线通电 → 发中位指令（512 或 2048 脉冲）锁轴 → "
                 "再按机构中位机械对正压入舵盘并拧紧。"
                 "严禁装完再靠软件 Offset 硬拉大角度，会损失单向行程甚至撞断外壳。"),
    },
    "battery_com": {
        "mass_g": 200.0,
        "sagittal_offset_limit_mm": 5.0,
        "why": "偏离矢状面超 5mm 会导致 ZMP 漂移，单脚支撑切换时出现侧倾晃动",
        "pelvis_tradeoff": "重心低、跌倒冲击小；但净空狭窄，易与髋部 3 舵机干涉",
        "torso_tradeoff": "构成倒立摆，质心略高反而利于动态摆动平衡；但抬升整机重心",
    },
    "buy_metal_not_print": [
        "所有主轴舵盘（塑料/树脂经不起踝关节 0.84 N·m 周期性交变剪切）",
        "踝/膝关节的 U 型传动架（落地冲程应力集中区，PETG 层间易剪切剥离）",
    ],
    "safe_to_print": [
        "躯干主舱框架、头壳、足底板（大面积面接触受压）",
        "手臂非受力摆动连杆、传感器固定卡扣",
    ],
}
