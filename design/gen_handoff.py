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
        "**静力计算安全系数**（不是动力学系数）：乘在**静力算出的保持力矩**上的一次总裕度，"
        "用来覆盖 ①步态加减速的动态载荷 ②落脚冲击 ③舵机个体差异与电压跌落。"
        "名字里的 static 指『它作用在静力计算值上』，不代表被覆盖的载荷是静态的；"
        "工业做法通常 1.5–2.0，取中值偏高。⚠️ 它 ≠ 动载系数，别与 "
        "stance_dynamic_factor（单腿支撑工况的 2.0）混用或相乘。"
    ),
    "gravity_torque_calibers": ["zero_pose_static", "worst_case_within_limits"],
    "note_gravity_torque_calibers": (
        "重力矩的**两种口径**，产物里分列、不互相替代："
        "(a) `zero_pose_static` = 当前 URDF 零位（站立不动、各关节 0°）下的真实重力矩，"
        "读作『站着不动时关节实际要扛多少』；"
        "(b) `worst_case_within_limits` = 在该关节限位范围内、连同其祖先与后代关节一起搜索出的"
        "**最大重力矩**（方法见 worst_case_search），读作『这个关节在自身运动范围内可能遇到的最坏静力』，"
        "是选型用的保守上界。两者相差可达数倍（例如躯干俯仰、髋/膝），**引用时必须写明用的是哪一种**。"
    ),
    "worst_case_search": "coordinate_ascent_with_exact_per_axis_extremum",
    "note_worst_case_search": (
        "最不利姿态的搜索方法：在『该关节 + 其祖先关节 + 其后代关节』这组相关自由度上做坐标上升，"
        "每个自由度按**解析极值**取值——固定其余关节、只转第 k 个关节时，τ_k(θ) 恒为 "
        "C + A·cosθ + B·sinθ（刚体绕定轴转动、重力方向固定），用 θ = 0/π/2/π 三点定出系数后"
        "在限位区间上闭式取 |τ| 最大；从零位、全下限、全上限三个起点各收敛一次取最大。"
        "只搜索运动学限位，不含地面接触/平衡约束，故是**上界**（真实步态里未必能摆到该姿态）。"
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
                           "**竖直轴关节（髋 yaw、头 yaw）的重力力矩恒为 0**"
                           "（重力与该轴平行），必须靠惯性项才能给出有意义的选型下限。"
                           "惯性项用的半径是 I = Σ m·r⊥²（含沿轴分量的垂直距离），"
                           "与重力力臂不是同一个量。"),
    "gait_cop_offset_mm": 25.0,
    "note_gait_cop_offset_mm": ("行走时的地面反力作用点（CoP）相对关节轴线的最大水平偏移。"
                      "站立时 CoP 在足心附近，行走/加减速时会前后移动；"
                      "取 25mm 作为中等步幅下的估算值。"),
    "stance_dynamic_factor": 2.0,
    "note_stance_dynamic_factor": ("单腿支撑期的动载系数：落脚冲击、重心起伏、"
                            "加减速惯性都会放大关节力矩。静力分析无法覆盖，"
                            "按 2.0 估算。⚠️ 这是**单独一项工况**的系数"
                            "（与 safety_factor_static 各自独立、不叠加），"
                            "作用在『全身重量 × CoP 偏移』的静力项上。"),
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
    """返回该关节以下（含）的所有 link 名称。

    ⚠️ 力矩模型**不再用它**（2026-09-12 起改用 `_kinematics()["subtree"]`，
    那里同时给出相关自由度与索引）；本函数作为通用工具保留，供外部脚本复用。
    """
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
    """某个下游 link 的质心相对该关节零位坐标系的位移（零姿态，单位 mm）。

    ⚠️ **已不参与力矩计算**（2026-09-12 起），仅作参考保留：
    它只累加各关节 origin 的平移、忽略 origin 的 rpy 与关节转角，因此
    ① 只能用于零姿态，② 无法支持"限位内最不利姿态"的搜索。
    现行管线走 `_kinematics()` + `_joint_state()` 的完整正解。
    """
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


# --------------------------------------------------------------------------
# 力臂的两种口径（2026-09-12 修正；此前两者被混为一谈）
# --------------------------------------------------------------------------
# 绕关节轴的重力力矩只由**水平面内、垂直于该轴**的质心偏移决定：
#
#     τ = (r × m·g·ẑ) · â = m·g·(r_x·a_y − r_y·a_x)        （â 为单位轴向量）
#
#   * 水平轴（a_z = 0，本模型 19/22 个关节）：力臂 = 水平偏移里垂直于轴的分量；
#     质心正对轴线的上方/下方时力臂**为 0**（这是对的物理，不是退化）。
#   * 竖直轴（a_x = a_y = 0）：括号恒为 0 —— 重力与该轴平行，绕它不产生力矩。
#     「质心到轴线的水平距离」**不是**竖直轴的重力力臂（那是水平外力，比如地面
#     反力的力臂）；只有转动惯量 I = Σ m·r⊥² 才用那个几何半径。
#
# 因此下面两个函数是**两个不同的物理量**，任何一处都不得互相顶替：
#     perpendicular_arm()   → r⊥ = 质心到轴线的垂直距离（含沿轴分量），供惯性项用
#     gravity_moment_arm()  → 重力力臂（水平面内垂直于轴的分量）
def perpendicular_arm(offset_mm: Tuple[float, float, float],
                      axis: List[float]) -> float:
    """质心到关节轴线的**垂直距离** r⊥（mm）—— 纯几何量，供惯性项 I = Σ m·r⊥² 用。

    ⚠️ **这不是重力力臂**：r⊥ 含沿轴方向的分量，而重力绕该轴的力矩与沿轴分量无关。
    重力力臂见 gravity_moment_arm()。历史教训：把本函数直接当重力力臂用，会让
    绕水平轴的关节把竖直偏移也算进力臂（躯干横滚因此高估 2 倍以上）。
    """
    p = offset_mm
    n = math.sqrt(sum(a * a for a in axis)) or 1.0
    a = [v / n for v in axis]
    along = sum(p[i] * a[i] for i in range(3))
    perp = [p[i] - along * a[i] for i in range(3)]
    return math.sqrt(sum(v * v for v in perp))


