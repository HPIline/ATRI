"""生成 A.T.R.I. 22 DOF 的 Webots 世界文件。

为什么要生成而不是手写：22 个关节 × (HingeJoint + RotationalMotor + PositionSensor
+ endPoint Solid) 手写近千行且极易写错；用脚本生成，改尺寸/改关节只需改这里的表。

为什么自包含、不用 ``EXTERNPROTO``：本机（以及比赛机器的网络）访问 GitHub 受限，
世界文件一旦依赖外部 PROTO 就可能打不开。这里全部用 Webots 内置节点
（``Robot`` / ``HingeJoint`` / ``RotationalMotor`` / ``PositionSensor`` / ``Solid`` / ``Box``）。

电机名与 ``controllers/atri_controller/joint_mapping.json`` 完全一致（默认同名映射），
所以 22 个关节全部能绑定上，联调跑的就是全关节。

用法::

    python webots/tools/generate_atri_world.py
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Sequence

WORLD_PATH = Path(__file__).resolve().parents[1] / "worlds" / "atri_22dof.wbt"

# 世界标称版本：与本机验证用的 Webots R2025a 对齐（工程说明要求 R2023b 或更新）
WORLD_VERSION = "R2025a"
BASIC_TIME_STEP = 32

# 关节最大角速度（rad/s），与控制器默认值保持一致
MOTOR_MAX_VELOCITY = 2.0

# 重力置零：这是"运动学联调"世界，验证的是 22 个关节角是否被正确下发与跟随，
# 不是双足平衡。零重力下机器人不会倒地，关节可以自由摆动，轨迹看得最清楚。
#
# 注意：Webots R2025a 里 WorldInfo.gravity 是 **SFFloat**（沿"下"轴的大小），
# 不是 SFVec3f。写成 `gravity 0 0 0` 会让世界文件解析失败，
# Webots 会静默回退到内置 empty.wbt——控制器一个都不会启动。
GRAVITY = 0.0


def num(value: float) -> str:
    """把数字格式化成 WBT 里好看的形式。"""
    if float(value) == int(value):
        return str(int(value))
    return f"{float(value):.4f}".rstrip("0").rstrip(".")


def vec(values: Sequence[float]) -> str:
    return " ".join(num(v) for v in values)


def joint(
    name: str,
    axis: Sequence[float],
    anchor: Sequence[float],
    size: Sequence[float],
    mass: float = 0.15,
    children: Sequence[Dict[str, Any]] = (),
) -> Dict[str, Any]:
    """一个 ATRI 关节 = HingeJoint + 电机 + 位置传感器 + 一段连杆。"""
    return {
        "name": name,
        "axis": tuple(axis),
        "anchor": tuple(anchor),
        "size": tuple(size),
        "mass": mass,
        "children": list(children),
    }


# --------------------------------------------------------------------------
# 头部链：torso -> head_yaw -> head_pitch -> 头
# --------------------------------------------------------------------------
def head_chain() -> Dict[str, Any]:
    return joint(
        "head_yaw",
        axis=(0, 0, 1),
        anchor=(0, 0, 0.05),
        size=(0.05, 0.05, 0.04),
        mass=0.06,
        children=[
            joint(
                "head_pitch",
                axis=(1, 0, 0),
                anchor=(0, 0, 0.02),
                size=(0.10, 0.09, 0.09),
                mass=0.18,
            )
        ],
    )


# --------------------------------------------------------------------------
# 手臂链：torso -> shoulder_pitch -> shoulder_roll -> elbow_pitch -> gripper
# --------------------------------------------------------------------------
def arm_chain(side: str) -> Dict[str, Any]:
    sign = -1.0 if side == "left" else 1.0
    shoulder_x = sign * 0.085
    return joint(
        f"{side}_shoulder_pitch",
        axis=(1, 0, 0),
        anchor=(shoulder_x, 0, 0.03),
        size=(0.04, 0.04, 0.09),
        mass=0.10,
        children=[
            joint(
                f"{side}_shoulder_roll",
                axis=(0, 1, 0),
                anchor=(0, 0, -0.045),
                size=(0.035, 0.035, 0.09),
                mass=0.08,
                children=[
                    joint(
                        f"{side}_elbow_pitch",
                        axis=(1, 0, 0),
                        anchor=(0, 0, -0.045),
                        size=(0.03, 0.03, 0.08),
                        mass=0.07,
                        children=[
                            joint(
                                f"{side}_gripper",
                                axis=(0, 0, 1),
                                anchor=(0, 0, -0.04),
                                size=(0.04, 0.02, 0.05),
                                mass=0.04,
                            )
                        ],
                    )
                ],
            )
        ],
    )


# --------------------------------------------------------------------------
# 腿链：pelvis -> hip_yaw -> hip_roll -> hip_pitch -> knee_pitch -> ankle_pitch
# --------------------------------------------------------------------------
def leg_chain(side: str) -> Dict[str, Any]:
    sign = -1.0 if side == "left" else 1.0
    hip_x = sign * 0.045
    return joint(
        f"{side}_hip_yaw",
        axis=(0, 0, 1),
        anchor=(hip_x, 0, -0.04),
        size=(0.05, 0.05, 0.05),
        mass=0.12,
        children=[
            joint(
                f"{side}_hip_roll",
                axis=(0, 1, 0),
                anchor=(0, 0, -0.025),
                size=(0.045, 0.045, 0.05),
                mass=0.12,
                children=[
                    joint(
                        f"{side}_hip_pitch",
                        axis=(1, 0, 0),
                        anchor=(0, 0, -0.025),
                        size=(0.045, 0.05, 0.10),
                        mass=0.20,
                        children=[
                            joint(
                                f"{side}_knee_pitch",
                                axis=(1, 0, 0),
                                anchor=(0, 0, -0.05),
                                size=(0.04, 0.045, 0.10),
                                mass=0.18,
                                children=[
                                    joint(
                                        f"{side}_ankle_pitch",
                                        axis=(1, 0, 0),
                                        anchor=(0, 0, -0.05),
                                        size=(0.05, 0.10, 0.025),
                                        mass=0.10,
                                    )
                                ],
                            )
                        ],
                    )
                ],
            )
        ],
    )


def robot_children() -> List[Dict[str, Any]]:
    """躯干 2 + 头 2 + 双臂 8 + 双腿 10 = 22 DOF。"""
    trunk = joint(
        "trunk_pitch",
        axis=(1, 0, 0),
        anchor=(0, 0, 0.04),
        size=(0.14, 0.09, 0.05),
        mass=0.20,
        children=[
            joint(
                "trunk_roll",
                axis=(0, 1, 0),
                anchor=(0, 0, 0.025),
                size=(0.16, 0.10, 0.10),
                mass=0.45,
                children=[head_chain(), arm_chain("left"), arm_chain("right")],
            )
        ],
    )
    return [trunk, leg_chain("left"), leg_chain("right")]


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


def render_joint(node: Dict[str, Any], indent: int) -> List[str]:
    pad = "  " * indent
    lines = [
        f"{pad}HingeJoint {{",
        f"{pad}  jointParameters HingeJointParameters {{",
        f"{pad}    axis {vec(node['axis'])}",
        f"{pad}    anchor {vec(node['anchor'])}",
        f"{pad}  }}",
        f"{pad}  device [",
        f"{pad}    RotationalMotor {{",
        f'{pad}      name "{node["name"]}"',
        f"{pad}      maxVelocity {num(MOTOR_MAX_VELOCITY)}",
        f"{pad}    }}",
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
            lines.extend(render_joint(child, indent + 3))
        lines.append(f"{pad}    ]")
    lines.append(f"{pad}  }}")
    lines.append(f"{pad}}}")
    return lines


def render_world() -> str:
    lines = [
        f"#VRML_SIM {WORLD_VERSION} utf8",
        "",
        "# 本文件由 webots/tools/generate_atri_world.py 生成，请勿手改。",
        "# A.T.R.I. 22 DOF 桌面人形：躯干 2 + 头 2 + 双臂 8 + 双腿 10。",
        "# 电机名与 controllers/atri_controller/joint_mapping.json 一一对应（默认同名映射）。",
        "",
        "WorldInfo {",
        f'  title "A.T.R.I. 22 DOF 桌面人形（运动学联调）"',
        f"  basicTimeStep {BASIC_TIME_STEP}",
        f"  gravity {num(GRAVITY)}",
        "  ERP 0.6",
        "  CFM 1e-05",
        "}",
        "",
        "Viewpoint {",
        "  orientation -0.1567 0.8935 0.4214 1.1077",
        "  position 0.62 -0.72 0.66",
        "  followType \"None\"",
        "}",
        "",
        "Robot {",
        '  name "ATRI"',
        '  controller "atri_controller"',
        "  translation 0 0 0.30",
        "  boundingObject Box {",
        "    size 0.16 0.10 0.08",
        "  }",
        "  physics Physics {",
        "    density -1",
        "    mass 1.0",
        "  }",
        "  children [",
    ]
    for node in robot_children():
        lines.extend(render_joint(node, 2))
    lines += [
        "  ]",
        "}",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    names = joint_names()
    assert len(names) == 22, f"关节数应为 22，实际 {len(names)}"
    assert len(set(names)) == 22, "关节名重复"

    WORLD_PATH.parent.mkdir(parents=True, exist_ok=True)
    # 用 open(..., newline="\n") 而不是 Path.write_text(newline=...)：
    # write_text 的 newline 参数是 Python 3.10 才加的，CI 矩阵里有 3.9。
    with open(WORLD_PATH, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(render_world())
    print(f"已生成 {WORLD_PATH}")
    print(f"关节数 {len(names)}: {', '.join(names)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
