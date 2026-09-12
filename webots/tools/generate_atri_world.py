"""生成 A.T.R.I. 22 DOF 的 Webots 世界文件。

为什么要生成而不是手写：22 个关节 × (HingeJoint + RotationalMotor + PositionSensor
+ endPoint Solid) 手写近千行且极易写错；用脚本生成，改尺寸/改关节只需改这里的表。

为什么自包含、不用 ``EXTERNPROTO``：本机（以及比赛机器的网络）访问 GitHub 受限，
世界文件一旦依赖外部 PROTO 就可能打不开。这里全部用 Webots 内置节点
（``Robot`` / ``HingeJoint`` / ``RotationalMotor`` / ``PositionSensor`` / ``Solid`` /
``Box``，带地面时再加 ``Plane``——不加地面就不用）。

电机名与 ``controllers/atri_controller/joint_mapping.json`` 完全一致（默认同名映射），
所以 22 个关节全部能绑定上，联调跑的就是全关节。关节硬限位（``minStop``/``maxStop``）
与电机 ``maxVelocity`` 也逐关节取自 ``design/robot_model.json`` 的
``limit_deg`` / ``velocity_dps``，世界与模型不再各写一套。

用法::

    python webots/tools/generate_atri_world.py        # 默认：零重力运动学联调世界

    # 带重力校核世界（S1 静立 / S2 站立扭矩用）：
    ATRI_WORLD_GRAVITY=-9.81 ATRI_WORLD_MAX_TORQUE=2.94 ATRI_WORLD_GROUND=1 \\
        python webots/tools/generate_atri_world.py --out /tmp/atri_grav.wbt

四个可选覆盖（同名命令行参数优先于环境变量；两者都不给 = 现在的默认行为）：

* ``ATRI_WORLD_GRAVITY`` / ``--gravity``：``WorldInfo.gravity``，默认 ``0.0``（零重力）。
  Webots 里它是**有符号标量**（沿 Z 轴）：向下为负（``-9.81``），给正值等于让机器人往上飞，
  所以正数直接报错退出。
* ``ATRI_WORLD_MAX_TORQUE`` / ``--max-torque``：逐电机 ``maxTorque``（N·m），默认**不写该字段**。
  注意"不写"≠无限大：Webots 默认 **10 N·m**，是 STS3215 堵转 2.94 N·m 的 3.4 倍，
  做扭矩校核时必须显式设成 2.94，否则结论作废。
* ``ATRI_WORLD_GROUND`` / ``--ground``：生成 ``Plane`` 地面（4 m × 4 m，理由见 ``GROUND_SIZE``），
  默认不生成。**重力非 0 时自动强制打开**——有重力没地面就是自由落体，跑出来的数字全是废的。
* ``--out <path>``：输出到别的路径（例如 ``docs/process/sim/worlds/`` 下的临时副本），
  默认仍是 ``webots/worlds/atri_22dof.wbt``。

**不带任何开关跑出来的世界与提交在仓库里的 ``worlds/atri_22dof.wbt`` 逐字节一致**，
CI 就是靠这条对账的（``git diff --exit-code``）。
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Sequence

WORLD_PATH = Path(__file__).resolve().parents[1] / "worlds" / "atri_22dof.wbt"

# L1 单一事实来源：几何/质量/关节全部从 design/robot_model.json 派生（v2 起）。
# 以前这里的关节链是**手写常量**，结果长期与模型不一致（腿段 190 mm vs 模型 235 mm、
# roll/pitch 轴向对调），而 CI 只比"生成器↔产物"，查不出这种漂移。现在改读模型。
REPO = Path(__file__).resolve().parents[2]
MODEL_PATH = REPO / "design" / "robot_model.json"
sys.path.insert(0, str(REPO / "design"))
import geometry  # noqa: E402  （纯标准库）

# 世界标称版本：与本机验证用的 Webots R2025a 对齐（工程说明要求 R2023b 或更新）
WORLD_VERSION = "R2025a"
BASIC_TIME_STEP = 32

# --------------------------------------------------------------------------
# 默认值：必须与提交在仓库里的 worlds/atri_22dof.wbt 逐字节一致
# --------------------------------------------------------------------------
# 重力置零：这是"运动学联调"世界，验证的是 22 个关节角是否被正确下发与跟随，
# 不是双足平衡。零重力下机器人不会倒地，关节可以自由摆动，轨迹看得最清楚。
#
# 注意：Webots R2025a 里 WorldInfo.gravity 是 **SFFloat**（沿"下"轴的大小），
# 不是 SFVec3f。写成 `gravity 0 0 0` 会让世界文件解析失败，
# Webots 会静默回退到内置 empty.wbt——控制器一个都不会启动。
# 它同时是**有符号标量**：默认 -9.81 指向 Z 轴负方向（向下），正值等于让机器人往上飞。
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
# 用 Plane 做接触面（Webots 里按无限平面处理）：机器人即使被推出去也不会掉出世界边界；
# 退一步说，即便某版本按有限矩形处理，4 m 也远超上述活动范围。
GROUND_SIZE = 4.0

_TRUE_WORDS = {"1", "true", "yes", "on", "y"}
_FALSE_WORDS = {"0", "false", "no", "off", "n", ""}

# 关节阻尼（HingeJointParameters.dampingConstant，单位 N·m·s/rad）。
#
# 必须显式写、且必须 > 0：Webots 不给关节写阻尼时，这个"零重力 + 22 个轻质连杆"
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
        description="生成 A.T.R.I. 22 DOF 的 Webots 世界文件（默认：零重力运动学联调世界）"
    )
    parser.add_argument(
        "--out", default=None, help="输出路径（默认 webots/worlds/atri_22dof.wbt）"
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
    if gravity > 0:
        raise ValueError(
            f"gravity 必须 ≤ 0，实际 {gravity}：Webots 的 gravity 是沿 Z 轴的有符号标量，"
            "正值向上，机器人会飞起来"
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
        "children": list(children),
    }


# --------------------------------------------------------------------------
# 从 L1 模型生成关节树
# --------------------------------------------------------------------------
def load_model() -> Dict[str, Any]:
    return json.loads(MODEL_PATH.read_text(encoding="utf-8"))


def _bbox_m(geom: Dict[str, Any]) -> List[float]:
    return [v / 1000.0 for v in geometry.bounding_box(geom)]


def robot_body(model: Dict[str, Any] | None = None):
    """(根 link 质量 kg, 根 link 包围盒 m, 根 link 离地高度 m)。"""
    model = model or load_model()
    children_of = {j["child"] for j in model["joints"]}
    root = next(l for l in model["links"] if l["name"] not in children_of)
    return (float(root["mass_kg"]), _bbox_m(root["geometry"]),
            float(model["base_pose_mm"][2]) / 1000.0)


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
            children=[node(k) for k in by_parent.get(j["child"], [])],
        )

    return [node(j) for j in by_parent.get(root_name, [])]


def joint_names() -> List[str]:
    """按生成顺序列出 22 个关节名（含断电自检用）。"""
    names: List[str] = []

    def walk(node: Dict[str, Any]) -> None:
        names.append(node["name"])
        for child in node["children"]:
            walk(child)

    for node in robot_children():
        walk(node)
    return names


def render_joint(node: Dict[str, Any], indent: int, max_torque: Optional[float] = None) -> List[str]:
    """渲染一个关节子树（HingeJoint + 电机 + 位置传感器 + 连杆 Solid）。

    ``max_torque`` 为 ``None`` 时不写 ``maxTorque`` 字段（= 现有世界的行为，
    Webots 按默认 10 N·m 处理）；给了值就**逐电机**写同一份上限——
    22 个电机漏写任何一个，那个关节的扭矩权限就还是 10 N·m，结论不可用。
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
        f"{pad}    dampingConstant {num(JOINT_DAMPING)}",
        f"{pad}  }}",
        f"{pad}  device [",
        *motor,
        f"{pad}    PositionSensor {{",
        f'{pad}      name "{node["name"]}_sensor"',
        f"{pad}    }}",
        f"{pad}  ]",
        f"{pad}  endPoint Solid {{",
        f'{pad}    name "{node["name"]}_link"',
        f"{pad}    boundingObject Box {{",
        f"{pad}      size {vec(node['size'])}",
        f"{pad}    }}",
        f"{pad}    physics Physics {{",
        f"{pad}      density -1",
        f"{pad}      mass {num(node['mass'])}",
        f"{pad}    }}",
    ]
    if node["children"]:
        lines.append(f"{pad}    children [")
        for child in node["children"]:
            lines.extend(render_joint(child, indent + 3, max_torque))
        lines.append(f"{pad}    ]")
    lines.append(f"{pad}  }}")
    lines.append(f"{pad}}}")
    return lines


