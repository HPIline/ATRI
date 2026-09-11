#!/usr/bin/env python3
"""从设计模型推导**真实硬件选型需求**，产出交给下游（部件库/Gemini）的交接数据。

这个脚本回答的是"选什么零件"，而不是"长什么样"：
  - 每个关节的重力保持力矩需求（含安全系数）→ 决定舵机扭矩等级
  - 每个关节的最大角速度需求          → 决定舵机速度等级
  - 功率预算                          → 决定电池容量与电源架构
  - 各处可用安装空腔体积              → 决定主控板/相机尺寸上限
  - 接口清单                          → 决定总线/通信方案

输出：design/handoff/hardware_requirements.json
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import geometry  # noqa: E402
import gen_urdf  # noqa: E402

OUT_DIR = HERE / "handoff"
G = 9.81  # m/s²

# 设计假设（必须显式写出，下游才知道这些数是估的还是实测）
ASSUMPTIONS = {
    "safety_factor_static": 1.8,
    "note_safety_factor_static": (
        "静力保持力矩 × 1.8：覆盖加减速动态载荷、地面冲击、"
        "以及舵机个体差异。工业做法通常 1.5–2.0，取中值偏高。"
    ),
    "servo_efficiency": 0.75,
    "note_servo_efficiency": "舵机从电功率到机械功率的效率，含减速箱损耗。",
    "cable_mass_kg": 0.0,
    "note_cable_mass_kg": ("v2 起线束质量已按比例摊入各 link（见 design/placements.json 的 "
                           "harness_fasteners），此处置 0，避免与 link 质量重复计入。"),
    "fastener_mass_kg": 0.0,
    "note_fastener_mass_kg": ("v2 起紧固件质量已按比例摊入各 link，此处置 0，避免重复计入。"),
    "battery_energy_density_wh_per_kg": 110.0,
    "note_battery_energy_density_wh_per_kg": ("按**整包**计（电芯+外壳+线材+接头）约 110 Wh/kg；"
                     "电芯单体约 180 Wh/kg，不能直接拿来估整包重量。"),
    "usable_discharge_fraction": 0.8,
    "note_usable_discharge_fraction": "锂聚合物不建议放空，按 80% 可用容量选型。",
    "walking_duty_cycle": 0.35,
    "note_walking_duty_cycle": "行走时舵机平均输出占『最大静力保持』的比例。",
    "angular_accel_rad_s2": 25.0,
    "note_angular_accel_rad_s2": ("摆腿/摆臂的典型角加速度。用于估算惯性扭矩——"
                           "竖直轴关节（如髋 yaw、头 yaw）重力力臂≈0，"
                           "必须靠惯性项才能给出有意义的选型下限。"),
    "gait_cop_offset_mm": 25.0,
    "note_gait_cop_offset_mm": ("行走时的地面反力作用点（CoP）相对关节轴线的最大水平偏移。"
                      "站立时 CoP 在足心附近，行走/加减速时会前后移动；"
                      "取 25mm 作为中等步幅下的估算值。"),
    "stance_dynamic_factor": 2.0,
    "note_stance_dynamic_factor": ("单腿支撑期的动载系数：落脚冲击、重心起伏、"
                            "加减速惯性都会放大关节力矩。静力分析无法覆盖，"
                            "按 2.0 估算。"),
    "min_practical_torque_nm": 0.25,
    "note_min_practical_torque_nm": ("工程下限：低于此值的舵机在齿轮刚度、回程间隙、"
                        "摩擦与抗扰上都不可用，即使算出来需求更小。"),
}


# --------------------------------------------------------------------------
# 运动学子树
# --------------------------------------------------------------------------
def build_children(model: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {}
    for j in model["joints"]:
        out.setdefault(j["parent"], []).append(j)
    return out


def subtree_links(model: Dict[str, Any], joint: Dict[str, Any]) -> List[str]:
    """返回该关节以下（含）的所有 link 名称。"""
    children = build_children(model)
    out: List[str] = []

    def walk(link: str) -> None:
        out.append(link)
        for j in children.get(link, []):
            walk(j["child"])

    walk(joint["child"])
    return out


def link_com_local(model: Dict[str, Any], name: str) -> Tuple[float, float, float]:
    """link 质心在其自身坐标系中的位置（用几何 offset 近似，忽略密度不均）。"""
    link = next(l for l in model["links"] if l["name"] == name)
    ox, oy, oz = geometry.geometry_origin(link["geometry"])
    return (ox, oy, oz)


def com_relative_to_joint(model: Dict[str, Any], joint: Dict[str, Any],
                          link_name: str) -> Tuple[float, float, float]:
    """某个下游 link 的质心，相对该关节坐标系的位移（零姿态，单位 mm）。"""
    # 沿链从 joint.child 走到 link_name，累加各关节 origin
    # URDF 中 joint.origin 是"父 link -> 子 link"的变换，子 link 坐标系本身
    # 就在关节处。因此只累加路径上**其它**关节的 origin，不含目标关节自己。
    chain: List[Dict[str, Any]] = []
    by_child = {j["child"]: j for j in model["joints"]}
    cur = link_name
    while cur in by_child:
        j = by_child[cur]
        if j["name"] == joint["name"]:
            break
        chain.append(j)
        cur = j["parent"]
    chain.reverse()

    x = y = z = 0.0
    for j in chain:
        x += j["origin_xyz_mm"][0]
        y += j["origin_xyz_mm"][1]
        z += j["origin_xyz_mm"][2]
    cx, cy, cz = link_com_local(model, link_name)
    return (x + cx, y + cy, z + cz)


def perpendicular_arm(offset_mm: Tuple[float, float, float],
                      axis: List[float]) -> float:
    """质心到关节轴线的垂直距离（mm）—— 即重力力矩的力臂。"""
    p = offset_mm
    n = math.sqrt(sum(a * a for a in axis)) or 1.0
    a = [v / n for v in axis]
    along = sum(p[i] * a[i] for i in range(3))
    perp = [p[i] - along * a[i] for i in range(3)]
    return math.sqrt(sum(v * v for v in perp))


# --------------------------------------------------------------------------
# 力矩需求
# --------------------------------------------------------------------------
def _tier(tau_req_nm: float) -> str:
    """按需求力矩分档，供下游按档位找候选舵机。"""
    if tau_req_nm >= 4.0:
        return "XL"
    if tau_req_nm >= 2.5:
        return "L"
    if tau_req_nm >= 1.2:
        return "M"
    return "S"


def pct_str(margin: float) -> str:
    """裕度百分比（向上取整）：避免 100.5% 被显示成 100%，看不出已超限。"""
    return f"{math.ceil(margin * 100.0 - 1e-9)}%"


def total_mass_of(model: Dict[str, Any]) -> float:
    """整机质量（含线束与紧固件），用于单腿支撑载荷计算。"""
    return (sum(l["mass_kg"] for l in model["links"])
            + ASSUMPTIONS["cable_mass_kg"] + ASSUMPTIONS["fastener_mass_kg"])


def torque_criteria(model: Dict[str, Any]) -> Dict[str, Any]:
    """舵机扭矩的两个口径（均取自 servo_defaults，缺省回退到已知值）。

    - continuous_rated_torque_nm：官方额定负载，可持续工况，**选型主判据**；
    - peak_torque_nm：堵转 × 50%，只能短时峰值，比官方额定乐观 50%。
    """
    ts = model.get("servo_defaults", {})
    return {
        "continuous_rated_torque_nm":
            float(ts.get("continuous_rated_torque_nm", 0.98)),
        "peak_torque_nm": float(ts.get("peak_torque_nm", 1.47)),
        "stall_torque_nm": float(ts.get("stall_torque_nm", 2.94)),
    }



_TOTAL_MASS_CACHE: Dict[int, float] = {}


def joint_torque(model: Dict[str, Any], joint: Dict[str, Any]) -> Dict[str, Any]:
    """计算该关节的力矩需求（三种工况取包络）。"""
    key = id(model)
    if key not in _TOTAL_MASS_CACHE:
        _TOTAL_MASS_CACHE[key] = total_mass_of(model)
    total_mass_all = _TOTAL_MASS_CACHE[key]
    links = subtree_links(model, joint)
    total_mass = 0.0
    total_moment = 0.0  # Σ m·r，单位 kg·mm
    detail = []
    for name in links:
        link = next(l for l in model["links"] if l["name"] == name)
        m = float(link["mass_kg"])
        off = com_relative_to_joint(model, joint, name)
        r = perpendicular_arm(off, joint["axis"])
        total_mass += m
        total_moment += m * r
        detail.append({"link": name, "mass_kg": m,
                       "arm_mm": round(r, 2)})

    # 重力保持力矩：τ = Σ m·g·r
    tau_grav = total_moment / 1000.0 * G  # kg·mm -> kg·m -> N·m

    # 惯性力矩：τ = I·α，I = Σ m·r²
    inertia = 0.0
    for d in detail:
        r_m = d["arm_mm"] / 1000.0
        inertia += d["mass_kg"] * r_m * r_m
    alpha = ASSUMPTIONS["angular_accel_rad_s2"]
    tau_inertia = inertia * alpha

    sf = ASSUMPTIONS["safety_factor_static"]
    floor = ASSUMPTIONS["min_practical_torque_nm"]

    # 单腿支撑工况：支撑腿的关节要承担**全身重量**，而不只是下游腿段。
    # 这是腿部关节真正的选型依据——静力"下游质量法"会严重低估。
    # 关节本身没有 group 字段，要从子 link 取
    child_link = next((l for l in model["links"] if l["name"] == joint["child"]),
                      None)
    group = (child_link or {}).get("group", "")
    tau_stance = 0.0
    mass_above = 0.0
    if group in ("leg_l", "leg_r"):
        mass_above = max(0.0, total_mass_all - total_mass)
        tau_stance = (mass_above * G * (ASSUMPTIONS["gait_cop_offset_mm"] / 1000.0)
                      * ASSUMPTIONS["stance_dynamic_factor"])

    tau_req = max(tau_grav * sf, tau_inertia * sf, tau_stance, floor)

    # 两个口径的裕度：主判据是官方连续额定，堵转 × 50% 只作短时峰值参考
    crit = torque_criteria(model)
    margin_continuous = tau_req / crit["continuous_rated_torque_nm"]
    margin_peak = tau_req / crit["peak_torque_nm"]

    # 主导因素，便于下游理解这个数是怎么来的
    cands = {
        "gravity": tau_grav * sf,
        "inertia": tau_inertia * sf,
        "stance": tau_stance,
        "practical_floor": floor,
    }
    driver = max(cands, key=lambda k: cands[k])
    if cands[driver] <= floor + 1e-9:
        driver = "practical_floor"

    return {
        "joint": joint["name"],
        "id": joint["id"],
        "axis": joint["axis"],
        "limit_deg": joint["limit_deg"],
        "max_speed_dps": joint["velocity_dps"],
        "distal_mass_kg": round(total_mass, 4),
        "max_arm_mm": round(max((d["arm_mm"] for d in detail), default=0.0), 2),
        "distal_inertia_kgm2": round(inertia, 6),
        "gravity_torque_nm": round(tau_grav, 4),
        "inertia_torque_nm": round(tau_inertia, 4),
        "stance_torque_nm": round(tau_stance, 4),
        "stance_mass_above_kg": round(mass_above, 4),
        "required_torque_nm": round(tau_req, 4),
        "requirements_driver": driver,
        "safety_factor": sf,
        "continuous_rated_torque_nm": crit["continuous_rated_torque_nm"],
        "peak_torque_nm": crit["peak_torque_nm"],
        "margin_vs_continuous_rated": round(margin_continuous, 3),
        "margin_vs_peak": round(margin_peak, 3),
        "exceeds_continuous_rated": bool(margin_continuous > 1.0 + 1e-9),
        "exceeds_peak": bool(margin_peak > 1.0 + 1e-9),
        "torque_tier": _tier(tau_req),
        "design_placeholder_nm": joint.get("effort_nm"),
        "detail": detail,
    }


# --------------------------------------------------------------------------
# 空腔体积（可安装电子件的空间）
# --------------------------------------------------------------------------
def cavity(model: Dict[str, Any], link_name: str,
           wall_mm: float = 2.5) -> Dict[str, Any]:
    """壳体内部可用空间：外形尺寸每边扣掉壁厚。"""
    link = next(l for l in model["links"] if l["name"] == link_name)
    sx, sy, sz = geometry.bounding_box(link["geometry"])
    ix = max(0.0, sx - 2 * wall_mm)
    iy = max(0.0, sy - 2 * wall_mm)
    iz = max(0.0, sz - 2 * wall_mm)
    return {
        "link": link_name,
        "outer_mm": [sx, sy, sz],
        "wall_mm": wall_mm,
        "inner_mm": [round(ix, 1), round(iy, 1), round(iz, 1)],
        "inner_volume_cm3": round(ix * iy * iz / 1000.0, 1),
    }


# --------------------------------------------------------------------------
# 功率预算
# --------------------------------------------------------------------------
def power_budget(model: Dict[str, Any], torques: List[Dict[str, Any]],
                 mission_min: float = 30.0) -> Dict[str, Any]:
    """由力矩需求估算电流与电池容量。

    方法：舵机电流与输出扭矩近似成正比。
        工作扭矩   = 需求扭矩 × operating_fraction
        单关节电流 = 堵转电流 × (工作扭矩 / 堵转扭矩)，上限为堵转电流
    不能给"总堵转电流"乘占空比——那会把电流高估数倍。
    """
    operating_fraction = 0.35   # 行走时平均输出占"最大静力保持"的比例
    stall_torque = 2.94         # N·m，STS3215 级堵转扭矩（电流-扭矩线性模型的参考点）
    stall_current = 2.7         # A，同级别堵转电流

    per_joint = []
    total_current = 0.0
    for t in torques:
        tau_op = t["required_torque_nm"] * operating_fraction
        ratio = min(1.0, tau_op / stall_torque) if stall_torque > 0 else 0.0
        i = stall_current * ratio
        total_current += i
        per_joint.append({
            "joint": t["joint"],
            "operating_torque_nm": round(tau_op, 4),
            "current_a": round(i, 3),
        })

    voltage = 11.1
    compute_w = 6.0   # 树莓派 4B 级中等负载
    sensor_w = 1.5    # 相机 + 麦克风 + IMU
    logic_at_5v = (compute_w + sensor_w) / 5.0
    logic_at_pack = (compute_w + sensor_w) / voltage

    usable = ASSUMPTIONS["usable_discharge_fraction"]
    pack_ah = (total_current + logic_at_pack) * mission_min / 60.0
    energy_wh = pack_ah * voltage
    nameplate_ah = pack_ah / usable
    nameplate_wh = energy_wh / usable
    mass_kg = nameplate_wh / ASSUMPTIONS["battery_energy_density_wh_per_kg"]

    # 敏感性：现电池 165 g（components.json battery），换 mass_kg 级后总重与单腿支撑扭矩上升。
    # 只作说明，不改 robot_model.json 的质量分布（改质量会连带 URDF 与全部生成物）。
    cur_batt_kg = 0.165
    new_batt_kg = round(mass_kg, 2)
    base_total_kg = total_mass_of(model)
    new_total_kg = base_total_kg - cur_batt_kg + new_batt_kg
    mass_ratio = new_total_kg / base_total_kg
    ankle = next((t for t in torques if t["joint"] == "left_ankle_pitch"), None)
    sensitivity_note = ""
    if ankle is not None:
        cont = ankle["continuous_rated_torque_nm"]
        new_ankle = ankle["required_torque_nm"] * mass_ratio
        new_pct = math.ceil(new_ankle / cont * 100.0 - 1e-9)
        sensitivity_note = (
            f"满足 {mission_min:.0f} min 需把电池由 {cur_batt_kg * 1000:.0f} g "
            f"增到约 {new_batt_kg * 1000:.0f} g，整机约 {new_total_kg:.2f} kg，"
            f"单腿支撑扭矩随之上升约 {(mass_ratio - 1) * 100:.1f}%"
            f"（踝约 {new_ankle:.2f} N·m ≈ {new_pct}%），即结论只会更差。")

    return {
        "servo_bus_voltage_v": voltage,
        "servo_count": len(torques),
        "current_model": "电流 ∝ 输出扭矩（线性近似）",
        "operating_fraction": operating_fraction,
        "stall_torque_ref_nm": stall_torque,
        "stall_current_a": stall_current,
        "avg_servo_current_a": round(total_current, 2),
        "logic_rail_v": 5.0,
        "logic_current_at_5v_a": round(logic_at_5v, 2),
        "logic_current_at_pack_a": round(logic_at_pack, 2),
        "total_avg_current_at_pack_a": round(total_current + logic_at_pack, 2),
        "mission_min": mission_min,
        "consumed_ah": round(pack_ah, 2),
        "consumed_wh": round(energy_wh, 1),
        "usable_fraction": usable,
        "required_nameplate_ah": round(nameplate_ah, 2),
        "required_nameplate_wh": round(nameplate_wh, 1),
        "estimated_battery_mass_kg": round(mass_kg, 2),
        "sensitivity_note": sensitivity_note,
        "per_joint_current": per_joint,
        "note": ("工作占比 0.35 与额定参数为同级别舵机的典型值，非实测；"
                 "选定舵机后必须按数据手册回填重算。"),
    }



# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
# 生成交接文档（Markdown）
# --------------------------------------------------------------------------
def emit_markdown(data: Dict[str, Any],
                  attachment_rows: str = "") -> Path:
    r = data["robot"]
    j = data["joints"]
    pb = data["power_budget"]
    asm = data["assumptions"]
    crit = data["torque_criterion"]

    def tier_rows() -> str:
        order = ["XL", "L", "M", "S"]
        out = []
        for k in order:
            v = data["summary_by_tier"].get(k)
            if not v:
                continue
            names = "、".join(v["joints"])
            out.append(f"| {k} | {v['count']} | {v['max_torque_nm']:.2f} | {names} |")
        return "\n".join(out)

    def tier_example() -> str:
        """输出格式示例里按当前模型的分档实况填数，避免模板写死后漂移。"""
        out = []
        for k in ("XL", "L", "M", "S"):
            v = data["summary_by_tier"].get(k)
            if not v:
                continue
            out.append(f"### {k} 档（{v['count']} 路，最大需求 "
                       f"{v['max_torque_nm']:.2f} N·m）")
            out.append("| 型号 | 扭矩 | 速度 | 重量 | 尺寸 | 协议 | 回读 | 价格 | 备注 |")
            out.append("| ... |")
        return "\n".join(out)

    def joint_rows() -> str:
        out = []
        for t in sorted(j, key=lambda x: -x["required_torque_nm"]):
            drv = {"gravity": "重力", "inertia": "惯性", "stance": "单腿支撑",
                   "practical_floor": "工程下限"}[t["requirements_driver"]]
            lo, hi = t["limit_deg"]
            over = " ❌" if t["exceeds_continuous_rated"] else ""
            out.append(
                f"| {t['id']:02d} | `{t['joint']}` | {t['distal_mass_kg']:.3f} | "
                f"{t['max_arm_mm']:.0f} | {t['gravity_torque_nm']:.3f} | "
                f"{t['inertia_torque_nm']:.3f} | {t['stance_torque_nm']:.3f} | "
                f"**{t['required_torque_nm']:.3f}** | "
                f"{pct_str(t['margin_vs_continuous_rated'])}{over} | "
                f"{pct_str(t['margin_vs_peak'])} | "
                f"{drv} | {lo:+.0f}~{hi:+.0f} | {t['max_speed_dps']:.0f} |"
            )
        return "\n".join(out)

    def over_limit_block() -> str:
        bad = [t for t in sorted(j, key=lambda x: -x["required_torque_nm"])
               if t["exceeds_continuous_rated"]]
        if not bad:
            return "**无关节超连续额定**（主判据 0.98 N·m）。\n"
        lines = [
            f"**❌ 超连续额定的关节共 {len(bad)} 个**"
            f"（主判据 {data['torque_criterion']['continuous_rated_torque_nm']:.2f} N·m）：",
            "",
            "| 关节 | 需求 (N·m) | 占连续额定 | 占峰值 |",
            "|---|---|---|---|",
        ]
        for t in bad:
            lines.append(
                f"| `{t['joint']}` | **{t['required_torque_nm']:.3f}** | "
                f"{pct_str(t['margin_vs_continuous_rated'])} | "
                f"{pct_str(t['margin_vs_peak'])} |")
        lines += [
            "",
            "这些关节在连续工况下超载，**必须减重、降低动载（放缓步态）或换更大扭矩舵机**；",
            "峰值口径只用于判断极限瞬态，不能当作连续设计值。",
        ]
        return "\n".join(lines) + "\n"

    def cavity_rows() -> str:
        out = []
        for c in data["cavities"]:
            i = c["inner_mm"]
            out.append(f"| `{c['link']}` | {i[0]:.0f} × {i[1]:.0f} × {i[2]:.0f} | "
                       f"{c['inner_volume_cm3']} |")
        return "\n".join(out)

    md = f"""# A.T.R.I. 设计交接包 —— 硬件选型需求