def gravity_moment_arm(offset_mm: Tuple[float, float, float],
                       axis: List[float]) -> float:
    """重力力矩的**有效力臂**（mm）：|r_x·a_y − r_y·a_x| / |â|。

    即质心偏移在水平面内、垂直于关节轴的分量。轴必须是该关节在
    **世界系**下的方向（由正运动学求出，不硬编码任何方向）。

    竖直轴（a_x = a_y = 0）得 0：重力与该轴平行，绕它不产生力矩——
    这不是"漏算"，是物理事实。
    """
    p = offset_mm
    n = math.sqrt(sum(a * a for a in axis)) or 1.0
    ax, ay = axis[0] / n, axis[1] / n
    return abs(p[0] * ay - p[1] * ax)


# --------------------------------------------------------------------------
# 刚体运动学（正解）——力臂与最不利姿态都必须用**世界位姿**，不能拍方向
# --------------------------------------------------------------------------
_IDENT3 = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
_KINEMATICS_CACHE: Dict[Any, Dict[str, Any]] = {}
_WORST_CASE_CACHE: Dict[Any, Dict[str, Any]] = {}


def _joint_rpy(joint: Dict[str, Any]) -> Tuple[float, float, float]:
    """关节 origin 的 rpy（弧度）。现行 robot_model.json 不含该字段（等价全 0），
    模型若补上 origin_rpy_rad / origin_rpy_deg 也能直接生效。"""
    r = joint.get("origin_rpy_rad")
    if r is None:
        d = joint.get("origin_rpy_deg")
        r = [math.radians(float(v)) for v in d] if d else (0.0, 0.0, 0.0)
    return (float(r[0]), float(r[1]), float(r[2]))


def _rpy_rotation(rpy: Tuple[float, float, float]):
    """URDF 的 R = Rz(yaw)·Ry(pitch)·Rx(roll)。返回 3x3 元组。"""
    cr, sr = math.cos(rpy[0]), math.sin(rpy[0])
    cp, sp = math.cos(rpy[1]), math.sin(rpy[1])
    cy, sy = math.cos(rpy[2]), math.sin(rpy[2])
    return ((cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr),
            (sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr),
            (-sp, cp * sr, cp * cr))


def _axis_rotation(axis: Tuple[float, float, float], ang: float):
    """罗德里格斯公式；轴对齐的常见情形走快路径（本模型 22 个关节全是轴对齐）。"""
    x, y, z = axis
    c, s = math.cos(ang), math.sin(ang)
    if x == 1.0 and y == 0.0 and z == 0.0:
        return ((1.0, 0.0, 0.0), (0.0, c, -s), (0.0, s, c))
    if x == 0.0 and y == 1.0 and z == 0.0:
        return ((c, 0.0, s), (0.0, 1.0, 0.0), (-s, 0.0, c))
    if x == 0.0 and y == 0.0 and z == 1.0:
        return ((c, -s, 0.0), (s, c, 0.0), (0.0, 0.0, 1.0))
    C = 1.0 - c
    return ((c + x * x * C, x * y * C - z * s, x * z * C + y * s),
            (y * x * C + z * s, c + y * y * C, y * z * C - x * s),
            (z * x * C - y * s, z * y * C + x * s, c + z * z * C))


def _model_fingerprint(model: Dict[str, Any]) -> Tuple[Any, ...]:
    """模型内容指纹（缓存键）。用它而不是 id(model)：id 会被回收重用，
    会让『换了个模型对象但内容不同』读到脏缓存。"""
    return (tuple((j["name"], tuple(j["axis"]), tuple(j["limit_deg"]),
                   tuple(j["origin_xyz_mm"]),
                   tuple(_joint_rpy(j))) for j in model["joints"]),
            tuple((l["name"], float(l["mass_kg"]),
                   tuple(geometry.geometry_origin(l["geometry"])))
                  for l in model["links"]))


def _kinematics(model: Dict[str, Any]) -> Dict[str, Any]:
    """把模型整理成正解需要的表（按内容指纹缓存）。"""
    key = _model_fingerprint(model)
    kin = _KINEMATICS_CACHE.get(key)
    if kin is not None:
        return kin

    joints: List[Dict[str, Any]] = []
    for j in model["joints"]:
        ax = [float(v) for v in j["axis"]]
        n = math.sqrt(sum(v * v for v in ax)) or 1.0
        lim = j.get("limit_deg") or [-180.0, 180.0]
        rpy = _joint_rpy(j)
        joints.append({
            "name": j["name"], "parent": j["parent"], "child": j["child"],
            "type": j.get("type", "revolute"),
            "axis": (ax[0] / n, ax[1] / n, ax[2] / n),
            "xyz": tuple(float(v) for v in j["origin_xyz_mm"]),
            "rpy": _rpy_rotation(rpy),
            "rpy_is_identity": rpy == (0.0, 0.0, 0.0),
            "lo": math.radians(float(lim[0])), "hi": math.radians(float(lim[1])),
        })
    by_child = {j["child"]: i for i, j in enumerate(joints)}

    children: Dict[str, List[int]] = {}
    for i, j in enumerate(joints):
        children.setdefault(j["parent"], []).append(i)

    chain_cache: Dict[int, List[int]] = {}

    def chain_idx(i: int) -> List[int]:
        if i in chain_cache:
            return chain_cache[i]
        p = joints[i]["parent"]
        out = (chain_idx(by_child[p]) if p in by_child else []) + [i]
        chain_cache[i] = out
        return out

    subtree: Dict[int, List[str]] = {}
    for i, j in enumerate(joints):
        acc: List[str] = []

        def walk(link: str) -> None:
            acc.append(link)
            for k in children.get(link, []):
                walk(joints[k]["child"])

        walk(j["child"])
        subtree[i] = acc

    rel: Dict[int, List[int]] = {}
    for i in range(len(joints)):
        r = set(chain_idx(i))                      # 祖先 + 自己
        for link in subtree[i]:
            r.update(children.get(link, []))       # 后代关节
        rel[i] = sorted(r)

    kin = {
        "key": key,
        "joints": joints,
        "index": {j["name"]: i for i, j in enumerate(joints)},
        "children": children,
        "chain": {i: chain_idx(i) for i in range(len(joints))},
        "subtree": subtree,
        "rel": rel,
        "mass": {l["name"]: float(l["mass_kg"]) for l in model["links"]},
        "com": {l["name"]: tuple(geometry.geometry_origin(l["geometry"]))
                for l in model["links"]},
    }
    _KINEMATICS_CACHE[key] = kin
    return kin