def render_ground() -> List[str]:
    """地面：``Solid`` + ``Plane``，落在 z = 0（脚底所在平面）。

    为什么不用 ``Floor``：``Floor`` / ``Ground`` 都是 Webots 的 **PROTO**，
    引用时必须配 ``EXTERNPROTO``，会破坏本世界"自包含、不引外部 PROTO"这条
    刻意保留的约束（见模块 docstring）。``Plane`` 是内置几何节点，两种场合都能用。
    """
    return [
        "Solid {",
        '  name "ground"',
        "  translation 0 0 0",
        "  children [",
        "    Shape {",
        "      appearance Appearance {",
        "        baseColor 0.5 0.5 0.55",
        "      }",
        "      geometry Plane {",
        f"        size {num(GROUND_SIZE)} {num(GROUND_SIZE)}",
        "      }",
        "    }",
        "  ]",
        "  boundingObject Plane {",
        f"    size {num(GROUND_SIZE)} {num(GROUND_SIZE)}",
        "  }",
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
        f"有：Plane，{num(GROUND_SIZE)} m × {num(GROUND_SIZE)} m，z = 0"
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
    ``worlds/atri_22dof.wbt`` **逐字节一致**，CI 就是拿这条对账的。
    """
    if gravity != 0.0 and not ground:
        # 硬约束：有重力没地面 = 自由落体，静立/站立数字全部作废
        raise ValueError("重力非 0 必须同时生成地面，否则机器人自由落体")
    _body = robot_body()
    title = (
        "A.T.R.I. 22 DOF 桌面人形（带重力校核）"
        if gravity != 0.0
        else "A.T.R.I. 22 DOF 桌面人形（运动学联调）"
    )
    lines = [
        f"#VRML_SIM {WORLD_VERSION} utf8",
        "",
        "# 本文件由 webots/tools/generate_atri_world.py 生成，请勿手改。",
        "# A.T.R.I. 22 DOF 桌面人形：几何与质量派生自 design/robot_model.json。",
        "# 关节限位与电机速度上限同样来自模型（minStop/maxStop/maxVelocity）。",
        "# 电机名与 controllers/atri_controller/joint_mapping.json 一一对应（默认同名映射）。",
    ]
    lines += render_provenance(gravity, max_torque, ground)
    lines += [
        "",
        "WorldInfo {",
        f'  title "{title}"',
        f"  basicTimeStep {BASIC_TIME_STEP}",
        f"  gravity {num(gravity)}",
        "  ERP 0.6",
        "  CFM 1e-05",
        "}",
        "",
        "Viewpoint {",
        "  orientation -0.1567 0.8935 0.4214 1.1077",
        "  position 0.62 -0.72 0.66",
        "  followType \"None\"",
        "}",
    ]
    if ground:
        # 地面放在 Viewpoint 之后、Robot 之前：与 Webots 样例世界的习惯顺序一致
        lines += [""] + render_ground()
    lines += [
        "",
        "Robot {",
        '  name "ATRI"',
        '  controller "atri_controller"',
        f"  translation 0 0 {num(_body[2])}",
        "  boundingObject Box {",
        f"    size {vec(_body[1])}",
        "  }",
        "  physics Physics {",
        "    density -1",
        f"    mass {num(_body[0])}",
        "  }",
        "  children [",
    ]
    for node in robot_children():
        lines.extend(render_joint(node, 2, max_torque))
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
    assert len(names) == 22, f"关节数应为 22，实际 {len(names)}"
    assert len(set(names)) == 22, "关节名重复"
    assert set(names) == {j["name"] for j in model["joints"]}, \
        "世界关节名与 robot_model.json 不一致"
    print(f"  模型 v{model.get('version')}，整机 "
          f"{sum(l['mass_kg'] for l in model['links']):.3f} kg，"
          f"包络 {model['overall']['height_mm']:.1f}×{model['overall']['width_mm']:.1f}"
          f"×{model['overall']['depth_mm']:.1f} mm")

    if not opts.is_default:
        torque_text = (
            "不写字段（Webots 默认 10 N·m）"
            if opts.max_torque is None
            else f"{num(opts.max_torque)} N·m × 22"
        )
        ground_text = (
            f"有（Plane {num(GROUND_SIZE)}×{num(GROUND_SIZE)} m）" if opts.ground else "无"
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