> **给谁看**：负责补充"工业部件世界知识"的 agent（部件库 builder）
> **要什么**：根据本文件的需求，产出**真实可采购部件**的候选清单与集成说明
> **不要什么**：不需要再改几何外形，几何由本项目自己维护
> **自动生成**：本文件由 `design/gen_handoff.py` 生成，请勿手改；
> 数值全部来自 `design/robot_model.json`，改模型后重跑即可同步。

---

## 一、先说清楚：这份几何是"占位"，不是可制造设计

这是最重要的一节，直接决定你能帮上什么忙。

**A.T.R.I. 当前是一个 22 自由度运动学模型**，几何形状全部是**基元占位**：
长方体、圆柱、球、胶囊。它表达的是**包络尺寸与连接关系**，
不是可加工零件。

**它没有、也不打算有（这正是需要你补的）：**

| 缺失项 | 说明 |
|---|---|
| 舵机支架 / 舵盘 | 每个关节都需要真实安装接口，现在只有包络 |
| 轴承与轴承座 | 转动副的支撑结构 |
| 螺钉柱、螺纹孔、沉孔 | 全部未建模 |
| 走线槽与过线孔 | 线束路径未设计 |
| 拔模斜度、圆角、打印方向 | 工艺特征全无 |
| 电池 / 电路板的安装位置与固定方式 | 只算了"可用空腔"，没有安装结构 |
| 外壳分件、卡扣、装配顺序 | 没有 |

