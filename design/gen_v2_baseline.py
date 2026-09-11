#!/usr/bin/env python3
"""按 TonyPi Pro 参考机重建 A.T.R.I. 参数基线（v1 → v2）。

用法：
    python3 design/gen_v2_baseline.py            # 重建（一次性迁移，已迁移则拒绝重复执行）
    python3 design/gen_v2_baseline.py --check    # 只报告当前模型是否为 v2

为什么要重建
------------
v1 的 ``robot_model.json`` 里 **link 质量是"结构占位预算"（合计 1650 g）**，
既不含 22 只舵机（1210 g），也不含电子件与电池（351 g）。
后果：导出的 URDF 总质量 1.80 kg，而实物口径是 2.26 kg —— **喂给刚体引擎的动力学是错的**。

v2 做三件事：
1. **尺寸对齐参考机**：身高 475 → **373 mm**（对齐 TonyPi Pro 的 373 mm，见
   ``design/reference/tonypi_pro_baseline.json``）。
2. **质量改成真实分布**：link 质量 = 结构壳 + 装在该壳上的舵机 + 装在该壳里的电子件 + 分摊线束，
   使 `sum(link mass) == 实物口径总重`，URDF 可直接用于动力学仿真。
3. **配件位置落表**：每只舵机、每个电子件、每块结构件的宿主 link、坐标、尺寸、质量
   写入 ``design/placements.json``。

缩放口径（**非等比，理由充分**）
--------------------------------
    x（前后/足长/躯干深度） ×1.000  → 保持 123 mm
    y（左右/肩宽/髋距）     ×1.000  → 保持 190 mm（参考机 187）
    z（上下/身高）          ×0.785  → 475 → 373 mm

为什么不等比缩 x/y：
- 树莓派 4B 的边长 **85 mm** 与 3S 电池的边长 **88 mm** 决定了躯干内部净空下限，
  缩小 x 会迫使改用 CM4 或零板（参考机 106 mm 深正是因为它用的是 CM4 类方案）；
- 参考机的肩宽 187 mm ≈ 我们的 190 mm，**宽度本来就已对齐**，缩了反而不像参考机。
所以 v2 是"**同宽同深、矮 21%**"的构型，深度比参考机深 17 mm —— 这是一个明确的取舍，已记录。

结构件质量口径
--------------
按**面密度法**（薄壳假设）分配：每个 link 的结构质量 ∝ 其几何包围盒表面积，
总和锁定 ``STRUCTURE_TOTAL_G``。该值取 v1 的 CAD 实测 552 g 按身高缩减折算（≈500 g），
**不是**参考机那种 1.5–2 mm 铝板件的 ~400 g —— 后者是需要换工艺才能拿到的优化目标。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
import geometry  # noqa: E402

MODEL_PATH = HERE / "robot_model.json"
COMPONENTS_PATH = HERE / "components.json"
PLACEMENTS_PATH = HERE / "placements.json"
REFERENCE_PATH = HERE / "reference" / "tonypi_pro_baseline.json"

# --------------------------------------------------------------------------
# 设计常量（改这里即可重新定标）
# --------------------------------------------------------------------------
SCALE = {"x": 1.000, "y": 1.000, "z": 0.785}   # → 373 mm 高（对齐参考机）
STRUCTURE_TOTAL_G = 500.0                       # 结构件总预算（v1 CAD 552 g 按身高折算）
CABLE_MASS_G = 80.0                             # 线束
FASTENER_MASS_G = 40.0                          # 紧固件

SERVO = {
    "model": "飞特 STS3215（12V 版，SER0070 同类）",
    "qty": 22,
    "mass_g": 55.0,
    "size_mm": [45.2, 24.7, 35.0],
    "voltage_nominal_v": 11.1,
    "voltage_range_v": [9.0, 12.6],
    "stall_torque_nm": 2.94,
    "rated_torque_nm": 0.98,          # 【官方】额定负载 10 kg·cm @12V（2026-09-11 确认，见下列 basis）
    "rated_torque_basis": (
        "【官方】额定负载 10 kg·cm = 0.98 N·m @12V（DFRobot SER0070 + 飞特 STS3235 规格书双重印证，"
        "见 design/handoff/STS3215-官方规格书核验.md §4.1）。"
        "历史口径『堵转 × 50% = 1.47 N·m』偏乐观 50%，已降为并列参考（rated_torque_nm_half_stall_deprecated），"
        "不再是 rated_torque_nm"
    ),
    "rated_torque_nm_half_stall_deprecated": 1.47,   # 历史判据：堵转 × 50%，参考机选型习惯，偏乐观 50%
    "no_load_speed_dps": 270.0,       # 0.222 s/60°（12V，实物包装标签）→ 270 °/s；原 300 无出处
    "no_load_speed_basis": (
        "0.222 s/60°(12V) → 270 °/s。来源【实物包装标签】ST-3215-C018"
        "（见 design/reference/sts3215/）；0.18 与 300 °/s 均无出处，2026-09-11 订正"
    ),
    "protocol": "TTL 半双工串行总线 @1Mbps",
    "feedback": "位置 / 速度 / 负载 / 电压 / 电流 / 温度（12 位磁编码）",
    "price_cny": "85-95",
}

# 每只舵机装在哪个 link 上（= 它驱动的那个 joint 的父 link）
SERVO_MOUNT: Dict[str, List[str]] = {
    "pelvis": ["trunk_roll", "left_hip_yaw", "right_hip_yaw"],
    "trunk_roll_link": ["trunk_pitch"],
    "torso_upper": ["head_yaw", "left_shoulder_pitch", "right_shoulder_pitch"],
    "head_yaw_link": ["head_pitch"],
    "left_hip_yaw_link": ["left_hip_roll"],
    "right_hip_yaw_link": ["right_hip_roll"],
    "left_hip_roll_link": ["left_hip_pitch"],
    "right_hip_roll_link": ["right_hip_pitch"],
    "left_thigh": ["left_knee_pitch"],
    "right_thigh": ["right_knee_pitch"],
    "left_shank": ["left_ankle_pitch"],
    "right_shank": ["right_ankle_pitch"],
    "left_shoulder_pitch_link": ["left_shoulder_roll"],
    "right_shoulder_pitch_link": ["right_shoulder_roll"],
    "left_upper_arm": ["left_elbow_pitch"],
    "right_upper_arm": ["right_elbow_pitch"],
    "left_forearm": ["left_gripper"],
    "right_forearm": ["right_gripper"],
}

# 电子件与电池：宿主 link、质量、尺寸、在宿主 link 坐标系里的位置
ELECTRONICS: List[Dict[str, Any]] = [
    {"id": "compute", "name": "Raspberry Pi 4B (4GB)", "link": "torso_upper",
     "mass_g": 46.0, "size_mm": [85.0, 56.0, 17.0], "position_mm": [0.0, 0.0, -12.0],
     "note": "需 15 mm 散热高度；v2 躯干内净空 94×84×49，85 边放在 y 向（余量 4 mm）"},
    {"id": "mcu", "name": "STM32F405RGT6 核心板", "link": "torso_upper",
     "mass_g": 12.0, "size_mm": [52.0, 24.0, 12.0], "position_mm": [-30.0, 0.0, 18.0]},
    {"id": "servo_driver", "name": "飞特 URT-1 总线驱动板", "link": "torso_upper",
     "mass_g": 15.0, "size_mm": [40.0, 25.0, 12.0], "position_mm": [28.0, 0.0, 18.0]},
    {"id": "bec", "name": "XL4015 降压模块", "link": "torso_upper",
     "mass_g": 22.0, "size_mm": [65.0, 35.0, 25.0], "position_mm": [0.0, -28.0, 14.0]},
    {"id": "amp", "name": "PAM8403 功放模块", "link": "torso_upper",
     "mass_g": 5.0, "size_mm": [15.0, 12.0, 5.0], "position_mm": [-40.0, 34.0, 20.0]},
    {"id": "speaker", "name": "4Ω 3W 腔体喇叭 Φ28", "link": "torso_upper",
     "mass_g": 25.0, "size_mm": [28.0, 28.0, 15.0], "position_mm": [0.0, 0.0, 24.0]},
    {"id": "camera", "name": "UVC 广角相机模组 (OV9732/IMX219)", "link": "head",
     "mass_g": 15.0, "size_mm": [38.0, 38.0, 15.0], "position_mm": [18.0, 0.0, 6.0],
     "note": "装在头部前方，随 head_pitch 俯仰"},
    {"id": "mic", "name": "USB 免驱拾音模块 (CM6533)", "link": "head",
     "mass_g": 8.0, "size_mm": [25.0, 15.0, 8.0], "position_mm": [10.0, 0.0, -14.0]},
    {"id": "imu", "name": "ICM-42688-P 模块", "link": "pelvis",
     "mass_g": 3.0, "size_mm": [20.0, 15.0, 3.0], "position_mm": [0.0, 0.0, 8.0],
     "note": "装在骨盆（重心附近），避免头部摆动干扰姿态解算"},
    {"id": "battery", "name": "3S 11.1V 2000mAh 10C 锂聚合物 (XT60)", "link": "torso_upper",
     "mass_g": 165.0, "size_mm": [88.0, 34.0, 19.0], "position_mm": [0.0, 0.0, -26.0],
     "note": "容量对齐参考机（TonyPi Pro 为 11.1V 2000mAh 10C）；"
             "按仓库电源模型 30 min 任务需 ≥2.89 Ah，选型时须复核"},
]

REFERENCE_MACHINE = {
    "name": "幻尔 TonyPi Pro",
    "role": "参考构型（量产验证），非采购目标",
    "source": "https://www.hiwonder.com.cn/product-detail/TonyPi-Pro-2025.html",
    "envelope_mm": {"height": 373.0, "width": 187.0, "depth": 106.0},
    "mass_kg": 1.8,
    "dof": {"total": 20, "per_leg": 5, "per_arm": 4, "head": 2, "trunk": 0,
            "note": "身体 18 + 头 2；每臂 4 = 3 关节 + 1 开合手掌"},
    "material": "硬铝合金",
    "battery": "11.1V 2000mAh 10C",
    "endurance_min": 60,
    "servos": {
        "body": {"model": "LX-824HV", "qty": 18, "stall_torque_kgcm": 17.0,
                 "voltage_v": 11.1, "feedback": "电位器 / 角度+温度",
                 "topology": "三端口串联总线"},
        "head": {"model": "LFD-01M", "qty": 2, "mass_g": 13.5,
                 "size_mm": [22.3, 12.0, 23.2], "voltage_v": "4.8-6 (PWM)",
                 "stall_torque_kgcm": 1.8, "speed_s_per_60deg": 0.12},
    },
    "main_controller": "树莓派 4B (4GB) + 幻尔树莓派扩展板",
    "vision": "480P 120° 广角 + 2 DOF 云台",
    "voice": "WonderEcho Pro AI 语音交互盒",
    "price_cny_per_unit": 4600,
    "price_source": "山东大学浪潮人工智能学院 2026-08 采购 10 台共 ¥46,000",
    "derived_lessons": [
        "全机身用同一款舵机（18 个身体关节同型号），不做扭矩分档",
        "腿 5 DOF / 臂 4 DOF（含末端 1 DOF）/ 头 2 DOF 的分配有量产行走验证",
        "11.1V 高压总线比 7.4V 版电流低约 60%",
        "1.8 kg 机体用 1.67 N·m 堵转舵机可跑跨栏与上下台阶 → 连续可用 ≈ 堵转一半",
        "宽度与深度由树莓派 4B（85 mm 边）与 3S 电池决定，身高才是可压缩量",
    ],
    "unverified": ["LX-824HV 的外形尺寸/质量/空载速度/电流", "LX-824HV 单价",
                   "官方 URDF/CAD 是否公开", "每腿 5 个舵机的具体关节类型"],
}


# --------------------------------------------------------------------------
# 几何缩放
# --------------------------------------------------------------------------
def scale_geometry(geom: Dict[str, Any], s: Dict[str, float]) -> Dict[str, Any]:
    """按轴向缩放基元尺寸。半径类用 xy 平均（薄壳在横截面上等比）。"""
    out = dict(geom)
    kind = out.get("type", "")
    sx, sy, sz = s["x"], s["y"], s["z"]
    s_rad = (sx + sy) / 2.0          # 横截面半径的缩放
    s_all = (sx + sy + sz) / 3.0     # 各向同性量（圆角、球壳）取平均

    if "size_mm" in out:
        x, y, z = out["size_mm"]
        out["size_mm"] = [round(x * sx, 1), round(y * sy, 1), round(z * sz, 1)]
    if "fillet_mm" in out:
        out["fillet_mm"] = round(out["fillet_mm"] * s_all, 1)
    if "outer_r_mm" in out:
        out["outer_r_mm"] = round(out["outer_r_mm"] * s_all, 1)
    if "inner_r_mm" in out:
        out["inner_r_mm"] = round(out["inner_r_mm"] * s_all, 1)
    if "radius_mm" in out:
        out["radius_mm"] = round(out["radius_mm"] * s_rad, 1)
    if "height_mm" in out:
        out["height_mm"] = round(out["height_mm"] * sz, 1)
    if "length_mm" in out:
        out["length_mm"] = round(out["length_mm"] * sz, 1)
    if "origin_mm" in out:
        ox, oy, oz = out["origin_mm"]
        out["origin_mm"] = [round(ox * sx, 1), round(oy * sy, 1), round(oz * sz, 1)]
    # 记录缩放前的类型，便于下游识别（不影响既有读取）
    if kind:
        out["type"] = kind
    return out


def bbox_area(geom: Dict[str, Any]) -> float:
    x, y, z = geometry.bounding_box(geom)
    return 2.0 * (x * y + y * z + z * x)


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------
def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="按参考机重建 A.T.R.I. 参数基线 v2")
    ap.add_argument("--check", action="store_true", help="只报告当前模型版本")
    args = ap.parse_args(argv)

    model = json.loads(MODEL_PATH.read_text(encoding="utf-8"))
    version = str(model.get("version", "1.0"))

    if args.check:
        print(f"robot_model.json version = {version}")
        print(f"  身高 {model['overall']['height_mm']} mm，"
              f"整机质量 {model['overall']['mass_kg']} kg")
        return 0

    if version.startswith("2."):
        print("已是 v2，拒绝重复迁移（避免二次缩放）。改常量后请先在 git 里回退 robot_model.json。")
        return 1

    comps = json.loads(COMPONENTS_PATH.read_text(encoding="utf-8"))

    # ---- 1) 尺寸：关节原点 + link 几何 ----
    old_h = model["overall"]["height_mm"]
    old_mass = model["overall"]["mass_kg"]
    for j in model["joints"]:
        ox, oy, oz = j["origin_xyz_mm"]
        j["origin_xyz_mm"] = [round(ox * SCALE["x"], 1),
                              round(oy * SCALE["y"], 1),
                              round(oz * SCALE["z"], 1)]
    for link in model["links"]:
        link["geometry"] = scale_geometry(link["geometry"], SCALE)

    # ---- 2) 足底落地：两遍求 base_pose（不手算关节链，避免符号错） ----
    import gen_urdf  # noqa: E402  （纯标准库，同目录）
    model["base_pose_mm"] = [0.0, 0.0, 0.0]
    lowest = gen_urdf.measured_envelope(model)["min_z_mm"]
    model["base_pose_mm"] = [0.0, 0.0, round(-lowest, 1)]

    # ---- 3) 结构质量：面密度法 ----
    areas = {l["name"]: bbox_area(l["geometry"]) for l in model["links"]}
    total_area = sum(areas.values())
    struct_g = {n: STRUCTURE_TOTAL_G * a / total_area for n, a in areas.items()}

    # ---- 4) 舵机 / 电子件 / 线束分派 ----
    servo_g = {l["name"]: 0.0 for l in model["links"]}
    servo_list: List[Dict[str, Any]] = []
    joint_by_name = {j["name"]: j for j in model["joints"]}
    for link_name, joints in SERVO_MOUNT.items():
        for jn in joints:
            servo_g[link_name] += SERVO["mass_g"]
            j = joint_by_name[jn]
            servo_list.append({
                "joint": jn, "id": j["id"], "mounted_on_link": link_name,
                "position_mm": j["origin_xyz_mm"], "axis": j["axis"],
                "size_mm": SERVO["size_mm"], "mass_g": SERVO["mass_g"],
                "model": SERVO["model"],
            })
    assert len(servo_list) == SERVO["qty"], f"舵机数 {len(servo_list)} != {SERVO['qty']}"

    # 舵机作为"附加体"写进 link：球的关节壳**包不住** 45.2 mm 的舵机（check_fit 已证实），
    # 舵机是外挂在关节壳外、靠支架夹持的实体，必须进 collision 才能让自碰撞正确。
    # 电子件不写：它们装在壳内，壳的等效包围盒已经覆盖。
    for link in model["links"]:
        extras = []
        for i, s in enumerate(servo_list):
            if s["mounted_on_link"] != link["name"]:
                continue
            extras.append({
                "type": "box",
                "size_mm": list(SERVO["size_mm"]),
                "origin_mm": list(s["position_mm"]),
                "label": f"舵机 {SERVO['model'].split('（')[0]} — 驱动 {s['joint']}",
                "color": [0.25, 0.27, 0.32],
                "note": "长边沿 x 轴摆放（设计暂定），详细设计时按支架实际朝向复核",
            })
        if extras:
            link["extra_geometry"] = extras

    elec_g = {l["name"]: 0.0 for l in model["links"]}
    for e in ELECTRONICS:
        elec_g[e["link"]] += e["mass_g"]

    base_g = {l["name"]: struct_g[l["name"]] + servo_g[l["name"]] + elec_g[l["name"]]
              for l in model["links"]}
    harness_total = CABLE_MASS_G + FASTENER_MASS_G
    base_sum = sum(base_g.values())
    harness_g = {n: harness_total * m / base_sum for n, m in base_g.items()}

    for link in model["links"]:
        n = link["name"]
        s, sv, el, ha = struct_g[n], servo_g[n], elec_g[n], harness_g[n]
        link["mass_kg"] = round((s + sv + el + ha) / 1000.0, 5)
        link["mass_breakdown_g"] = {
            "structure": round(s, 1), "servos": round(sv, 1),
            "electronics": round(el, 1), "harness_fasteners": round(ha, 1),
        }

    total_g = sum(l["mass_kg"] for l in model["links"]) * 1000.0

    # ---- 5) 包络 ----
    env = gen_urdf.measured_envelope(model)
    height = env["height_mm"]
    width = env["width_mm"]
    depth = env["depth_mm"]

    # ---- 6) 写回 robot_model.json ----
    model["version"] = "2.0"
    model["description"] = (
        "A.T.R.I. 小人形组 22 DOF 设计模型 v2（尺寸对齐 TonyPi Pro 参考机，质量改为真实分布）。"
        "v2 的 link 质量 = 结构壳 + 装在其上的舵机 + 装在其内的电子件 + 分摊线束，"
        "因此 sum(link mass) == 实物口径总重，URDF 可直接用于刚体动力学仿真。"
    )
    model["overall"] = {
        "height_mm": round(height, 1),
        "width_mm": round(width, 1),
        "depth_mm": round(depth, 1),
        "mass_kg": round(total_g / 1000.0, 3),
        "note": (
            f"v2 包络；身高由 v1 的 {old_h:.1f} mm 缩到 {height:.1f} mm（z ×{SCALE['z']}）对齐参考机 373 mm；"
            f"宽/深保持（x/y ×1.0）—— 树莓派 4B 的 85 mm 边与 3S 电池的 88 mm 边决定躯干净空下限。"
        ),
    }
    model["reference_baseline"] = {
        "machine": REFERENCE_MACHINE["name"],
        "source": REFERENCE_MACHINE["source"],
        "scale_applied": SCALE,
        "aligned": {
            "height_mm": [REFERENCE_MACHINE["envelope_mm"]["height"], round(height, 1)],
            "width_mm": [REFERENCE_MACHINE["envelope_mm"]["width"], round(width, 1)],
            "depth_mm": [REFERENCE_MACHINE["envelope_mm"]["depth"], round(depth, 1)],
        },
        "deviations": [
            "深度比参考机深约 17 mm：躯干要装 85 mm 的树莓派 4B 与 88 mm 的 3S 电池",
            "比参考机多 2 个躯干关节（赛题『上肢+躯干 ≥10』要求），也多 2 只舵机",
            "结构按打印薄壳 500 g 计，参考机为 1.5–2 mm 铝板件（≈400 g）；换工艺可再省约 100 g",
        ],
    }
    model["mass_budget"] = {
        "structure_g": STRUCTURE_TOTAL_G,
        "servos_g": round(SERVO["mass_g"] * SERVO["qty"], 1),
        "electronics_g": round(sum(e["mass_g"] for e in ELECTRONICS), 1),
        "harness_fasteners_g": harness_total,
        "total_g": round(total_g, 1),
        "note": "全部摊入 link 质量；gen_handoff 的 cable/fastener 假设已置 0，避免重复计入。",
    }
    model["servo_defaults"] = {
        "model": SERVO["model"],
        "protocol": SERVO["protocol"],
        "voltage_nominal_v": SERVO["voltage_nominal_v"],
        "mass_g": SERVO["mass_g"],
        "size_mm": SERVO["size_mm"],
        "stall_torque_nm": SERVO["stall_torque_nm"],
        "rated_torque_nm": SERVO["rated_torque_nm"],
        "rated_torque_basis": SERVO["rated_torque_basis"],
        "rated_torque_nm_half_stall_deprecated": SERVO["rated_torque_nm_half_stall_deprecated"],
        "no_load_speed_dps": SERVO["no_load_speed_dps"],
        "speed_basis": SERVO["no_load_speed_basis"],
        "mounting": "M2.5/M3 支架夹持；STS3215 体对角线 62.3 mm，无法被现有球壳全包，采用外部支架",
    }
    model["changelog"] = [
        {"from": "1.0", "to": "2.0",
         "changes": [
             f"身高 {old_h:.1f} → {height:.1f} mm（z ×{SCALE['z']}，对齐参考机 373 mm）",
             "link 质量：结构占位预算 → 真实分布（结构 + 舵机 + 电子件 + 线束）",
             f"整机质量占位 {old_mass:.3f} → {total_g / 1000.0:.3f} kg（实物口径，含舵机与电子件）",
             "新增 placements.json：22 舵机 + 10 电子件 + 23 结构件的宿主/坐标/尺寸/质量",
             "新增 reference/tonypi_pro_baseline.json：参考机公开参数与可迁移结论",
         ]},
    ]

    MODEL_PATH.write_text(json.dumps(model, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")

    # ---- 7) 写 components.json ----
    comps["schema_version"] = "2.0"
    comps["note"] = (comps.get("note", "") +
                     "　【v2】结构件与线束质量按参考机对标口径更新；"
                     "舵机数量与型号不变，但额定扭矩改用有出处的判据（堵转 × 50%）。")
    comps["structure_mass_estimate_g"] = STRUCTURE_TOTAL_G
    comps["structure_mass_note"] = (
        f"v2：按参考机对标后的身高 373 mm 重估，取 v1 CAD 实测 552 g 的身高折算值。"
        f"参考机（373 mm、1.8 kg）为 1.5–2 mm 铝板件，结构约 400 g —— 换工艺可再省约 100 g。")
    comps["cable_mass_g"] = CABLE_MASS_G
    comps["fastener_mass_g"] = FASTENER_MASS_G
    for c in comps["components"]:
        if c["role"] == "servo_s":
            c["name"] = SERVO["model"]
            c["mass_g"] = SERVO["mass_g"]
            c["size_mm"] = SERVO["size_mm"]
            c["spec"]["rated_torque_nm"] = SERVO["rated_torque_nm"]
            c["spec"]["stall_torque_nm"] = SERVO["stall_torque_nm"]
            c["spec"]["voltage_v"] = SERVO["voltage_nominal_v"]
            c["spec"]["rated_basis"] = SERVO["rated_torque_basis"]
            c["spec"]["rated_torque_nm_half_stall_deprecated"] = SERVO["rated_torque_nm_half_stall_deprecated"]
            c["spec"]["speed_s_per_60deg"] = round(60.0 / SERVO["no_load_speed_dps"], 3)
            c["spec"]["speed_basis"] = SERVO["no_load_speed_basis"]
            c["note"] = ("全机型号归一；额定值取【官方】0.98 N·m（2026-09-11 确认）；"
                         "历史判据『堵转 × 50% = 1.47 N·m』偏乐观 50%，仅作并列参考")
        if c["role"] == "battery":
            c["name"] = "3S 11.1V 2000mAh 10C 锂聚合物 (XT60)"
            c["mass_g"] = 165.0
            c["size_mm"] = [88.0, 34.0, 19.0]
            c["note"] = "容量对齐参考机；按仓库电源模型 30 min 任务需 ≥2.89 Ah，选型时须复核"
    comps["placements"] = [
        {"component": e["name"], "link": e["link"], "size_mm": e["size_mm"],
         "mass_g": e["mass_g"], "position_mm": e["position_mm"],
         "note": e.get("note", "")}
        for e in ELECTRONICS
    ]
    comps["reference_alignment"] = model["reference_baseline"]
    COMPONENTS_PATH.write_text(json.dumps(comps, ensure_ascii=False, indent=2) + "\n",
                               encoding="utf-8")

    # ---- 8) 写 placements.json ----
    structures = []
    for link in model["links"]:
        bb = geometry.bounding_box(link["geometry"])
        structures.append({
            "link": link["name"], "group": link.get("group", ""),
            "primitive": link["geometry"].get("type", ""),
            "bbox_mm": [round(v, 1) for v in bb],
            "structure_mass_g": round(struct_g[link["name"]], 1),
            "total_link_mass_g": round(link["mass_kg"] * 1000.0, 1),
        })
    placements = {
        "schema_version": "2.0",
        "generated_by": "design/gen_v2_baseline.py",
        "units": {"length": "mm", "mass": "g", "angle": "deg", "axis": "URDF 约定（+z 向上）"},
        "frame_note": (
            "position_mm 是相对『宿主 link 坐标系原点』的偏移；link 坐标系原点落在驱动它的关节轴线上。"
            "舵机的位置 = 它驱动的那个关节的原点（即父 link 坐标系里的 joint origin）。"
            "全部为**设计位**，实物装配前须按采购件复测。"
        ),
        "servos": servo_list,
        "electronics": ELECTRONICS,
        "harness_fasteners": {
            "cable_g": CABLE_MASS_G, "fastener_g": FASTENER_MASS_G,
            "allocation": "按各 link 的（结构+舵机+电子）质量比例摊派（见各 link 的 harness_fasteners 分项）",
        },
        "structures": structures,
        "summary": {
            "links": len(model["links"]), "joints": len(model["joints"]),
            "servos": len(servo_list),
            "envelope_mm": [round(height, 1), round(width, 1), round(depth, 1)],
            "total_mass_g": round(total_g, 1),
            "mass_budget_g": model["mass_budget"],
        },
    }
    PLACEMENTS_PATH.write_text(json.dumps(placements, ensure_ascii=False, indent=2) + "\n",
                               encoding="utf-8")

    # ---- 9) 写参考机基线 ----
    REFERENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    REFERENCE_PATH.write_text(
        json.dumps(REFERENCE_MACHINE, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # ---- 10) 报告 ----
    print(f"v1 → v2 重建完成")
    print(f"  包络  {old_h:.1f} → {height:.1f} mm 高"
          f"｜{width:.1f} 宽｜{depth:.1f} 深")
    print(f"  质量  {total_g / 1000.0:.3f} kg"
          f"（结构 {STRUCTURE_TOTAL_G:.0f} + 舵机 {SERVO['mass_g'] * SERVO['qty']:.0f}"
          f" + 电子 {sum(e['mass_g'] for e in ELECTRONICS):.0f} + 线束紧固件 {harness_total:.0f}）")
    print(f"  配件  {len(servo_list)} 舵机 + {len(ELECTRONICS)} 电子件 + {len(structures)} 结构件")
    for p in (MODEL_PATH, COMPONENTS_PATH, PLACEMENTS_PATH, REFERENCE_PATH):
        print(f"  写出  {p.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