def _mul3(a, b):
    """3x3 矩阵乘法（显式写开：这是搜索最内层的热点，比生成器表达式快数倍）。"""
    return ((a[0][0] * b[0][0] + a[0][1] * b[1][0] + a[0][2] * b[2][0],
             a[0][0] * b[0][1] + a[0][1] * b[1][1] + a[0][2] * b[2][1],
             a[0][0] * b[0][2] + a[0][1] * b[1][2] + a[0][2] * b[2][2]),
            (a[1][0] * b[0][0] + a[1][1] * b[1][0] + a[1][2] * b[2][0],
             a[1][0] * b[0][1] + a[1][1] * b[1][1] + a[1][2] * b[2][1],
             a[1][0] * b[0][2] + a[1][1] * b[1][2] + a[1][2] * b[2][2]),
            (a[2][0] * b[0][0] + a[2][1] * b[1][0] + a[2][2] * b[2][0],
             a[2][0] * b[0][1] + a[2][1] * b[1][1] + a[2][2] * b[2][1],
             a[2][0] * b[0][2] + a[2][1] * b[1][2] + a[2][2] * b[2][2]))


def _joint_state(kin: Dict[str, Any], ji: int, angles: Dict[str, float]):
    """该关节的世界位姿 + 其下游各 link 的质心世界坐标（mm）。

    只走『该关节的祖先链 + 自己 + 子树』：其余分支（兄弟腿、另一条手臂）既不在
    它的下游、也不改变它的轴，对它的重力力矩**没有影响**，故不遍历。
    """
    J = kin["joints"]
    R = _IDENT3
    t = (0.0, 0.0, 0.0)
    origin = axis_w = None
    for k in kin["chain"][ji]:
        jk = J[k]
        x, y, z = jk["xyz"]
        Rj = R if jk["rpy_is_identity"] else _mul3(R, jk["rpy"])
        tj = (t[0] + Rj[0][0] * x + Rj[0][1] * y + Rj[0][2] * z,
              t[1] + Rj[1][0] * x + Rj[1][1] * y + Rj[1][2] * z,
              t[2] + Rj[2][0] * x + Rj[2][1] * y + Rj[2][2] * z)
        if k == ji:
            origin = tj
            ax, ay, az = jk["axis"]
            axis_w = (Rj[0][0] * ax + Rj[0][1] * ay + Rj[0][2] * az,
                      Rj[1][0] * ax + Rj[1][1] * ay + Rj[1][2] * az,
                      Rj[2][0] * ax + Rj[2][1] * ay + Rj[2][2] * az)
        R = _mul3(Rj, _axis_rotation(jk["axis"], angles.get(jk["name"], 0.0)))
        t = tj

    coms: Dict[str, Tuple[float, float, float]] = {}
    stack = [(J[ji]["child"], R, t)]
    while stack:
        link, Rl, tl = stack.pop()
        cx, cy, cz = kin["com"][link]
        coms[link] = (tl[0] + Rl[0][0] * cx + Rl[0][1] * cy + Rl[0][2] * cz,
                      tl[1] + Rl[1][0] * cx + Rl[1][1] * cy + Rl[1][2] * cz,
                      tl[2] + Rl[2][0] * cx + Rl[2][1] * cy + Rl[2][2] * cz)
        for k in kin["children"].get(link, []):
            jk = J[k]
            x, y, z = jk["xyz"]
            Rj = Rl if jk["rpy_is_identity"] else _mul3(Rl, jk["rpy"])
            tk = (tl[0] + Rj[0][0] * x + Rj[0][1] * y + Rj[0][2] * z,
                  tl[1] + Rj[1][0] * x + Rj[1][1] * y + Rj[1][2] * z,
                  tl[2] + Rj[2][0] * x + Rj[2][1] * y + Rj[2][2] * z)
            Ra = _axis_rotation(jk["axis"], angles.get(jk["name"], 0.0))
            stack.append((jk["child"], _mul3(Rj, Ra), tk))
    return origin, axis_w, coms


def gravity_torque(kin: Dict[str, Any], ji: int,
                   angles: Dict[str, float], signed: bool = False) -> float:
    """该关节在给定姿态下的重力力矩（N·m）。signed=True 时保留方向。"""
    origin, axis_w, coms = _joint_state(kin, ji, angles)
    ax, ay = axis_w[0], axis_w[1]
    moment = 0.0   # Σ m·(r_x·a_y − r_y·a_x)，单位 kg·mm
    for link, p in coms.items():
        rx, ry = p[0] - origin[0], p[1] - origin[1]
        moment += kin["mass"][link] * (rx * ay - ry * ax)
    tau = moment / 1000.0 * G     # kg·mm -> kg·m -> N·m
    return tau if signed else abs(tau)


def _best_on_axis(kin: Dict[str, Any], ji: int, q: Dict[str, float],
                  ki: int) -> Tuple[float, float]:
    """固定其余自由度，求第 ki 个关节在其限位内使 |τ| 最大的角度（精确解）。

    固定其余关节、只转第 ki 个：整条受影响链绕**定轴**刚体转动，τ 必为
    `C + A·cosθ + B·sinθ`；取 θ = 0、π/2、π 三点即可定出系数，再闭式取最大。
    """
    jk = kin["joints"][ki]
    name = jk["name"]
    lo, hi = jk["lo"], jk["hi"]
    t0 = gravity_torque(kin, ji, {**q, name: 0.0}, signed=True)
    tpi = gravity_torque(kin, ji, {**q, name: math.pi}, signed=True)
    th = gravity_torque(kin, ji, {**q, name: math.pi / 2.0}, signed=True)
    C = 0.5 * (t0 + tpi)
    A = 0.5 * (t0 - tpi)
    B = th - C
    amp = math.hypot(A, B)
    phi = math.atan2(B, A)
    cands = [lo, hi]
    for base in (phi, phi + math.pi):
        for m in (-2, -1, 0, 1, 2):
            x = base + 2.0 * math.pi * m
            if lo - 1e-12 <= x <= hi + 1e-12:
                cands.append(min(max(x, lo), hi))
    best_v, best_x = -1.0, lo
    for x in cands:
        v = abs(C + amp * math.cos(x - phi))
        if v > best_v:
            best_v, best_x = v, x
    return best_v, best_x