**所以：不要试图为当前几何画零件图。** 你要做的是——
**根据下面的需求，从真实工业部件里选出能用的东西，并说明怎么装。**

---

## 二、可信赖的硬数据（这些是真的）

| 项目 | 数值 | 来源 |
|---|---|---|
| 自由度 | **{r['dof']}**（腿 10 + 臂 8 + 躯干 2 + 头 2） | 与固件 `config.py` 同源 |
| 包络尺寸 | **{r['envelope_mm']['height_mm']:.0f} × {r['envelope_mm']['width_mm']:.0f} × {r['envelope_mm']['depth_mm']:.0f}** mm（高×宽×厚） | 由关节链几何推导 |
| 整机质量 | **{r['mass_kg']}** kg（结构 {r['mass_breakdown_kg']['structure_g']:.0f} + 舵机 {r['mass_breakdown_kg']['servos_g']:.0f} + 电子件与电池 {r['mass_breakdown_kg']['electronics_g']:.0f} + 线束紧固件 {r['mass_breakdown_kg']['harness_fasteners_g']:.0f} g） | 结构为 CAD 实装实算，其余为部件清单 |
| 赛道要求 | {r['competition_class']} | 中国国际大学生创新大赛陕西赛区 |
| 运动学模型 | `atri.urdf`（23 link / 22 joint，含惯量） | 可直接加载 PyBullet / Webots |

