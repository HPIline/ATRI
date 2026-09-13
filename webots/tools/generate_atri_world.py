"""生成 A.T.R.I. 20 DOF（v2，无 hip_yaw）的 Webots 运动学联调世界。

为什么要生成而不是手写：20 个关节 × (HingeJoint + RotationalMotor + PositionSensor
+ endPoint Solid) 手写近千行且极易写错；用脚本生成，改尺寸/改关节只需改这里的表。

为什么自包含、不用 ``EXTERNPROTO``：本机（以及比赛机器的网络）访问 GitHub 受限，
世界文件一旦依赖外部 PROTO 就可能打不开。这里全部用 Webots 内置节点
（``Robot`` / ``HingeJoint`` / ``RotationalMotor`` / ``PositionSensor`` / ``Solid`` /
``Box``，带地面时再加 ``Plane``——不加地面就不用）。

电机名与 ``controllers/atri_controller/joint_mapping.json`` 完全一致（默认同名映射），
所以 20 个关节全部能绑定上，联调跑的就是全关节。关节硬限位（``minStop``/``maxStop``）
取自 ``design/v2/profile.py``，原点/轴向/质量取自 ``design/v2/out/sim/atri_v2.urdf``。
旧 22 DOF 世界备份在 ``archive/v1-22dof/webots/worlds/atri_22dof.wbt``，本生成器默认不再覆盖它。

用法::

    python webots/tools/generate_atri_world.py        # 默认：零重力 20 DOF 运动学联调世界

    # 带重力校核世界（S1 静立 / S2 站立扭矩用）：
    ATRI_WORLD_GRAVITY=9.81 ATRI_WORLD_MAX_TORQUE=2.94 ATRI_WORLD_GROUND=1 \\
        python webots/tools/generate_atri_world.py --out /tmp/atri_grav.wbt

四个可选覆盖（同名命令行参数优先于环境变量；两者都不给 = 现在的默认行为）：

* ``ATRI_WORLD_GRAVITY`` / ``--gravity``：``WorldInfo.gravity``，默认 ``0.0``（零重力）。
  本机 Webots R2025a + ENU 实测：``9.81`` 落到地面，负值沿 +Z 飞走，所以 ``gravity < 0``
  直接报错退出。
* ``ATRI_WORLD_MAX_TORQUE`` / ``--max-torque``：逐电机 ``maxTorque``（N·m），默认**不写该字段**。
  注意"不写"≠无限大：Webots 默认 **10 N·m**，是 STS3215 堵转 2.94 N·m 的 3.4 倍，
  做扭矩校核时必须显式设成 2.94，否则结论作废。
* ``ATRI_WORLD_GROUND`` / ``--ground``：生成 ``Plane`` 地面（4 m × 4 m，理由见 ``GROUND_SIZE``），
  默认不生成。**重力非 0 时自动强制打开**——有重力没地面就是自由落体，跑出来的数字全是废的。
* ``--out <path>``：输出到别的路径（例如 ``docs/process/sim/worlds/`` 下的临时副本），
  默认仍是 ``webots/worlds/atri_v2.wbt``。

**不带任何开关跑出来的世界与提交在仓库里的 ``worlds/atri_v2.wbt`` 逐字节一致**，
CI 就是靠这条对账的（``git diff --exit-code``）。
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

WORLD_PATH = Path(__file__).resolve().parents[1] / "worlds" / "atri_v2.wbt"

# v2 单一事实来源：限位来自 design/v2/profile.py，运动学树来自 atri_v2.urdf。
REPO = Path(__file__).resolve().parents[2]
URDF_PATH = REPO / "design" / "v2" / "out" / "sim" / "atri_v2.urdf"
sys.path.insert(0, str(REPO / "design"))
sys.path.insert(0, str(REPO / "software" / "atri"))
import geometry  # noqa: E402  （纯标准库）
from v2 import profile as v2_profile  # noqa: E402
from atri.stand_balance import pelvis_spawn_z_m  # noqa: E402

# 世界标称版本：与本机验证用的 Webots R2025a 对齐（工程说明要求 R2023b 或更新）
WORLD_VERSION = "R2025a"
BASIC_TIME_STEP = 32
GRAVITY_TIME_STEP = 8
GRAVITY_JOINT_DAMPING = 2.0

# --------------------------------------------------------------------------
# 默认值：必须与提交在仓库里的 worlds/atri_v2.wbt 逐字节一致
# --------------------------------------------------------------------------
# 重力置零：这是"运动学联调"世界，验证的是 20 个关节角是否被正确下发与跟随，
# 不是双足平衡。零重力下机器人不会倒地，关节可以自由摆动，轨迹看得最清楚。
#
# 注意：Webots R2025a 里 WorldInfo.gravity 是 **SFFloat**（沿"下"轴的大小），
# 不是 SFVec3f。写成 `gravity 0 0 0` 会让世界文件解析失败，
# Webots 会静默回退到内置 empty.wbt——控制器一个都不会启动。
# 本机 Webots R2025a + ENU 实测：gravity 9.81 才落到地面，-9.81 会沿 +Z 飞走。
GRAVITY = 0.0
DEFAULT_GRAVITY = GRAVITY
# 不写 maxTorque = 沿用 Webots 默认 10 N·m（不是无限大）。
# 真实 STS3215 堵转只有 2.94 N·m，不显式收紧就是把舵机权限放宽 3.4 倍，扭矩结论作废。
DEFAULT_MAX_TORQUE: Optional[float] = None
# 默认不生成地面：零重力世界里机器人不下落，地面只会多余地参与渲染。
DEFAULT_GROUND = False

# 地面边长（m）。取 4 × 4 的理由：
#   * 机器人高 0.407 m、脚盒 0.11 m，静止站立与五张任务卡场景位移都在 0.5 m 量级，
#     4 m 给出 ±2 m（≈ 5 倍机高）余量，够"足够大"；
#   * 再大只会拖慢渲染、影响取景，本场景不需要大地图。
# 重力世界用静态盒做地面（无 Physics）。ODE 无限 Plane 上薄脚盒摩擦经常失效；
# 官方 NAO Floor / KHR RectangleArena 也是盒，不是 Plane。
GROUND_SIZE = 4.0
GROUND_THICKNESS = 0.1

_TRUE_WORDS = {"1", "true", "yes", "on", "y"}
_FALSE_WORDS = {"0", "false", "no", "off", "n", ""}

# 关节阻尼（HingeJointParameters.dampingConstant，单位 N·m·s/rad）。
#
# 必须显式写、且必须 > 0：Webots 不给关节写阻尼时，这个"零重力 + 20 个轻质连杆"
# 世界对约束求解器是不稳定的。2026-09-12 在 Windows + Webots R2025a 上实测：
#   * 不写阻尼：trunk_pitch / hip_pitch / knee_pitch / shoulder_pitch /
#     elbow_pitch / gripper 在**启动 4 个物理步（128 ms）内**被弹到 -1309°、-1976°、
#     -2937°、+4138°、+17636° 后卡死；位置传感器从此读数恒定在几千度、且不再跟随
#     任何指令 —— 控制器测到的"有行程关节"因此从 18/22 掉到 11/22，动作链路看起来
#     "没动"，实际是世界坏了。对照组（只加这一行）三个被观测关节全部精确到位
#     （膝 20.0°、肘 -40.0°、夹爪 20.0°）。
#   * 0.5 是实测稳定且不掩盖运动的取值；太小（< 0.05）仍会有启动瞬态。
# 这条与 minStop/maxStop 一样属于"不写就是错的默认值"，所以由生成器统一写死。
JOINT_DAMPING = 0.5


def num(value: float) -> str:
    """把数字格式化成 WBT 里好看的形式。"""
    if float(value) == int(value):
        return str(int(value))
    return f"{float(value):.4f}".rstrip("0").rstrip(".")


def num_inertia(value: float) -> str:
    """惯量必须比 num() 更高精度，否则 9.6e-5 会被四舍五入成 1e-4。"""
    text = f"{float(value):.9f}".rstrip("0").rstrip(".")
    return text if text else "0"


def vec(values: Sequence[float]) -> str:
    return " ".join(num(v) for v in values)


# --------------------------------------------------------------------------
# 可选覆盖：命令行 > 环境变量 > 默认值（默认值 = 现有世界文件）
# --------------------------------------------------------------------------
class Options(NamedTuple):
    """一次生成用的全部参数。"""

    gravity: float
    max_torque: Optional[float]
    ground: bool
    out: Path
    ground_auto: bool = False  # 地面是被"重力非 0"这条硬约束自动打开的

    @property
    def is_default(self) -> bool:
        """是否等于默认组合（= 与提交在仓库里的世界逐字节一致的那种跑法）。"""
        return (
            self.gravity == DEFAULT_GRAVITY
            and self.max_torque is None
            and not self.ground
        )


def _env_float(name: str, default: Optional[float]) -> Optional[float]:
    """读一个浮点环境变量；未设置或空白用默认值，写了非法值直接报错。

    **非法值不能悄悄退回默认**：``ATRI_WORLD_GRAVITY=-9,81``（逗号）这种笔误
    如果被吞掉，生成出来的还是零重力世界，S1/S2 的数字就全是假的。
    """
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw.strip())
    except ValueError:
        raise ValueError(f"环境变量 {name}={raw!r} 不是合法数字") from None


def _env_flag(name: str, default: bool) -> bool:
    """读一个开关环境变量（1/0、true/false、on/off）；写了非法值直接报错。"""
    raw = os.environ.get(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in _TRUE_WORDS:
        return True
    if value in _FALSE_WORDS:
        return False
    raise ValueError(f"环境变量 {name}={raw!r} 不是合法开关（用 1/0、true/false、on/off）")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="生成 A.T.R.I. 20 DOF 的 Webots 世界文件（默认：零重力运动学联调世界）"
    )
    parser.add_argument(
        "--out", default=None, help="输出路径（默认 webots/worlds/atri_v2.wbt）"
    )
    parser.add_argument(
        "--gravity", type=float, default=None,
        help="WorldInfo.gravity，m/s²，沿 Z 轴向下为负（如 -9.81）；默认 0 = 零重力",
    )
    parser.add_argument(
        "--max-torque", type=float, default=None,
        help="逐电机 maxTorque，N·m；默认不写该字段（Webots 默认 10 N·m）",
    )
    parser.add_argument(
        "--ground", action="store_true", default=None,
        help="生成 Plane 地面（默认不生成；重力非 0 时自动启用）",
    )
    return parser


def resolve_options(args: argparse.Namespace) -> Options:
    """把命令行/环境变量/默认值合成一份 Options，并把两条硬约束在这里卡住。"""
    gravity = args.gravity
    if gravity is None:
        gravity = _env_float("ATRI_WORLD_GRAVITY", DEFAULT_GRAVITY)
    assert gravity is not None  # DEFAULT_GRAVITY 非 None，仅帮类型检查器

    max_torque = args.max_torque
    if max_torque is None:
        max_torque = _env_float("ATRI_WORLD_MAX_TORQUE", DEFAULT_MAX_TORQUE)

    ground = args.ground if args.ground is not None else _env_flag("ATRI_WORLD_GROUND", DEFAULT_GROUND)

    if max_torque is not None and not math.isfinite(max_torque):
        raise ValueError(f"maxTorque 必须是有限数，实际 {max_torque}")
    if max_torque is not None and max_torque <= 0:
        raise ValueError(
            f"maxTorque 必须 > 0，实际 {max_torque}：0 或负数等于电机没有力矩，机器人会直接瘫掉"
        )
    if not math.isfinite(gravity):
        # nan / inf 会被原样写进 WBT，Webots 解析失败后会静默回退到 empty.wbt
        raise ValueError(f"gravity 必须是有限数，实际 {gravity}")
    if gravity < 0:
        # R2025a + ENU 实测：gravity -9.81 沿 +Z 加速（往天上飞），
        # gravity 9.81 才落到地面。与部分旧文档「负号向下」相反。
        raise ValueError(
            f"gravity 必须 ≥ 0，实际 {gravity}：本机 Webots R2025a ENU 下负值会把机器人弹上天"
        )

    ground_auto = False
    if gravity != 0.0 and not ground:
        # 硬约束：非零重力 + 无地面 = 自由落体，静立/站立数字全部作废。
        # 这里自动补上地面而不是报错，免得队友少写一个环境变量就白跑一轮。
        ground = True
        ground_auto = True

    out = Path(args.out) if args.out else WORLD_PATH
    if not out.is_absolute():
        out = Path.cwd() / out
    return Options(
        gravity=float(gravity),
        max_torque=None if max_torque is None else float(max_torque),
        ground=bool(ground),
        out=out,
        ground_auto=ground_auto,
    )


def joint(
    name: str,
    axis: Sequence[float],
    anchor: Sequence[float],
    size: Sequence[float],
    mass: float = 0.15,
    limit_deg: Sequence[float] = (-180.0, 180.0),
    velocity_dps: float = 180.0,
    inertia: Optional[Tuple[float, float, float, float, float, float]] = None,
    com: Optional[Tuple[float, float, float]] = None,
    children: Sequence[Dict[str, Any]] = (),
) -> Dict[str, Any]:
    """一个 ATRI 关节 = HingeJoint + 电机 + 位置传感器 + 一段连杆。

    ``limit_deg``/``velocity_dps`` 原样来自 L1 模型：世界里的硬限位与电机
    ``maxVelocity`` 必须和模型一致，否则 Webots 会按默认"无限位 + 统一速度"跑。
    """
    return {
        "name": name,
        "axis": tuple(axis),
        "anchor": tuple(anchor),
        "size": tuple(size),
        "mass": mass,
        "limit_deg": tuple(limit_deg),
        "velocity_dps": float(velocity_dps),
        "inertia": inertia,
        "com": com,
        "children": list(children),
    }


# --------------------------------------------------------------------------
# 从 v2 URDF + profile 生成关节树
# --------------------------------------------------------------------------
_LINK_BOX_MM: Dict[str, List[float]] = {
    "pelvis": [40.0, 80.0, 32.0],
    "trunk_roll_link": [28.0, 40.0, 20.0],
    "torso": [55.0, 90.0, 80.0],
    "head_yaw_link": [25.0, 30.0, 20.0],
    "head": [40.0, 40.0, 45.0],
    "left_hip_roll_link": [30.0, 30.0, 30.0],
    "right_hip_roll_link": [30.0, 30.0, 30.0],
    "left_thigh": [25.0, 25.0, 78.0],
    "right_thigh": [25.0, 25.0, 78.0],
    "left_shank": [22.0, 22.0, 78.0],
    "right_shank": [22.0, 22.0, 78.0],
    "left_foot": [120.0, 70.0, 12.0],
    "right_foot": [120.0, 70.0, 12.0],
    "left_upper": [22.0, 22.0, 50.0],
    "right_upper": [22.0, 22.0, 50.0],
    "left_fore": [20.0, 20.0, 44.0],
    "right_fore": [20.0, 20.0, 44.0],
    "left_hand": [20.0, 20.0, 40.0],
    "right_hand": [20.0, 20.0, 40.0],
    "left_grip": [15.0, 20.0, 30.0],
    "right_grip": [15.0, 20.0, 30.0],
}


def load_model() -> Dict[str, Any]:
    """把 v2 URDF 收成旧生成器能吃的 robot_model 形字典。"""
    import xml.etree.ElementTree as ET

    if not URDF_PATH.exists():
        raise FileNotFoundError(f"缺少 v2 URDF: {URDF_PATH}")
    root = ET.parse(URDF_PATH).getroot()
    limits = {j["name"]: list(j["limit_deg"]) for j in v2_profile.JOINTS}

    links: List[Dict[str, Any]] = []
    for link in root.findall("link"):
        name = link.get("name") or ""
        mass_el = link.find("inertial/mass")
        mass = float(mass_el.get("value")) if mass_el is not None else 0.05
        inertia_el = link.find("inertial/inertia")
        inertia = None
        if inertia_el is not None:
            inertia = (
                float(inertia_el.get("ixx", 0)),
                float(inertia_el.get("iyy", 0)),
                float(inertia_el.get("izz", 0)),
                float(inertia_el.get("ixy", 0)),
                float(inertia_el.get("ixz", 0)),
                float(inertia_el.get("iyz", 0)),
            )
        origin_el = link.find("inertial/origin")
        com = (0.0, 0.0, 0.0)
        if origin_el is not None and origin_el.get("xyz"):
            parts = [float(v) for v in origin_el.get("xyz").split()]
            if len(parts) == 3:
                com = (parts[0], parts[1], parts[2])
        size = _LINK_BOX_MM.get(name, [30.0, 30.0, 30.0])
        links.append({
            "name": name,
            "mass_kg": mass,
            "inertia": inertia,
            "com": com,
            "geometry": {"type": "box", "size_mm": size},
        })

    joints: List[Dict[str, Any]] = []
    for idx, joint_el in enumerate(root.findall("joint")):
        if joint_el.get("type") != "revolute":
            continue
        name = joint_el.get("name") or ""
        origin = joint_el.find("origin")
        axis_el = joint_el.find("axis")
        limit_el = joint_el.find("limit")
        xyz_m = [float(v) for v in (origin.get("xyz") if origin is not None else "0 0 0").split()]
        axis = [float(v) for v in (axis_el.get("xyz") if axis_el is not None else "0 0 1").split()]
        vel_dps = math.degrees(float(limit_el.get("velocity"))) if limit_el is not None else 270.0
        if name not in limits:
            raise ValueError(f"URDF 关节 {name} 不在 v2 profile.JOINTS 里")
        joints.append({
            "id": idx,
            "name": name,
            "parent": joint_el.find("parent").get("link"),
            "child": joint_el.find("child").get("link"),
            "axis": axis,
            "origin_xyz_mm": [v * 1000.0 for v in xyz_m],
            "limit_deg": limits[name],
            "velocity_dps": vel_dps,
        })

    envelope = v2_profile.envelope_mm()
    return {
        "version": "v2-20dof",
        "base_pose_mm": [0.0, 0.0, 232.0],
        "overall": envelope,
        "links": links,
        "joints": joints,
    }


def _bbox_m(geom: Dict[str, Any]) -> List[float]:
    return [v / 1000.0 for v in geometry.bounding_box(geom)]


def robot_body(model: Dict[str, Any] | None = None):
    """(根 link 质量 kg, 根 link 包围盒 m, 根 link 离地高度 m, 根惯量, 根质心)。"""
    model = model or load_model()
    children_of = {j["child"] for j in model["joints"]}
    root = next(l for l in model["links"] if l["name"] not in children_of)
    com = root.get("com") or (0.0, 0.0, 0.0)
    return (
        float(root["mass_kg"]),
        _bbox_m(root["geometry"]),
        float(model["base_pose_mm"][2]) / 1000.0,
        root.get("inertia"),
        tuple(com),
    )


def robot_children(model: Dict[str, Any] | None = None) -> List[Dict[str, Any]]:
    """按 L1 模型生成关节树：根 link 的子关节 = 世界的顶层 HingeJoint。

    每个节点带：轴向、锚点（父 link 系，m）、连杆包围盒（m）、**该 link 的真实质量**。
    v2 起 link 质量已含舵机与电子件，所以这个世界与 URDF 同源。
    """
    model = model or load_model()
    by_parent: Dict[str, List[Dict[str, Any]]] = {}
    for j in sorted(model["joints"], key=lambda x: x["id"]):
        by_parent.setdefault(j["parent"], []).append(j)
    links = {l["name"]: l for l in model["links"]}
    children_of = {j["child"] for j in model["joints"]}
    root_name = next(l["name"] for l in model["links"] if l["name"] not in children_of)

    def node(j: Dict[str, Any]) -> Dict[str, Any]:
        child = links[j["child"]]
        return joint(
            j["name"],
            axis=j["axis"],
            anchor=[v / 1000.0 for v in j["origin_xyz_mm"]],
            size=_bbox_m(child["geometry"]),
            mass=float(child["mass_kg"]),
            limit_deg=j["limit_deg"],
            velocity_dps=float(j["velocity_dps"]),
            inertia=child.get("inertia"),
            com=child.get("com"),
            children=[node(k) for k in by_parent.get(j["child"], [])],
        )

    return [node(j) for j in by_parent.get(root_name, [])]


def joint_names() -> List[str]:
    """按生成顺序列出 20 个关节名（含断电自检用）。"""
    names: List[str] = []

    def walk(node: Dict[str, Any]) -> None:
        names.append(node["name"])
        for child in node["children"]:
            walk(child)

    for node in robot_children():
        walk(node)
    return names


def left_foot_chain_z_m(model: Dict[str, Any] | None = None) -> float:
    """骨盆原点到左踝原点的 z（m，URDF 零位，负值）。"""
    model = model or load_model()
    by_name = {j["name"]: j for j in model["joints"]}
    return sum(
        by_name[name]["origin_xyz_mm"][2] / 1000.0
        for name in (
            "left_hip_roll",
            "left_hip_pitch",
            "left_knee_pitch",
            "left_ankle_pitch",
        )
    )


def ankle_to_sole_m() -> float:
    """踝原点到 TPU 底的距离（m）。CAD ``foot_to_ankle_z``，不是 12 mm 脚盒半高。"""
    return float(v2_profile.K["foot_to_ankle_z"]) / 1000.0


def gravity_foot_box_m() -> Tuple[float, float, float]:
    """CAD/URDF 脚：120×70×44 mm，不是 12 mm 薄盒。"""
    return (
        float(v2_profile.K["foot_l"]) / 1000.0,
        float(v2_profile.K["foot_w"]) / 1000.0,
        ankle_to_sole_m(),
    )


def gravity_foot_box_offset_z_m() -> float:
    """盒心在踝下方半高，盒底落在鞋底。"""
    return -ankle_to_sole_m() / 2.0


def render_physics(
    pad: str,
    mass: float,
    inertia: Optional[Tuple[float, float, float, float, float, float]],
    gravity: float,
    com: Optional[Sequence[float]] = None,
) -> List[str]:
    lines = [
        f"{pad}    physics Physics {{",
        f"{pad}      density -1",
        f"{pad}      mass {num(mass)}",
    ]
    if gravity != 0.0 and inertia is not None:
        ixx, iyy, izz, ixy, ixz, iyz = inertia
        cx, cy, cz = (0.0, 0.0, 0.0) if com is None else (float(com[0]), float(com[1]), float(com[2]))
        lines += [
            f"{pad}      centerOfMass [",
            f"{pad}        {vec((cx, cy, cz))}",
            f"{pad}      ]",
            f"{pad}      inertiaMatrix [",
            f"{pad}        {num_inertia(ixx)} {num_inertia(iyy)} {num_inertia(izz)}",
            f"{pad}        {num_inertia(ixy)} {num_inertia(ixz)} {num_inertia(iyz)}",
            f"{pad}      ]",
        ]
    lines.append(f"{pad}    }}")
    return lines


def render_joint(
    node: Dict[str, Any],
    indent: int,
    max_torque: Optional[float] = None,
    gravity: float = 0.0,
    damping: float = JOINT_DAMPING,
) -> List[str]:
    """渲染一个关节子树（HingeJoint + 电机 + 位置传感器 + 连杆 Solid）。

    ``max_torque`` 为 ``None`` 时不写 ``maxTorque`` 字段（= 现有世界的行为，
    Webots 按默认 10 N·m 处理）；给了值就**逐电机**写同一份上限——
    20 个电机漏写任何一个，那个关节的扭矩权限就还是 10 N·m，结论不可用。
    """
    pad = "  " * indent
    lo, hi = node["limit_deg"]
    motor = [
        f"{pad}    RotationalMotor {{",
        f'{pad}      name "{node["name"]}"',
        f"{pad}      maxVelocity {num(math.radians(node['velocity_dps']))}",
    ]
    if max_torque is not None:
        motor.append(f"{pad}      maxTorque {num(max_torque)}")
    motor.append(f"{pad}    }}")
    lines = [
        f"{pad}HingeJoint {{",
        f"{pad}  jointParameters HingeJointParameters {{",
        f"{pad}    axis {vec(node['axis'])}",
        f"{pad}    anchor {vec(node['anchor'])}",
        # Webots 不写 minStop/maxStop 就是无限位，控制器钳制再严也只是软件层
        f"{pad}    minStop {num(math.radians(lo))}",
        f"{pad}    maxStop {num(math.radians(hi))}",
        # 不写阻尼这一行，世界会在启动瞬间把若干关节弹飞（见 JOINT_DAMPING 注释）
        f"{pad}    dampingConstant {num(damping)}",
        f"{pad}  }}",
        f"{pad}  device [",
        *motor,
        f"{pad}    PositionSensor {{",
        f'{pad}      name "{node["name"]}_sensor"',
        f"{pad}    }}",
        f"{pad}  ]",
        f"{pad}  endPoint Solid {{",
        # urdf2webots：子 Solid 放到关节原点。脚 Solid 必须在踝，惯量才和 URDF 一致。
        f"{pad}    translation {vec(node['anchor'])}",
        f'{pad}    name "{node["name"]}_link"',
    ]
    if gravity != 0.0:
        contact = v2_profile.CONTACT
        mat = (
            contact["foot_material"]
            if "ankle_pitch" in node["name"]
            else contact["other_material"]
        )
        lines.append(f'{pad}    contactMaterial "{mat}"')
    mass = float(node["mass"])
    if gravity == 0.0:
        lines += [
            f"{pad}    boundingObject Box {{",
            f"{pad}      size {vec(node['size'])}",
            f"{pad}    }}",
        ]
    elif "ankle_pitch" in node["name"]:
        lx, ly, lz = gravity_foot_box_m()
        dz = gravity_foot_box_offset_z_m()
        lines += [
            f"{pad}    boundingObject Pose {{",
            f"{pad}      translation 0 0 {num(dz)}",
            f"{pad}      children [",
            f"{pad}        Box {{",
            f"{pad}          size {num(lx)} {num(ly)} {num(lz)}",
            f"{pad}        }}",
            f"{pad}      ]",
            f"{pad}    }}",
        ]
    else:
        # 碰撞用小球避免大腿 AABB 戳地；惯量仍写 URDF 盒，不用球。
        lines += [
            f"{pad}    boundingObject Sphere {{",
            f"{pad}      radius 0.008",
            f"{pad}    }}",
        ]
    lines += render_physics(pad, mass, node.get("inertia"), gravity, node.get("com"))
    visual: List[str] = []
    if gravity != 0.0:
        # 碰撞仍用脚盒 + 其它小球；画面要用完整连杆盒，否则录屏里机器人是隐形的。
        visual = [
            f"{pad}    Shape {{",
            f"{pad}      appearance Appearance {{",
            f"{pad}        material Material {{",
            f"{pad}          diffuseColor 0.18 0.42 0.86",
            f"{pad}        }}",
            f"{pad}      }}",
            f"{pad}      geometry Box {{",
            f"{pad}        size {vec(node['size'])}",
            f"{pad}      }}",
            f"{pad}    }}",
        ]
    nested: List[str] = []
    for child in node["children"]:
        nested.extend(
            render_joint(child, indent + 3, max_torque, gravity=gravity, damping=damping)
        )
    if visual or nested:
        lines.append(f"{pad}    children [")
        lines.extend(visual)
        lines.extend(nested)
        lines.append(f"{pad}    ]")
    lines.append(f"{pad}  }}")
    lines.append(f"{pad}}}")
    return lines


def render_ground() -> List[str]:
    """地面：静态 ``Box``，顶面在 z = 0（脚底所在平面）。

    不用 ``Floor`` PROTO（要 ``EXTERNPROTO``）。不用 ``Plane``：ODE 无限平面
    对薄脚盒的切向摩擦经常不生效，μ=0.7 和 μ=8 都会滑。
    """
    z = -GROUND_THICKNESS / 2.0
    size = f"{num(GROUND_SIZE)} {num(GROUND_SIZE)} {num(GROUND_THICKNESS)}"
    return [
        "Solid {",
        '  name "ground"',
        f"  translation 0 0 {num(z)}",
        "  children [",
        "    Shape {",
        "      appearance Appearance {",
        "        material Material {",
        "          diffuseColor 0.86 0.82 0.74",
        "        }",
        "      }",
        "      geometry Box {",
        f"        size {size}",
        "      }",
        "    }",
        "  ]",
        "  boundingObject Box {",
        f"    size {size}",
        "  }",
        f'  contactMaterial "{v2_profile.CONTACT["ground_material"]}"',
        "}",
    ]


def render_provenance(
    gravity: float, max_torque: Optional[float], ground: bool
) -> List[str]:
    """非默认参数时往文件头补一段"参数来源"注释；默认组合返回空（保证逐字节一致）。

    这一段是给队友和评审看的：世界文件本身就能回答"gravity / maxTorque 各是多少"，
    不用再去翻生成时的命令（清单 §0.3 要求报告里写清这三个值）。
    """
    if gravity == DEFAULT_GRAVITY and max_torque is None and not ground:
        return []
    torque_text = (
        "不写该字段（Webots 默认 10 N·m，**扭矩结论不可用**）"
        if max_torque is None
        else f"{num(max_torque)} N·m（STS3215 堵转 2.94 N·m）"
    )
    ground_text = (
        f"有：Box，{num(GROUND_SIZE)} m × {num(GROUND_SIZE)} m × {num(GROUND_THICKNESS)} m，顶面 z = 0"
        if ground
        else "无"
    )
    return [
        "#",
        "# ⚠ 本世界用非默认参数生成，只用于**仿真校核**，里面的数字是仿真值不是实测值：",
        f"#   gravity   = {num(gravity)} m/s²"
        + ("（零重力：运动学联调）" if gravity == 0.0 else ""),
        f"#   maxTorque = {torque_text}",
        f"#   ground    = {ground_text}",
        "#   生成命令：见 webots/README.md「带重力/带地面的校核跑法」。",
    ]


def render_world(
    gravity: float = DEFAULT_GRAVITY,
    max_torque: Optional[float] = DEFAULT_MAX_TORQUE,
    ground: bool = DEFAULT_GROUND,
) -> str:
    """渲染世界文件文本。

    默认参数（``0.0`` / ``None`` / ``False``）= 与提交在仓库里的
    ``worlds/atri_v2.wbt`` **逐字节一致**，CI 就是拿这条对账的。
    """
    if gravity != 0.0 and not ground:
        # 硬约束：有重力没地面 = 自由落体，静立/站立数字全部作废
        raise ValueError("重力非 0 必须同时生成地面，否则机器人自由落体")
    _body = robot_body()
    spawn_z = float(_body[2])
    damping = JOINT_DAMPING
    if gravity != 0.0:
        if max_torque is None:
            max_torque = float(v2_profile.SERVO["stall_nm"])
        spawn_z = pelvis_spawn_z_m(
            chain_z_m=left_foot_chain_z_m(),
            foot_half_z_m=ankle_to_sole_m(),
            clearance_m=0.008,
        )
        damping = GRAVITY_JOINT_DAMPING
    title = (
        "A.T.R.I. 20 DOF 桌面人形（带重力校核）"
        if gravity != 0.0
        else "A.T.R.I. 20 DOF 桌面人形（运动学联调）"
    )
    lines = [
        f"#VRML_SIM {WORLD_VERSION} utf8",
        "",
        "# 本文件由 webots/tools/generate_atri_world.py 生成，请勿手改。",
        "# A.T.R.I. 20 DOF 桌面人形：限位来自 design/v2/profile.py，树来自 atri_v2.urdf。",
        "# 关节限位与电机速度上限同样来自模型（minStop/maxStop/maxVelocity）。",
        "# 电机名与 controllers/atri_controller/joint_mapping.json 一一对应（默认同名映射）。",
    ]
    lines += render_provenance(gravity, max_torque, ground)
    lines += [
        "",
        "WorldInfo {",
        f'  title "{title}"',
        f"  basicTimeStep {GRAVITY_TIME_STEP if gravity != 0.0 else BASIC_TIME_STEP}",
        f"  gravity {num(gravity)}",
        f"  ERP {'0.2' if gravity != 0.0 else '0.6'}",
        "  CFM 1e-05",
    ]
    if gravity != 0.0:
        contact = v2_profile.CONTACT
        # ENU：Z 向上。μ 来自 profile.CONTACT（TPU95A 鞋底 × 室内塑胶地板）。
        lines += [
            '  coordinateSystem "ENU"',
            '  gpsCoordinateSystem "local"',
            "  contactProperties [",
            "    ContactProperties {",
            f'      material1 "{contact["foot_material"]}"',
            f'      material2 "{contact["ground_material"]}"',
            f'      coulombFriction {num(contact["mu_foot_ground"])}',
            f'      bounce {num(contact["bounce"])}',
            "      softCFM 1e-5",
            '      bumpSound ""',
            '      rollSound ""',
            '      slideSound ""',
            "    }",
            "    ContactProperties {",
            f'      material1 "{contact["other_material"]}"',
            f'      material2 "{contact["ground_material"]}"',
            f'      coulombFriction {num(contact["mu_other_ground"])}',
            f'      bounce {num(contact["bounce"])}',
            "      softCFM 1e-5",
            '      bumpSound ""',
            '      rollSound ""',
            '      slideSound ""',
            "    }",
            "  ]",
        ]
    lines += [
        "}",
        "",
        "Viewpoint {",
    ]
    if gravity != 0.0:
        lines += [
            "  orientation -0.1567 0.8935 0.4214 1.1077",
            "  position 0.45 -0.55 0.28",
            '  follow "ATRI"',
            '  followType "None"',
        ]
    else:
        lines += [
            "  orientation -0.1567 0.8935 0.4214 1.1077",
            "  position 0.62 -0.72 0.66",
            '  followType "None"',
        ]
    lines += [
        "}",
        "",
    ]
    if gravity != 0.0:
        lines += [
            "Background {",
            "  skyColor [ 0.62 0.72 0.88 ]",
            "}",
            "DirectionalLight {",
            "  ambientIntensity 0.8",
            "  direction 0.4 -0.6 -1",
            "  intensity 2",
            "  castShadows FALSE",
            "}",
            "",
        ]
    if ground:
        # 地面放在 Viewpoint 之后、Robot 之前：与 Webots 样例世界的习惯顺序一致
        lines += [""] + render_ground()
    lines += [
        "",
        "Robot {",
        '  name "ATRI"',
        '  controller "atri_controller"',
    ]
    if gravity != 0.0:
        # Supervisor 才能 movieStartRecording；默认零重力世界不加，CI 对账不变。
        lines.append("  supervisor TRUE")
        lines.append(f'  contactMaterial "{v2_profile.CONTACT["other_material"]}"')
    lines.append(f"  translation 0 0 {num(spawn_z)}")
    if gravity == 0.0:
        lines += [
            "  boundingObject Box {",
            f"    size {vec(_body[1])}",
            "  }",
        ]
    else:
        lines += [
            "  boundingObject Sphere {",
            "    radius 0.008",
            "  }",
        ]
    physics_lines = [
        "  physics Physics {",
        "    density -1",
        f"    mass {num(_body[0])}",
    ]
    if gravity != 0.0 and _body[3] is not None:
        ixx, iyy, izz, ixy, ixz, iyz = _body[3]
        com = _body[4] if len(_body) > 4 and _body[4] is not None else (0.0, 0.0, 0.0)
        physics_lines += [
            "    centerOfMass [",
            f"      {vec(com)}",
            "    ]",
            "    inertiaMatrix [",
            f"      {num_inertia(ixx)} {num_inertia(iyy)} {num_inertia(izz)}",
            f"      {num_inertia(ixy)} {num_inertia(ixz)} {num_inertia(iyz)}",
            "    ]",
        ]
    physics_lines.append("  }")
    lines += physics_lines
    lines += [
        "  children [",
    ]
    if gravity != 0.0:
        lines += [
            "    GPS {",
            '      name "pelvis_gps"',
            "    }",
            "    InertialUnit {",
            '      name "imu"',
            "    }",
            "    Shape {",
            "      appearance Appearance {",
            "        material Material {",
            "          diffuseColor 0.86 0.28 0.18",
            "        }",
            "      }",
            "      geometry Box {",
            f"        size {vec(_body[1])}",
            "      }",
            "    }",
            # 骨盆正上方往下看（相机默认朝 -Z）。用来确认 Robot 连杆会不会进画面。

        ]
    for node in robot_children():
        lines.extend(
            render_joint(node, 2, max_torque, gravity=gravity, damping=damping)
        )
    lines += [
        "  ]",
        "}",
        "",
    ]
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    try:
        opts = resolve_options(args)
    except ValueError as exc:
        # 参数错误必须让生成失败：悄悄退回默认会生成一个"看起来正常"的零重力世界，
        # 而队友会拿它去跑 S1/S2——那正是本次改动要消灭的坑。
        print(f"  [生成器] 参数错误：{exc}", file=sys.stderr)
        return 2

    model = load_model()
    names = joint_names()
    assert len(names) == 20, f"关节数应为 20，实际 {len(names)}"
    assert len(set(names)) == 20, "关节名重复"
    assert set(names) == {j["name"] for j in model["joints"]}, \
        "世界关节名与 v2 URDF 不一致"
    assert "left_hip_yaw" not in names and "right_hip_yaw" not in names
    print(f"  模型 v{model.get('version')}，整机 "
          f"{sum(l['mass_kg'] for l in model['links']):.3f} kg，"
          f"包络 {model['overall']['height_mm']:.1f}×{model['overall']['width_mm']:.1f}"
          f"×{model['overall']['depth_mm']:.1f} mm")

    if not opts.is_default:
        if opts.max_torque is not None:
            torque_text = f"{num(opts.max_torque)} N·m × 20"
        elif opts.gravity != 0.0:
            torque_text = f"{num(v2_profile.SERVO['stall_nm'])} N·m × 20（STS3215 堵转）"
        else:
            torque_text = "不写字段（Webots 默认 10 N·m）"
        ground_text = (
            f"有（Box {num(GROUND_SIZE)}×{num(GROUND_SIZE)}×{num(GROUND_THICKNESS)} m）" if opts.ground else "无"
        )
        print(f"  [生成器] 非默认参数：gravity={num(opts.gravity)} m/s²，"
              f"maxTorque={torque_text}，地面={ground_text}")
        if opts.ground_auto:
            print("  [生成器] 重力非 0 → 自动生成地面（无地面 = 自由落体，静立/站立数字全废）")

    opts.out.parent.mkdir(parents=True, exist_ok=True)
    # 显式 newline="\n"：Windows 上默认会把 \n 翻成 \r\n，破坏与 CI 的字节比对。
    # 这里用 open() 而不是 Path.write_text(newline=...)：后者 3.10 才支持，
    # 本机系统 Python 3.9.6 会直接 TypeError（旧版代码就是这么在本机跑不起来的）。
    text = render_world(opts.gravity, opts.max_torque, opts.ground)
    with open(opts.out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    print(f"已生成 {opts.out}")
    print(f"关节数 {len(names)}: {', '.join(names)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