def worst_case_gravity(kin: Dict[str, Any], ji: int,
                       sweeps: int = 6) -> Tuple[float, Dict[str, float]]:
    """限位内最不利姿态下的 |重力矩|（N·m）与该姿态（度）。

    方法：在『该关节 + 祖先 + 后代』相关自由度上做坐标上升，每轴用
    _best_on_axis() 取**精确**极值；从零位、全下限、全上限三个起点各收敛一次取最大。
    只搜索运动学限位（不含地面接触与平衡约束），因此是**上界**。
    """
    key = kin["key"]
    cache = _WORST_CASE_CACHE.setdefault(key, {})
    hit = cache.get(ji)
    if hit is not None:
        return hit
    J = kin["joints"]
    rel = kin["rel"][ji]
    # 起点集（**确定性**，不用随机数）：零位、全下限、全上限，外加"每个相关自由度
    # 单独顶到某一端"。最优点通常落在若干自由度的限位上，这组起点能覆盖到；
    # 曾用 200 个随机起点做过对照，本起点集已能取到同样的最大值（见线程报告 §验证）。
    starts = [{},
              {J[k]["name"]: J[k]["lo"] for k in rel},
              {J[k]["name"]: J[k]["hi"] for k in rel}]
    for k in rel:
        starts.append({J[k]["name"]: J[k]["lo"]})
        starts.append({J[k]["name"]: J[k]["hi"]})
    glob_v, glob_q = 0.0, {}
    for s in starts:
        q = dict(s)
        cur = abs(gravity_torque(kin, ji, q, signed=True))
        for _ in range(sweeps):
            for k in rel:
                _, x = _best_on_axis(kin, ji, q, k)
                q[J[k]["name"]] = x
            new = abs(gravity_torque(kin, ji, q, signed=True))
            if new <= cur + 1e-12:
                break
            cur = new
        if cur > glob_v:
            glob_v = cur
            glob_q = {J[k]["name"]: round(math.degrees(q[J[k]["name"]]), 1)
                      for k in rel if abs(q.get(J[k]["name"], 0.0)) > 1e-9}
    # 竖直轴关节（髋 yaw、头 yaw）的重力矩**恒为 0**：数值噪声不要变成一个"最不利姿态"
    if glob_v <= 1e-9:
        glob_v, glob_q = 0.0, {}
    cache[ji] = (glob_v, glob_q)
    return glob_v, glob_q


def gravity_arm_detail(kin: Dict[str, Any], ji: int,
                       angles: Dict[str, float]) -> List[Dict[str, Any]]:
    """逐 link 力臂明细（重力口径与惯性口径都列，便于复核与自洽断言）。

    - `gravity_arm_mm`        = |signed|，重力力臂的**大小**
    - `signed_gravity_arm_mm` = 带符号，Σ m·g·signed/1000 即该姿态的重力矩（带符号）
    - `moment_kgmm`           = m·signed，Σ moment/1000·g = τ（可直接对账）
    - `radial_arm_mm`         = 到轴线的垂直距离（仅供惯性与几何参考，**不是**重力力臂）
    """
    origin, axis_w, coms = _joint_state(kin, ji, angles)
    n = math.sqrt(sum(v * v for v in axis_w)) or 1.0
    out = []
    for link in kin["subtree"][ji]:
        p = coms[link]
        r = (p[0] - origin[0], p[1] - origin[1], p[2] - origin[2])
        m = kin["mass"][link]
        # 带符号的重力力臂：Σ m·g·signed/1000 就是该姿态的重力矩（符号即力矩方向）
        signed = (r[0] * axis_w[1] - r[1] * axis_w[0]) / n
        out.append({
            "link": link,
            "mass_kg": m,
            "gravity_arm_mm": round(abs(signed), 2),
            "signed_gravity_arm_mm": round(signed, 2),
            "moment_kgmm": round(m * signed, 4),
            "radial_arm_mm": round(perpendicular_arm(r, list(axis_w)), 2),
        })
    return out


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


def total_mass_of(model: Dict[str, Any]) -> float:
    """整机质量（含线束与紧固件），用于单腿支撑载荷计算。"""
    return (sum(l["mass_kg"] for l in model["links"])
            + ASSUMPTIONS["cable_mass_kg"] + ASSUMPTIONS["fastener_mass_kg"])


_TOTAL_MASS_CACHE: Dict[Any, float] = {}