**关节定义**：名称、编号、轴向、角度限位与固件完全一致，
不是随手编的——有单元测试逐项校验同源。

---

## 三、硬件选型需求（你的主要输入）

### 3.1 关节力矩需求

**计算方法**（可复现）：

三种工况取包络（用哪个大就用哪个）：

```
① 重力保持   τ_g = Σ mᵢ·g·rᵢ · {asm['safety_factor_static']}
             rᵢ = 下游质心到关节轴线的垂直距离
② 惯性       τ_i = (Σ mᵢ·rᵢ²) · α · {asm['safety_factor_static']}
             α = {asm['angular_accel_rad_s2']} rad/s²（摆腿/摆臂角加速度）
③ 单腿支撑   τ_s = (整机质量 − 下游腿段质量) · g · {asm['gait_cop_offset_mm']:.0f}mm · {asm['stance_dynamic_factor']}
             ⚠ 腿部关节的真正选型依据：支撑期要撑起全身重量
安全下限     {asm['min_practical_torque_nm']} N·m（低于此值齿轮刚度与回程间隙不可接受）
```

**"依据"列**告诉你每个数是怎么来的：竖直轴关节（髋 yaw、头 yaw/pitch）
重力力臂≈0，实际是按惯性或工程下限定的。

**扭矩判据用两套口径，主判据是官方连续额定：**

