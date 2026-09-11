"""生成 A.T.R.I. 22 DOF 的 Webots 世界文件。

为什么要生成而不是手写：22 个关节 × (HingeJoint + RotationalMotor + PositionSensor
+ endPoint Solid) 手写近千行且极易写错；用脚本生成，改尺寸/改关节只需改这里的表。

为什么自包含、不用 ``EXTERNPROTO``：本机（以及比赛机器的网络）访问 GitHub 受限，
世界文件一旦依赖外部 PROTO 就可能打不开。这里全部用 Webots 内置节点
（``Robot`` / ``HingeJoint`` / ``RotationalMotor`` / ``PositionSensor`` / ``Solid`` / ``Box``）。

电机名与 ``controllers/atri_controller/joint_mapping.json`` 完全一致（默认同名映射），
所以 22 个关节全部能绑定上，联调跑的就是全关节。关节硬限位（``minStop``/``maxStop``）
与电机 ``maxVelocity`` 也逐关节取自 ``design/robot_model.json`` 的
``limit_deg`` / ``velocity_dps``，世界与模型不再各写一套。

用法::

    python webots/tools/generate_atri_world.py
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Sequence

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


def render_joint(node: Dict[str, Any], indent: int) -> List[str]:
    pad = "  " * indent
    lo, hi = node["limit_deg"]
    lines = [
        f"{pad}HingeJoint {{",
        f"{pad}  jointParameters HingeJointParameters {{",
        f"{pad}    axis {vec(node['axis'])}",
        f"{pad}    anchor {vec(node['anchor'])}",
        # Webots 不写 minStop/maxStop 就是无限位，控制器钳制再严也只是软件层
        f"{pad}    minStop {num(math.radians(lo))}",
        f"{pad}    maxStop {num(math.radians(hi))}",
        f"{pad}  }}",
        f"{pad}  device [",
        f"{pad}    RotationalMotor {{",
        f'{pad}      name "{node["name"]}"',
        f"{pad}      maxVelocity {num(math.radians(node['velocity_dps']))}",
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
    _body = robot_body()
    lines = [
        f"#VRML_SIM {WORLD_VERSION} utf8",
        "",
        "# 本文件由 webots/tools/generate_atri_world.py 生成，请勿手改。",
        "# A.T.R.I. 22 DOF 桌面人形：几何与质量派生自 design/robot_model.json。",
        "# 关节限位与电机速度上限同样来自模型（minStop/maxStop/maxVelocity）。",
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
        lines.extend(render_joint(node, 2))
    lines += [
        "  ]",
        "}",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
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