def joint_torque(model: Dict[str, Any], joint: Dict[str, Any]) -> Dict[str, Any]:
    """计算该关节的力矩需求。

    **重力矩两种口径同时给出**（2026-09-12 修正后）：
      (a) `gravity_torque_nm_zero_pose`  —— 零姿态静力（真实站立不动的重力矩）
      (b) `gravity_torque_nm_worst_case` —— 限位内最不利姿态（选型用的保守上界）
    两者都进入 `required_torque_nm_*`（再各自与惯性/单腿支撑/工程下限取包络），
    **主判据（required_torque_nm = 选型需求）取保守口径**，零姿态口径并列报出。
    """
    kin = _kinematics(model)
    ji = kin["index"][joint["name"]]
    mkey = kin["key"]
    if mkey not in _TOTAL_MASS_CACHE:
        _TOTAL_MASS_CACHE[mkey] = total_mass_of(model)
    total_mass_all = _TOTAL_MASS_CACHE[mkey]

    zero_pose: Dict[str, float] = {}
    detail = gravity_arm_detail(kin, ji, zero_pose)
    total_mass = sum(d["mass_kg"] for d in detail)

    # (a) 零姿态重力矩：真实站在零位的重力矩（不含安全系数）
    # (b) 限位内最不利姿态：相关自由度上搜索出的最大 |重力矩|
    # 两者先取整到发布精度，后面所有派生量（需求/裕度/百分比）都由**发布值**算，
    # 下游拿 JSON 里的数复算就能对上（不留 1e-4 级的自相矛盾）。
    tau_grav_zero = round(gravity_torque(kin, ji, zero_pose), 4)
    tau_grav_worst_raw, worst_posture = worst_case_gravity(kin, ji)
    tau_grav_worst = round(tau_grav_worst_raw, 4)

    # 惯性力矩：τ = I·α，I = Σ m·r⊥²（沿轴的垂直距离；与重力力臂不是同一个量）
    inertia = 0.0
    for d in detail:
        r_m = d["radial_arm_mm"] / 1000.0
        inertia += d["mass_kg"] * r_m * r_m
    alpha = ASSUMPTIONS["angular_accel_rad_s2"]
    inertia_pub = round(inertia, 6)
    tau_inertia = round(inertia_pub * alpha, 4)

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
        tau_stance = round(mass_above * G
                           * (ASSUMPTIONS["gait_cop_offset_mm"] / 1000.0)
                           * ASSUMPTIONS["stance_dynamic_factor"], 4)

    # 两种口径各自取包络（惯性/支撑/工程下限对两者相同）
    tau_req_zero = round(max(tau_grav_zero * sf, tau_inertia * sf,
                             tau_stance, floor), 4)
    tau_req_worst = round(max(tau_grav_worst * sf, tau_inertia * sf,
                              tau_stance, floor), 4)
    # 主判据 = 保守口径（最不利姿态）
    tau_req = tau_req_worst

    # 主导因素，便于下游理解这个数是怎么来的（按主判据算）
    cands = {
        "gravity": tau_grav_worst * sf,
        "inertia": tau_inertia * sf,
        "stance": tau_stance,
        "practical_floor": floor,
    }
    driver = max(cands, key=lambda k: cands[k])
    if cands[driver] <= floor + 1e-9:
        driver = "practical_floor"

    crit = torque_criteria(model)
    rated = crit["continuous_rated_torque_nm"]
    peak = crit["peak_torque_nm"]
    # 裕度必须由**发布出去的那个数**算，否则 JSON 里 margin ≠ required/rated：
    # 下游拿 required_torque_nm 复算就会对不上（旧版按未取整值算，差 ~5e-4）。
    tau_req_pub = tau_req
    tau_req_zero_pub = tau_req_zero
    margin_continuous = tau_req_pub / rated if rated else 0.0
    margin_peak = tau_req_pub / peak if peak else 0.0
    margin_continuous_zero = tau_req_zero_pub / rated if rated else 0.0
    margin_peak_zero = tau_req_zero_pub / peak if peak else 0.0

    return {
        "joint": joint["name"],
        "id": joint["id"],
        "axis": joint["axis"],
        "limit_deg": joint["limit_deg"],
        "max_speed_dps": joint["velocity_dps"],
        "distal_mass_kg": round(total_mass, 4),
        # 力臂：重力口径（零姿态 / 最不利姿态）与惯性口径（径向）分列，勿混用
        "max_gravity_arm_zero_pose_mm": round(
            max((d["gravity_arm_mm"] for d in detail), default=0.0), 2),
        "max_gravity_arm_worst_case_mm": round(
            max((d["gravity_arm_mm"] for d in gravity_arm_detail(
                kin, ji, worst_posture_rad(worst_posture))), default=0.0), 2),
        "max_radial_arm_mm": round(
            max((d["radial_arm_mm"] for d in detail), default=0.0), 2),
        # 兼容字段：旧名 max_arm_mm 历史上是"径向臂"，保留但语义见上
        "max_arm_mm": round(
            max((d["radial_arm_mm"] for d in detail), default=0.0), 2),
        "distal_inertia_kgm2": inertia_pub,
        "gravity_torque_nm_zero_pose": tau_grav_zero,
        "gravity_torque_nm_worst_case": tau_grav_worst,
        # 兼容字段：旧名 gravity_torque_nm 历史上是"径向臂口径"，现取**最不利姿态**
        "gravity_torque_nm": tau_grav_worst,
        "inertia_torque_nm": tau_inertia,
        "stance_torque_nm": tau_stance,
        "stance_mass_above_kg": round(mass_above, 4),
        "required_torque_nm": tau_req_pub,
        "required_torque_nm_zero_pose": tau_req_zero_pub,
        "required_torque_nm_worst_case": tau_req_pub,
        "requirements_driver": driver,
        "safety_factor": sf,
        "continuous_rated_torque_nm": rated,
        "peak_torque_nm": peak,
        "margin_vs_continuous_rated": round(margin_continuous, 6),
        "margin_vs_peak": round(margin_peak, 6),
        "margin_vs_continuous_rated_zero_pose": round(margin_continuous_zero, 6),
        "margin_vs_peak_zero_pose": round(margin_peak_zero, 6),
        "pct_continuous_rated": round(margin_continuous * 100.0, 1),
        "pct_continuous_rated_zero_pose": round(margin_continuous_zero * 100.0, 1),
        "exceeds_continuous_rated": bool(margin_continuous > 1.0 + 1e-9),
        "exceeds_peak": bool(margin_peak > 1.0 + 1e-9),
        "exceeds_continuous_rated_zero_pose": bool(
            margin_continuous_zero > 1.0 + 1e-9),
        "exceeds_peak_zero_pose": bool(margin_peak_zero > 1.0 + 1e-9),
        "torque_tier": _tier(tau_req),
        "design_placeholder_nm": joint.get("effort_nm"),
        "worst_case_posture_deg": worst_posture,
        "gravity_caliber_note": (
            "gravity_torque_nm_zero_pose = 零位真实重力矩；"
            "gravity_torque_nm_worst_case = 限位内最不利姿态的最大重力矩；"
            "required_torque_nm 取后者（保守口径），required_torque_nm_zero_pose 为前者。"),
        "detail": detail,
    }


def worst_posture_rad(worst_posture_deg: Dict[str, float]) -> Dict[str, float]:
    """把最不利姿态（度）转回弧度字典，供逐 link 力臂明细复用。"""
    return {k: math.radians(v) for k, v in worst_posture_deg.items()}