| 口径 | 值 | 含义 |
|---|---|---|
| **连续额定（主判据）** | **{crit['continuous_rated_torque_nm']:.2f} N·m** | 官方额定负载 10 kg·cm @12V（额定电流 900 mA），**可持续工况**；⚠️ 12V 变体推断值，待实测（7.4V 版额定仅 0.49 N·m） |
| 峰值参考 | {crit['peak_torque_nm']:.2f} N·m | 堵转 × 50%，只能短时峰值，**比官方额定乐观 50%** |
| 堵转 | {crit['stall_torque_nm']:.2f} N·m | 30 kg·cm，仅极限瞬态 |

| ID | 关节 | 下游质量(kg) | 力臂(mm) | 重力矩 | 惯性矩 | 单腿支撑 | **需求(N·m)** | 占连续额定 | 占峰值 | 依据 | 限位(°) | 最大速度(°/s) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
{joint_rows()}

{over_limit_block()}
**按档位汇总**（选型时按档位找候选即可）：

| 档位 | 路数 | 最大需求(N·m) | 关节 |
|---|---|---|---|
{tier_rows()}

### 3.2 功率预算

| 项目 | 数值 |
|---|---|
| 舵机总线电压 | {pb['servo_bus_voltage_v']} V（3S） |
| 舵机平均电流 | {pb['avg_servo_current_a']} A |
| 逻辑（{pb['logic_rail_v']:.0f}V 轨） | {pb['logic_current_at_5v_a']} A |
| 折算到电池侧合计 | **{pb['total_avg_current_at_pack_a']} A** |
| 30 min 任务消耗 | {pb['consumed_ah']} Ah / {pb['consumed_wh']} Wh |
| 按 {pb['usable_fraction']*100:.0f}% 可用容量 | 需标称 **{pb['required_nameplate_ah']} Ah / {pb['required_nameplate_wh']} Wh** |
| 整包预估质量 | **{pb['estimated_battery_mass_kg']} kg** |

> ⚠️ **容量敏感性（功率预算反推）**：{pb['sensitivity_note']}

### 3.3 可用安装空腔（内部净空，已扣 2.5mm 壁厚）

| 部位 | 内腔 (mm) | 容积 (cm³) |
|---|---|---|
{cavity_rows()}

> 躯干是主控板 + 电池仓；骨盆是电池或配重候选位；头部装相机与麦克风。

### 3.4 接口与平台需求

| 类别 | 需求 | 说明 |
|---|---|---|
| 舵机总线 | **{data['interface_requirements']['servo_bus']['count']} 路 TTL 半双工串行总线** | 单线级联；需支持绝对位置与温度/负载回读 |
| 主控（大脑） | 4 核 ARM64、≥2GB RAM、≥2 路 USB | 跑离线视觉 + 离线语音 + 状态机；**必须全离线** |
| 下位机（小脑） | Cortex-M3/M4+、≥2 路 UART、≥2 路高级定时器、I²C/SPI | 步态解算 + IMU 闭环 + 舵机群控 |
| IMU | 6 轴，I²C 或 SPI | 姿态闭环 |
| 相机 | USB UVC **免驱**广角，≥70° FOV | Linux 直接识别，无需驱动 |
| 麦克风 | USB 免驱 | 离线关键词识别 |
| 扬声器 | 3W + 功放 | TTS 播报 |
| 电源 | 3S 锂聚合物 + 独立 BEC + XT60 | 舵机与逻辑电源隔离 |

---

## 四、请你产出什么（任务清单）

按优先级排列。每条都要求：**具体型号 + 关键参数 + 兼容性风险 + 大致价格**。

### P0 舵机选型（最关键）

1. 按 **S / M 两个档位**各给出 **3 个以上**可采购候选（国内易买）：
   - 型号、额定/堵转扭矩、速度、重量、外形尺寸、**总线协议**、回读能力、价格
   - 明确是否支持 **TTL 半双工级联**
2. 给出**舵盘/支架**方案：现成件还是需自制？安装孔位标准？同轴度要求？
3. 指出**混用不同档位舵机的注意事项**（同总线不同型号的 ID 分配、波特率、供电差异）

### P0 电控平台

4. **主控板候选**：能跑离线视觉+语音的（树莓派 4B 级别），含供电与散热要求
5. **下位机候选**：STM32 具体型号，以及**与主控的通信协议建议**（UART/CDC/USB）
6. **总线舵机驱动板**：USB-TTL 或 串口转总线 的具体型号
7. **主控 ↔ 下位机 ↔ 舵机总线**的完整连接拓扑图（文字描述即可）

### P1 感知与交互

8. 相机候选（UVC 免驱广角，尺寸要能塞进头部 {data['cavities'][2]['inner_mm'][0]:.0f}×{data['cavities'][2]['inner_mm'][1]:.0f}×{data['cavities'][2]['inner_mm'][2]:.0f} mm）
9. 麦克风 / 扬声器候选（含功放模块）
10. IMU 候选（6 轴，I²C/SPI）

### P1 电源与线束

11. 电池具体型号（3S，≥{pb['required_nameplate_ah']} Ah，含接头）
12. **BEC / 降压模块**选型（舵机侧大电流 + 逻辑侧 5V，需隔离）
13. 线规建议（舵机总线电流 {pb['avg_servo_current_a']} A 平均，峰值更高）
14. 连接器标准（XT60 / JST / 杜邦 / GH1.25 的使用场景）

### P2 集成与兼容性（"坑"清单）

15. 每个推荐型号的**已知兼容性问题**：
    - 舵机总线协议差异（飞特 / 幻尔 / 创客工场 互不兼容？）
    - 树莓派 USB 供电不足导致舵机驱动板掉线
    - 舵机堵转电流拉垮主控（共地/隔离问题）
    - 免驱相机在 Linux 下的实际兼容情况
16. **大创赛相关**：陕西省赛 / 国赛对硬件有无特殊要求或推荐清单

---

## 五、输出格式要求

请按以下结构输出，便于直接并入本项目文档：

```markdown
## 舵机选型
{tier_example()}
## 电控平台
...
## 兼容性与坑
...
```

**要求**：
- 所有参数必须是**真实可查**的，标注来源（官网/立创/淘宝链接均可）
- 不确定的写"待确认"，**不要编造参数**
- 价格给量级即可（如"约 90–120 元"）

---

## 六、附件清单

| 文件 | 内容 | 用途 |
|---|---|---|
| `hardware_requirements.json` | 本文档的机器可读版，含每个关节的力矩推导明细 | 程序化消费 |
{attachment_rows}| `fit_report.md` | 元件配合与质量校验结果 | 上一轮白皮书的复核结论 |

---

## 七、后续轮次

| 文件 | 用途 |
|---|---|
| `下一轮-给Gemini的提示词.md` | 第 2 轮：索取机械接口数据（当前阻塞项） |
| `下一轮-本仓库执行提示词.md` | 第 2 轮：CAD 化改造与零件建模 |

---

## 八、边界声明

- 本文件中"**设计值**"均为**基于质量分布与力臂的计算/估算**，
  **不是实测数据**，也未做刚体动力学仿真。
- 舵机外形取自模型 `servo_defaults`（45.2×24.7×35.0 mm，厂商标称值）；
  电气参数为厂商参数表值（DFRobot SER0070 + 飞特规格书），均未实物实测。