def torque_criteria(model: Dict[str, Any]) -> Dict[str, Any]:
    """舵机扭矩两个口径。字段名兼容 main 的 rated_torque_nm 与本分支的 continuous_rated。"""
    ts = model.get("servo_defaults", {})
    rated = float(ts.get("rated_torque_nm")
                  or ts.get("continuous_rated_torque_nm")
                  or 0.98)
    peak = float(ts.get("rated_torque_nm_half_stall_deprecated")
                 or ts.get("peak_torque_nm")
                 or 1.47)
    stall = float(ts.get("stall_torque_nm") or 2.94)
    return {
        "primary": "continuous_rated",
        "continuous_rated_torque_nm": rated,
        "peak_torque_nm": peak,
        "stall_torque_nm": stall,
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
        单关节电流 = 堵转电流 × (工作扭矩 / 额定扭矩)，上限为堵转电流
    不能给"总堵转电流"乘占空比——那会把电流高估数倍。
    """
    operating_fraction = 0.35   # 行走时平均输出占"最大静力保持"的比例
    # 【官方】额定负载 10 kg·cm = 0.98 N·m @12V（DFRobot SER0070 + 飞特 STS3235 规格书双重印证，
    # 见 design/handoff/STS3215-官方规格书核验.md §4.1、总体参数汇总表.md §2.1）。
    # ⚠️ 2.94 N·m 是**堵转**扭矩，不是额定：旧版把堵转当额定，会让这个以
    #    「工作扭矩 / 额定」算电流占比的模型把电流低估约 3 倍。
    rated_torque = 0.98         # N·m，【官方】额定负载（≠ 堵转 2.94）
    stall_torque = 2.94         # N·m，【官方】堵转（单独保留，勿与额定混用）
    stall_current = 2.7         # A，同级别堵转电流

    per_joint = []
    total_current = 0.0
    for t in torques:
        tau_op = t["required_torque_nm"] * operating_fraction
        ratio = min(1.0, tau_op / rated_torque) if rated_torque > 0 else 0.0
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

    return {
        "servo_bus_voltage_v": voltage,
        "servo_count": len(torques),
        "current_model": "电流 ∝ 输出扭矩（线性近似）",
        "operating_fraction": operating_fraction,
        "rated_torque_nm": rated_torque,
        "rated_torque_source": "【官方】额定负载 10 kg·cm = 0.98 N·m @12V（DFRobot SER0070 + 飞特 STS3235 规格书）",
        "stall_torque_nm": stall_torque,
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
        "per_joint_current": per_joint,
        "note": ("工作占比 0.35 为工程估值、非实测；额定扭矩与堵转电流已按【官方】口径取"
                 "（额定 0.98 / 堵转 2.94 N·m、堵转 2.7 A，见 STS3215-官方规格书核验.md）。"
                 "选定舵机后仍须按数据手册回填重算。"),
        "model_caveat": ("⚠️ 订正额定值（2.94 → 0.98 N·m）后本预算变严约 3 倍：『电流 ∝ 扭矩』"
                         "线性近似在接近额定/堵转时偏保守（真实舵机电流在低扭矩段偏低、"
                         "近堵转陡升），所以这里的电流与电池容量应读作**上限量级**，"
                         "不是可用选型值。按此口径 3S 2000 mAh 已明显不够——"
                         "电源架构（降额/限流/机构减载）需与重量方案一起重新定案。"),
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
    mb = r.get("mass_budget_g", {})
    pc = mb.get("part_count", "—")
    ie = r.get("installed_envelope_mm", r["envelope_mm"])

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

    def joint_rows() -> str:
        out = []
        for t in sorted(j, key=lambda x: -x["required_torque_nm"]):
            drv = {"gravity": "重力", "inertia": "惯性", "stance": "单腿支撑",
                   "practical_floor": "工程下限"}[t["requirements_driver"]]
            lo, hi = t["limit_deg"]
            out.append(
                f"| {t['id']:02d} | `{t['joint']}` | {t['distal_mass_kg']:.3f} | "
                f"{t['gravity_torque_nm_zero_pose']:.3f} | "
                f"{t['gravity_torque_nm_worst_case']:.3f} | "
                f"{t['inertia_torque_nm']:.3f} | {t['stance_torque_nm']:.3f} | "
                f"{t['required_torque_nm_zero_pose']:.3f} | "
                f"**{t['required_torque_nm']:.3f}** | "
                f"{t['pct_continuous_rated_zero_pose']:.0f}% | "
                f"**{t['pct_continuous_rated']:.0f}%** | "
                f"{drv} | {lo:+.0f}~{hi:+.0f} | {t['max_speed_dps']:.0f} |"
            )
        return "\n".join(out)

    def cavity_rows() -> str:
        out = []
        for c in data["cavities"]:
            i = c["inner_mm"]
            out.append(f"| `{c['link']}` | {i[0]:.0f} × {i[1]:.0f} × {i[2]:.0f} | "
                       f"{c['inner_volume_cm3']} |")
        return "\n".join(out)

    def tier_outline() -> str:
        """按当前档位汇总生成选型提纲（不再把历史档位数量写死）。"""
        out = []
        for k in ("XL", "L", "M", "S"):
            v = data["summary_by_tier"].get(k)
            if not v:
                continue
            out.append(f"### {k} 档（最大需求 {v['max_torque_nm']:.2f} N·m，"
                       f"{v['count']} 路：{'、'.join(v['joints'])}）\n"
                       f"| 型号 | 扭矩 | 速度 | 重量 | 尺寸 | 协议 | 回读 | 价格 | 备注 |\n"
                       f"|---|---|---|---|---|---|---|---|---|\n...\n")
        return "".join(out)

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
| 包络尺寸 | **{r['envelope_mm']['height_mm']:.0f} × {r['envelope_mm']['width_mm']:.0f} × {r['envelope_mm']['depth_mm']:.0f}** mm（高×宽×厚） | 由关节链几何推导（【设计】基元口径；【实测】CAD 实装见下） |
| 包络（CAD 实装，实测） | **{ie['height_mm']:.0f} × {ie['width_mm']:.0f} × {ie['depth_mm']:.0f}** mm（高×宽×厚） | `design/cad/assembly.py --all --no-export`（2026-09-12）；赛题上限 600×300×300 |
| 整机质量 | **{r['mass_kg']}** kg（**结构件实算 {mb['structure']:.0f} g** / {pc} 件 + 舵机 {mb['servos']:.0f} + 电子件与电池 {mb['electronics']:.0f} + 线束紧固件 {mb['harness_fasteners']:.0f}）—— **整机为纸面推算，重量方案未定案** | 结构实算（CAD）/ 整机推算 |
| 赛道要求 | {r['competition_class']} | 中国国际大学生创新大赛陕西赛区 |
| 运动学模型 | `atri.urdf`（23 link / 22 joint，含惯量） | 可直接加载 PyBullet / Webots |

**关节定义**：名称、编号、轴向、角度限位与固件完全一致，
不是随手编的——有单元测试逐项校验同源。

---

## 三、硬件选型需求（你的主要输入）

### 3.1 关节力矩需求

**计算方法**（可复现）：

三种工况取包络（用哪个大就用哪个），每种工况各自算**两个重力口径**：

```
① 重力保持   τ_g = Σ mᵢ·g·armᵢ · {asm['safety_factor_static']}
             armᵢ = **重力力臂** = 质心偏移在水平面内、垂直于关节轴的分量
                    = |r_x·a_y − r_y·a_x|（â = 该关节由 URDF 正解出的世界轴向）
             ⚠ 不是"质心到轴线的垂直距离"（那个含沿轴分量，只用于②的惯性半径）
             ⚠ 竖直轴关节（髋 yaw / 头 yaw）该力臂恒为 0：重力与该轴平行，绕它不产生力矩
             ▸ (a) 零姿态口径：各关节 0° 时的真实重力矩 = gravity_torque_nm_zero_pose
             ▸ (b) 最不利口径：在**关节限位内**搜索出的最大重力矩 = gravity_torque_nm_worst_case
                   （含祖先与后代关节的姿态自由度；方法见 assumptions.worst_case_search）
② 惯性       τ_i = (Σ mᵢ·r⊥ᵢ²) · α · {asm['safety_factor_static']}
             r⊥ᵢ = 下游质心到关节轴线的**垂直距离**（含沿轴分量，与①的力臂不是一个量）
             α = {asm['angular_accel_rad_s2']} rad/s²（摆腿/摆臂角加速度）
③ 单腿支撑   τ_s = (整机质量 − 下游腿段质量) · g · {asm['gait_cop_offset_mm']:.0f}mm · {asm['stance_dynamic_factor']}
             ⚠ 腿部关节的真正选型依据：支撑期要撑起全身重量（动载系数 2.0，与①的
               静力安全系数 {asm['safety_factor_static']} 是两回事，不叠加使用）
安全下限     {asm['min_practical_torque_nm']} N·m（低于此值齿轮刚度与回程间隙不可接受）
```

**两种重力口径都要看，不要只看一个**（下面的表两列都给了）：

| 口径 | 含义 | 用在哪 |
|---|---|---|
| **零姿态静力**（(a)） | 当前 URDF 零位（站立不动）时的真实重力矩 | 回答"站着不动到底要扛多少"；这是最贴近实际静止工况的数 |
| **限位内最不利**（(b)） | 在该关节自身限位内、连同祖先/后代关节一起搜索出的最大重力矩 | **选型用的保守上界**：舵机必须在整个运动范围内都不失步 |

`需求（最不利）` 列是**主判据**（保守口径，用于选型）；`需求（零姿态）` 列是同一套
惯性/支撑/下限工况换成零姿态重力矩的结果，两者一般不同，**引用时必须写明用的是哪一种**。

**"依据"列**告诉你每个数是怎么来的：竖直轴关节（髋 yaw、头 yaw）
重力矩恒为 0，实际是按惯性或工程下限定的。

| ID | 关节 | 下游质量(kg) | 重力矩(零姿态) | 重力矩(最不利) | 惯性矩 | 单腿支撑 | 需求(零姿态) | **需求(最不利·主判据)** | 占额定(零) | 占额定(主) | 依据 | 限位(°) | 最大速度(°/s) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
{joint_rows()}

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

> ⚠️ **口径订正（2026-09-12）**：额定扭矩按【官方】**0.98 N·m**（此前误用堵转 2.94），
> 本预算因此变严约 3 倍。{pb.get('model_caveat', '')}

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
{tier_outline()}## 电控平台
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

扭矩主判据为【官方额定】0.98 N·m（堵转 2.94 只作参考）。**两种重力口径都报**：
`torque_criterion.joints_exceeding_continuous` = 按**最不利姿态**口径（主判据）超额定的关节，
`torque_criterion.joints_exceeding_continuous_zero_pose` = 按**零姿态**口径超额定的关节。
本次两者相同（腿链 10 个关节，由单腿支撑工况决定）。
过程提示词已迁到 `design/handoff/prompt-*.md` 与 `docs/process/`，不再把不存在的「下一轮」文件写进附件表。

---

## 八、边界声明

- 本文件中"**设计值**"均为**基于质量分布与力臂的计算/估算**，
  **不是实测数据**，也未做刚体动力学仿真。
- 力矩有**两种重力口径**：零姿态（站立不动）与限位内最不利姿态（搜索出的保守上界）；
  最不利姿态只搜索运动学限位，不含地面接触与平衡约束，因此是**上界**、不是实际步态值。
- 舵机外形与电气参数为**同级别产品典型值**，选定型号后需回填重算。
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
    # 头条整机质量用 robot_model 的权威口径（= out/report.md 合计 3136 g），
    # link 累加值（3136.6）另存 links_total，避免与总表/README 差 1 g 对不上。
    mb = model.get("mass_budget", {})
    headline_mass_g = float(mb.get("total_g", round(total_mass * 1000, 1)))
    part_count = model.get("installed_parts_count") or 81
    power = power_budget(model, torques)

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
            "installed_envelope_mm": model.get("installed_envelope_mm", {}),
            "mass_status": model.get("mass_status", {}),
            "mass_kg": round(headline_mass_g / 1000.0, 3),
            "mass_budget_g": {
                "structure": mb.get("structure_g"),
                "servos": mb.get("servos_g"),
                "electronics": mb.get("electronics_g"),
                "harness_fasteners": mb.get("harness_fasteners_g"),
                "total": headline_mass_g,
                "part_count": part_count,
                "status": "结构件实算；整机纸面推算，重量方案未定案",
            },
            "mass_breakdown_kg": {
                "links_total": round(declared_mass, 3),
                "cables": ASSUMPTIONS["cable_mass_kg"],
                "fasteners": ASSUMPTIONS["fastener_mass_kg"],
            },
            "competition_class": "小人形组（高≤600 宽≤300 厚≤300 mm，≥18 DOF，≥7.4V）",
        },
        "assumptions": ASSUMPTIONS,
        "joints": torques,
        "summary_by_tier": {},
        "cavities": [
            cavity(model, "torso_upper"),
            cavity(model, "pelvis"),
            cavity(model, "head"),
        ],
        "power_budget": power,
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
                "battery": (f"3S 11.1V 锂聚合物；30 min 任务按额定 0.98 口径需标称 "
                            f"≥{power['required_nameplate_ah']} Ah（现选 2000 mAh 不够）"),
                "regulation": "独立 BEC 给舵机供电，与逻辑电源隔离",
                "connector": "XT60 主接口",
            },
        },
        "what_is_placeholder": [
            "所有 link 的几何是**基元占位**（长方体/圆柱/球/胶囊），"
            "只表达包络与连接关系，不是可加工零件。",
            "舵机外形（45.2×24.7×35.0 mm）取 STS3215 实测包络，轴心不在长度中点。",
            "未建模：舵机支架、轴承、走线槽、螺钉柱、拔模与圆角。",
            "未建模：电池与电路板的实际安装位置与固定方式。",
            "力矩需求为**静力估算**（零姿态 + 限位内最不利姿态两种口径），"
            "未做刚体动力学仿真；最不利姿态不含地面接触与平衡约束，是上界。",
        ],
        "what_is_real": [
            "关节数量、编号、名称、轴向、角度限位 —— 与固件 config.py 同源。",
            "运动学树（父子关系与关节原点）—— 可直接加载 URDF 验证。",
            "整机包络尺寸与质量预算 —— 由几何推导，与声明值一致。",
            "力矩需求的**推导方法**与量级 —— 基于质量分布与重力力臂计算；"
            "重力力臂由 URDF 轴向量正解得到（不硬编码方向）。",
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

    crit = torque_criteria(model)
    exceeding = sorted(t["joint"] for t in torques if t.get("exceeds_continuous_rated"))
    exceeding_peak = sorted(t["joint"] for t in torques if t.get("exceeds_peak"))
    exceeding_zero = sorted(t["joint"] for t in torques
                            if t.get("exceeds_continuous_rated_zero_pose"))
    exceeding_peak_zero = sorted(t["joint"] for t in torques
                                 if t.get("exceeds_peak_zero_pose"))
    out["torque_criterion"] = {
        "primary": crit["primary"],
        # 主判据用的重力口径（最不利姿态）；零姿态口径的清单并列给出
        "primary_gravity_caliber": ASSUMPTIONS["gravity_torque_calibers"][1],
        "gravity_calibers": ASSUMPTIONS["gravity_torque_calibers"],
        "continuous_rated_torque_nm": crit["continuous_rated_torque_nm"],
        "peak_torque_nm": crit["peak_torque_nm"],
        "stall_torque_nm": crit["stall_torque_nm"],
        "joints_exceeding_continuous": exceeding,
        "joints_exceeding_peak": exceeding_peak,
        "joints_exceeding_continuous_zero_pose": exceeding_zero,
        "joints_exceeding_peak_zero_pose": exceeding_peak_zero,
        "note": ("两种口径并列报出：*_zero_pose = 零位站立不动的真实重力矩口径；"
                 "无后缀 = 限位内最不利姿态口径（主判据/选型用）。"),
    }
    # 紧凑的扭矩体检块（供快速人工核对；逐关节两种口径的百分比）
    out["torque_check"] = {
        "criterion": "舵机【官方】连续额定 0.98 N·m（堵转 2.94 仅作参考）",
        "calibers": {
            "zero_pose_static": "零姿态静力：URDF 零位（站立不动）的真实重力矩口径",
            "worst_case_within_limits": "限位内最不利姿态：该关节限位内搜索出的最大重力矩口径（主判据）",
        },
        "joints_pct_of_continuous_rated": [
            {"joint": t["joint"],
             "zero_pose_pct": t["pct_continuous_rated_zero_pose"],
             "worst_case_pct": t["pct_continuous_rated"],
             "exceeds_rated": t["exceeds_continuous_rated"],
             "exceeds_rated_zero_pose": t["exceeds_continuous_rated_zero_pose"]}
            for t in sorted(torques, key=lambda x: -x["required_torque_nm"])
        ],
        "exceeding_worst_case": exceeding,
        "exceeding_zero_pose": exceeding_zero,
        "same_set": exceeding == exceeding_zero,
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / "hardware_requirements.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")

    # 控制台摘要
    print("=" * 70)
    print("硬件选型需求（由设计模型推导）")
    print("=" * 70)
    print(f"整机质量 {headline_mass_g / 1000.0:.3f} kg（推算，重量方案未定案）   DOF {len(model['joints'])}")
    ie = model.get("installed_envelope_mm", {})
    if ie:
        print(f"实装包络 {ie['height_mm']:.0f} × {ie['width_mm']:.0f} × {ie['depth_mm']:.0f} mm"
              f"（高×宽×深，实测）")
    print(f"包络 {model['overall']['height_mm']:.0f} × "
          f"{model['overall']['width_mm']:.0f} × "
          f"{model['overall']['depth_mm']:.0f} mm（基元/运动学口径）")
    print()
    print("关节力矩需求（重力矩两种口径并列；主判据取『限位内最不利姿态』）:")
    print("  力臂 = 质心偏移在水平面内垂直于关节轴的分量（不含竖直分量）；"
          "竖直轴关节恒为 0")
    print(f"  {'ID':>3} {'关节':<22} {'重力0°':>7} {'重力限位内':>10} {'惯性':>7} "
          f"{'支撑':>7} {'需求0°':>7} {'需求主':>7} {'%0°':>5} {'%主':>5} "
          f"{'依据':<14}")
    for t in sorted(torques, key=lambda x: -x["required_torque_nm"]):
        print(f"  {t['id']:>3} {t['joint']:<22} "
              f"{t['gravity_torque_nm_zero_pose']:>7.3f} "
              f"{t['gravity_torque_nm_worst_case']:>10.3f} "
              f"{t['inertia_torque_nm']:>7.3f} "
              f"{t['stance_torque_nm']:>7.3f} "
              f"{t['required_torque_nm_zero_pose']:>7.3f} "
              f"{t['required_torque_nm']:>7.3f} "
              f"{t['pct_continuous_rated_zero_pose']:>4.0f}% "
              f"{t['pct_continuous_rated']:>4.0f}% "
              f"{t['requirements_driver']:<14}")
    print()
    print(f"超【官方额定 0.98 N·m】的关节 —— 最不利口径 {len(exceeding)} 个: "
          f"{'、'.join(exceeding) if exceeding else '无'}")
    print(f"                              零姿态口径 {len(exceeding_zero)} 个: "
          f"{'、'.join(exceeding_zero) if exceeding_zero else '无'}"
          f"{'（与最不利口径同一集合）' if exceeding == exceeding_zero else '⚠ 两口径不同'}")
    print()
    print("分档汇总:")
    for k in ("S", "M", "L", "XL"):
        if k in tier_acc:
            v = tier_acc[k]
            print(f"  {k:<3} {v['count']:>2} 路  最大 {v['max_torque_nm']:.2f} N·m")
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