- 几何为占位基元，**不可用于加工**。
"""
    out = OUT_DIR / "设计交接包-硬件选型需求.md"
    out.write_text(md, encoding="utf-8")
    return out


# --------------------------------------------------------------------------
# 附件打包：把主文档需要的附件集中到 handoff/，文件名用 ASCII 便于上传
# --------------------------------------------------------------------------
# (源文件去掉扩展名, 目标文件名主干, 说明)
# 优先用 PNG（本机可导出时），否则回退到**已入库的 SVG** —— 否则在全新 clone / CI 上
# 附件永远缺失（PNG 被 .gitignore 排除），测试 test_all_declared_attachments_exist 必红。
ATTACHMENTS = [
    ("design/atri.urdf", "atri.urdf", "23 link / 22 joint 完整运动学 + 惯量"),
    ("design/renders/01_等轴测外观", "render_iso", "等轴测外观渲染"),
    ("design/renders/02_正视外观", "render_front", "正视外观渲染"),
    ("design/renders/04_关节配色图", "render_groups", "部位配色渲染"),
    ("design/drawings/01_关节编号图", "render_joints", "22 关节编号图（工程图）"),
]


def stage_attachments() -> List[Dict[str, str]]:
    """把附件复制/导出到 handoff/，返回 [{name, note}]（name 为实际落盘名）。

    分辨顺序：源文件本身（atri.urdf）→ 同名 .png（本机导出）→ 同名 .svg（已入库，CI 可用）。
    """
    import shutil
    staged: List[Dict[str, str]] = []
    repo = HERE.parent
    for src_rel, stem, note in ATTACHMENTS:
        src = repo / src_rel
        if src.suffix == "":
            # **确定性优先**：SVG 是入库文件，PNG 被 .gitignore 排除。
            # 以前"有 PNG 就用 PNG"会让交接包内容随本机状态漂移
            # （本机有 PNG → 声明 .png；CI 无 PNG → 目录里只有 .svg），
            # 于是全新 clone / CI 上附件校验必红。现在固定优先 SVG。
            for ext in (".svg", ".png"):
                cand = src.with_suffix(ext)
                if cand.exists():
                    src = cand
                    break
            else:
                src = src.with_suffix(".svg")
        if src.exists() and src.is_file():
            dst_name = stem if src.suffix == ".urdf" else stem + src.suffix
            shutil.copy2(src, OUT_DIR / dst_name)
            staged.append({"name": dst_name, "note": note})
        else:
            print(f"  [附件缺失] {src_rel}（跳过）")
    return staged


def main() -> int:
    model = gen_urdf.load_model()

    torques = [joint_torque(model, j)
               for j in sorted(model["joints"], key=lambda x: x["id"])]

    declared_mass = sum(l["mass_kg"] for l in model["links"])
    total_mass = (declared_mass + ASSUMPTIONS["cable_mass_kg"]
                  + ASSUMPTIONS["fastener_mass_kg"])

    ts = model["servo_defaults"]
    sv = ts["size_mm"]
    crit = torque_criteria(model)
    over_continuous = [t["joint"] for t in torques
                       if t["exceeds_continuous_rated"]]
    pb = power_budget(model, torques)

    out: Dict[str, Any] = {
        "schema_version": "1.0",
        "generated_by": "design/gen_handoff.py",
        "purpose": (
            "把几何设计翻译成**硬件选型需求**，供部件知识库/下游 agent 使用。"
            "本文件不含外观信息，只含约束与接口。"
        ),
        "robot": {
            "name": model["name"],
            "dof": len(model["joints"]),
            "envelope_mm": model["overall"],
            "mass_kg": round(total_mass, 3),
            "mass_breakdown_kg": {
                "links_total": round(declared_mass, 3),
                "cables": ASSUMPTIONS["cable_mass_kg"],
                "fasteners": ASSUMPTIONS["fastener_mass_kg"],
                # 分档来自 robot_model.json 的 mass_budget（结构为 CAD 实装实算）
                "structure_g": model["mass_budget"]["structure_g"],
                "servos_g": model["mass_budget"]["servos_g"],
                "electronics_g": model["mass_budget"]["electronics_g"],
                "harness_fasteners_g": model["mass_budget"]["harness_fasteners_g"],
            },
            "competition_class": "小人形组（高≤600 宽≤300 厚≤300 mm，≥18 DOF，≥7.4V）",
        },
        "assumptions": ASSUMPTIONS,
        "joints": torques,
        "torque_criterion": {
            "primary": "continuous_rated",
            "description": ("主判据 = 官方连续额定 0.98 N·m（额定负载 10 kg·cm @12V，"
                            "对应额定电流 900 mA）；peak_torque_nm 1.47 只作短时峰值参考，"
                            "比官方额定乐观 50%。0.98 属 12V 变体推断值，待实测"
                            "（仓库唯一的 STS3215 官方规格书为 7.4V 版，额定 0.49 N·m；"
                            "按 0.49 N·m 踝关节约 333%）。"),
            **torque_criteria(model),
            "joints_exceeding_continuous": [
                t["joint"] for t in torques if t["exceeds_continuous_rated"]],
            "joints_exceeding_peak": [
                t["joint"] for t in torques if t["exceeds_peak"]],
            "source": "design/handoff/STS3215-官方规格书核验.md",
        },
        "summary_by_tier": {},
        "cavities": [
            cavity(model, "torso_upper"),
            cavity(model, "pelvis"),
            cavity(model, "head"),
        ],
        "power_budget": pb,
        "interface_requirements": {
            "servo_bus": {
                "count": len(model["joints"]),
                "protocol": "TTL 半双工串行总线（单线级联）",
                "why": ("单线级联 22 路、支持绝对位置与温度/负载回读、"
                        "与现有 ServoBus 抽象天然对应"),
                "alternatives": ["PWM + PCA9685 驱动板（更便宜，但无回读、线束多）"],
            },
            "compute": {
                "role": "视觉感知 + 离线语音 + 任务状态机",
                "min_requirements": {
                    "cpu": "4 核 ARM64 及以上",
                    "ram_gb": 2,
                    "usb": "≥2 路 USB 2.0/3.0（相机 + 总线舵机）",
                    "network": "不需要（必须能完全离线运行）",
                },
                "reference_platforms": ["Raspberry Pi 4B", "Orange Pi 5",
                                        "Radxa Rock 5B"],
            },
            "mcu": {
                "role": "步态解算 + IMU 闭环 + 舵机群控",
                "min_requirements": {
                    "core": "Cortex-M3/M4 及以上",
                    "uart": "≥2 路（一路接总线舵机，一路接上位机）",
                    "timer": "≥2 路高级定时器",
                    "i2c_spi": "接 IMU",
                },
                "reference_platforms": ["STM32F103", "STM32F405",
                                        "ESP32-S3（若需无线调试）"],
            },
            "sensors": {
                "imu": {"type": "6 轴（加速度+陀螺）", "bus": "I²C 或 SPI"},
                "camera": {"type": "USB UVC 免驱广角", "fov_deg": 70,
                           "resolution": "640×480 即可"},
                "mic": {"type": "USB 免驱麦克风", "purpose": "离线关键词识别"},
                "speaker": {"type": "3W 喇叭 + 功放", "purpose": "TTS 播报"},
            },
            "power": {
                # 容量由 power_budget() 派生，避免与功率预算（≥4.53 Ah）两套口径
                "battery": (f"3S 11.1V 锂聚合物，≥"
                            f"{pb['required_nameplate_ah'] * 1000:.0f} mAh"
                            f"（{pb['required_nameplate_ah']} Ah，"
                            "按 30 min 任务由 power_budget 派生）"),
                "regulation": "独立 BEC 给舵机供电，与逻辑电源隔离",
                "connector": "XT60 主接口",
            },
        },
        "what_is_placeholder": [
            "所有 link 的几何是**基元占位**（长方体/圆柱/球/胶囊），"
            "只表达包络与连接关系，不是可加工零件。",
            f"舵机外形（{sv[0]:.1f}×{sv[1]:.1f}×{sv[2]:.1f} mm）取自模型 "
            "servo_defaults，与全机其它文档一致；本身仍为厂商标称值，非实测。",
            "未建模：舵机支架、轴承、走线槽、螺钉柱、拔模与圆角。",
            "未建模：电池与电路板的实际安装位置与固定方式。",
            "力矩需求为**静力估算**，未做动力学仿真。",
        ],
        "what_is_real": [
            "关节数量、编号、名称、轴向、角度限位 —— 与固件 config.py 同源。",
            "运动学树（父子关系与关节原点）—— 可直接加载 URDF 验证。",
            "整机包络尺寸与质量预算 —— 由几何推导，与声明值一致。",
            "力矩需求的**推导方法**与量级 —— 基于质量分布与力臂计算。",
            f"扭矩判据：主判据为官方连续额定 "
            f"{crit['continuous_rated_torque_nm']:.2f} N·m，峰值参考 "
            f"{crit['peak_torque_nm']:.2f} N·m（堵转 × 50%）；"
            f"{len(over_continuous)} 个关节超连续额定，"
            "已在 torque_criterion 与本文档显式列出。",
        ],
    }

    # 分档汇总
    tier_acc: Dict[str, Dict[str, Any]] = {}
    for t in torques:
        k = t["torque_tier"]
        acc = tier_acc.setdefault(k, {"count": 0, "max_torque_nm": 0.0,
                                      "joints": []})
        acc["count"] += 1
        acc["max_torque_nm"] = max(acc["max_torque_nm"],
                                   t["required_torque_nm"])
        acc["joints"].append(t["joint"])
    for k, v in tier_acc.items():
        v["max_torque_nm"] = round(v["max_torque_nm"], 3)
    out["summary_by_tier"] = tier_acc

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / "hardware_requirements.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")

    # 控制台摘要
    print("=" * 70)
    print("硬件选型需求（由设计模型推导）")
    print("=" * 70)
    print(f"整机质量 {total_mass:.3f} kg   DOF {len(model['joints'])}")
    print(f"包络 {model['overall']['height_mm']:.0f} × "
          f"{model['overall']['width_mm']:.0f} × "
          f"{model['overall']['depth_mm']:.0f} mm")
    print()
    print("关节力矩需求（重力保持 × 安全系数 1.8）:")
    print(f"  {'ID':>3} {'关节':<22} {'重力矩':>7} {'惯性矩':>7} {'支撑':>7} "
          f"{'需求':>7} {'依据':<14} {'档位':>4}")
    for t in sorted(torques, key=lambda x: -x["required_torque_nm"]):
        print(f"  {t['id']:>3} {t['joint']:<22} "
              f"{t['gravity_torque_nm']:>7.3f} {t['inertia_torque_nm']:>7.3f} "
              f"{t['stance_torque_nm']:>7.3f} "
              f"{t['required_torque_nm']:>7.3f} {t['requirements_driver']:<14} "
              f"{t['torque_tier']:>4}")
    print()
    print("分档汇总:")
    for k in ("S", "M", "L", "XL"):
        if k in tier_acc:
            v = tier_acc[k]
            print(f"  {k:<3} {v['count']:>2} 路  最大 {v['max_torque_nm']:.2f} N·m")
    print()
    print(f"扭矩判据: 连续额定 {crit['continuous_rated_torque_nm']:.2f} N·m（主判据）"
          f" / 峰值 {crit['peak_torque_nm']:.2f} N·m（堵转×50%）")
    if over_continuous:
        print(f"  [超连续额定] {len(over_continuous)} 个关节: "
              + "、".join(over_continuous))
    print()
    pb = out["power_budget"]
    print(f"功率预算: 舵机平均 {pb['avg_servo_current_a']} A + "
          f"逻辑 {pb['logic_current_at_pack_a']} A = "
          f"{pb['total_avg_current_at_pack_a']} A @ {pb['servo_bus_voltage_v']} V")
    print(f"          {pb['mission_min']} min 任务消耗 "
          f"{pb['consumed_ah']} Ah / {pb['consumed_wh']} Wh；"
          f"按 80% 可用需标称 {pb['required_nameplate_ah']} Ah / "
          f"{pb['required_nameplate_wh']} Wh")
    print(f"          整包质量约 {pb['estimated_battery_mass_kg']} kg")
    print()
    print("可用安装空腔:")
    for c in out["cavities"]:
        print(f"  {c['link']:<14} 内腔 "
              f"{c['inner_mm'][0]:.0f}×{c['inner_mm'][1]:.0f}×"
              f"{c['inner_mm'][2]:.0f} mm  ≈ {c['inner_volume_cm3']} cm³")
    print()
    print(f"已写出: {path}")
    print("打包附件:")
    staged = stage_attachments()
    rows = "\n".join(f"| `{a['name']}` | {a['note']} | |" for a in staged)
    md_path = emit_markdown(out, attachment_rows=rows + "\n")
    print(f"已写出: {md_path}  ({md_path.stat().st_size} bytes)")
    for a in staged:
        size = (OUT_DIR / a["name"]).stat().st_size
        print(f"  ✓ {a['name']}  ({size} bytes)")
    print(f"  共 {len(staged)}/{len(ATTACHMENTS)} 个附件就绪")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
