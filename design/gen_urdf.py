#!/usr/bin/env python3
"""从 design/robot_model.json 生成 URDF，并校验设计约束。

纯标准库实现，不依赖 numpy / lxml。

用法：
    python3 design/gen_urdf.py --validate
    python3 design/gen_urdf.py --summary
    python3 design/gen_urdf.py --output design/atri.urdf

单位纪律：
    模型 JSON 用 mm，URDF 用 m；角度在 JSON 里是 deg，URDF 里是 rad。
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
MODEL_PATH = HERE / "robot_model.json"

# 软件侧的关节定义是"同源"依据：关节名与限位以它为准
sys.path.insert(0, str(REPO / "软件" / "atri"))
try:
    from atri.config import JOINTS, GROUP_DOF, DOF_COUNT  # noqa: E402
except ImportError:  # 允许独立运行
    JOINTS = None
    GROUP_DOF = None
    DOF_COUNT = 22


def load_model(path: Path = MODEL_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def mm_to_m(value: float) -> float:
    return float(value) / 1000.0


def deg_to_rad(value: float) -> float:
    return float(value) * math.pi / 180.0


def box_inertia(mass: float, size_mm: list[float]) -> tuple[float, float, float]:
    """实心长方体惯量（kg·m²），尺寸输入 mm。"""
    w, d, h = (mm_to_m(v) for v in size_mm)
    ixx = mass * (d * d + h * h) / 12.0
    iyy = mass * (w * w + h * h) / 12.0
    izz = mass * (w * w + d * d) / 12.0
    return ixx, iyy, izz


def build_urdf(model: dict) -> str:
    """生成 URDF 文本，含 visual / collision / inertial。"""
    lines: list[str] = []
    lines.append('<?xml version="1.0"?>')
    lines.append(f'<robot name="{model["name"]}">')
    lines.append("  <!-- 由 design/gen_urdf.py 生成，请勿手工编辑 -->")
    lines.append("  <!-- units: model mm -> urdf m; angles deg -> rad -->")

    # 根 link
    root = "pelvis"
    for link in model["links"]:
        name = link["name"]
        geom = link.get("geometry", {})
        size = geom.get("size_mm", [100.0, 100.0, 100.0])
        color = geom.get("color", [0.7, 0.7, 0.7])
        mass = float(link["mass_kg"])
        sx, sy, sz = (mm_to_m(v) for v in size)
        ixx, iyy, izz = box_inertia(mass, size)

        lines.append(f'  <link name="{name}">')
        lines.append("    <visual>")
        lines.append(f'      <origin xyz="0 0 0" rpy="0 0 0"/>')
        lines.append("      <geometry>")
        lines.append(f'        <box size="{sx:.6f} {sy:.6f} {sz:.6f}"/>')
        lines.append("      </geometry>")
        lines.append("      <material>")
        lines.append(f'        <color rgba="{color[0]:.3f} {color[1]:.3f} {color[2]:.3f} 1.0"/>')
        lines.append("      </material>")
        lines.append("    </visual>")
        lines.append("    <collision>")
        lines.append(f'      <origin xyz="0 0 0" rpy="0 0 0"/>')
        lines.append("      <geometry>")
        lines.append(f'        <box size="{sx:.6f} {sy:.6f} {sz:.6f}"/>')
        lines.append("      </geometry>")
        lines.append("    </collision>")
        lines.append("    <inertial>")
        lines.append(f'      <origin xyz="0 0 0" rpy="0 0 0"/>')
        lines.append(f'      <mass value="{mass:.6f}"/>')
        lines.append(
            f'      <inertia ixx="{ixx:.9f}" ixy="0" ixz="0" '
            f'iyy="{iyy:.9f}" iyz="0" izz="{izz:.9f}"/>'
        )
        lines.append("    </inertial>")
        lines.append("  </link>")

    for joint in sorted(model["joints"], key=lambda j: j["id"]):
        lo, hi = joint["limit_deg"]
        axis = " ".join(str(a) for a in joint["axis"])
        xyz = " ".join(f"{mm_to_m(v):.6f}" for v in joint["origin_xyz_mm"])
        effort = joint.get("effort_nm", 1.0)
        velocity = deg_to_rad(joint.get("velocity_dps", 180.0))
        lines.append(f'  <joint name="{joint["name"]}" type="{joint["type"]}">')
        lines.append(f'    <parent link="{joint["parent"]}"/>')
        lines.append(f'    <child link="{joint["child"]}"/>')
        lines.append(f'    <axis xyz="{axis}"/>')
        lines.append(f'    <origin xyz="{xyz}" rpy="0 0 0"/>')
        lines.append(
            f'    <limit lower="{deg_to_rad(lo):.6f}" '
            f'upper="{deg_to_rad(hi):.6f}" '
            f'effort="{effort:.3f}" velocity="{velocity:.6f}"/>'
        )
        lines.append("  </joint>")

    lines.append("</robot>")
    return "\n".join(lines) + "\n"


def check(model: dict) -> list[str]:
    """返回问题列表；空列表表示通过。"""
    problems: list[str] = []
    links = {link["name"] for link in model["links"]}
    joints = model["joints"]

    # 1) 关节数量与编号
    ids = sorted(j["id"] for j in joints)
    if ids != list(range(len(joints))):
        problems.append(f"关节编号不连续: {ids}")

    # 2) 与软件配置同源
    if JOINTS is not None:
        model_names = {j["name"] for j in joints}
        code_names = set(JOINTS)
        if model_names != code_names:
            missing = sorted(code_names - model_names)
            extra = sorted(model_names - code_names)
            if missing:
                problems.append(f"模型缺少软件侧关节: {missing}")
            if extra:
                problems.append(f"模型多出未知关节: {extra}")
        for j in joints:
            spec = JOINTS.get(j["name"])
            if not spec:
                continue
            if list(j["limit_deg"]) != list(spec["limit_deg"]):
                problems.append(
                    f"{j['name']} 限位不一致: 模型 {j['limit_deg']} vs 软件 {spec['limit_deg']}"
                )
            if j["id"] != spec["id"]:
                problems.append(f"{j['name']} 编号不一致: {j['id']} vs {spec['id']}")

    # 3) 父子 link 必须存在
    for j in joints:
        if j["parent"] not in links:
            problems.append(f"{j['name']} 的父 link 不存在: {j['parent']}")
        if j["child"] not in links:
            problems.append(f"{j['name']} 的子 link 不存在: {j['child']}")

    # 4) 每个 link 只能有一个父关节（树结构），根除外
    children = [j["child"] for j in joints]
    dupes = {c for c in children if children.count(c) > 1}
    if dupes:
        problems.append(f"link 被多个关节作为子节点: {sorted(dupes)}")

    # 5) 质量合计
    total_mass = sum(link["mass_kg"] for link in model["links"])
    declared = model["overall"]["mass_kg"]
    if abs(total_mass - declared) > 0.02:
        problems.append(
            f"质量合计 {total_mass:.3f} kg 与声明 {declared:.3f} kg 不符（容差 0.02）"
        )

    # 6) 官方尺寸约束
    c = model["design_constraints"]
    o = model["overall"]
    if o["height_mm"] > c["competition_max_height_mm"]:
        problems.append(f"高度 {o['height_mm']} 超过上限 {c['competition_max_height_mm']}")
    if o["width_mm"] > c["competition_max_width_mm"]:
        problems.append(f"宽度 {o['width_mm']} 超过上限 {c['competition_max_width_mm']}")
    if o["depth_mm"] > c["competition_max_depth_mm"]:
        problems.append(f"厚度 {o['depth_mm']} 超过上限 {c['competition_max_depth_mm']}")

    # 7) 自由度分组
    if GROUP_DOF is not None:
        if GROUP_DOF["leg_l"] < c["competition_min_leg_dof_per_side"]:
            problems.append("单腿自由度数不足")
        upper = GROUP_DOF["arm_l"] + GROUP_DOF["arm_r"] + GROUP_DOF["trunk"]
        if upper < c["competition_min_upper_dof"]:
            problems.append(f"上肢+躯干自由度 {upper} 不足 {c['competition_min_upper_dof']}")
        if len(JOINTS) < c["competition_min_dof"]:
            problems.append("总自由度数不足")

    return problems


def kinematic_chain(model: dict, leaf: str) -> list[dict]:
    """从根到 leaf 的关节链。"""
    by_child = {j["child"]: j for j in model["joints"]}
    chain: list[dict] = []
    cur = leaf
    while cur in by_child:
        j = by_child[cur]
        chain.append(j)
        cur = j["parent"]
    chain.reverse()
    return chain


def reach_mm(model: dict, leaf: str) -> float:
    """沿链累加位移，得到该 leaf 相对根的直线距离（零姿态近似）。"""
    links = {l["name"]: l for l in model["links"]}
    x = y = z = 0.0
    for j in kinematic_chain(model, leaf):
        ox, oy, oz = j["origin_xyz_mm"]
        x += ox
        y += oy
        z += oz
    # 加上末端 link 自身半高
    geom = links.get(leaf, {}).get("geometry", {}).get("size_mm")
    if geom:
        z += geom[2] / 2.0
    return math.sqrt(x * x + y * y + z * z)


def summary(model: dict) -> str:
    out: list[str] = []
    o = model["overall"]
    c = model["design_constraints"]
    out.append("=" * 62)
    out.append("A.T.R.I. 设计模型摘要")
    out.append("=" * 62)
    out.append(f"模型状态      : {model['model_status']}")
    out.append(f"自由度        : {len(model['joints'])} (要求 >= {c['competition_min_dof']})")
    out.append(f"link 数       : {len(model['links'])}")
    out.append(
        f"包络 (HxWxD)  : {o['height_mm']:.1f} x {o['width_mm']:.1f} x {o['depth_mm']:.1f} mm"
    )
    out.append(
        f"官方上限      : {c['competition_max_height_mm']:.0f} x "
        f"{c['competition_max_width_mm']:.0f} x {c['competition_max_depth_mm']:.0f} mm"
    )
    hm = o["height_mm"] / c["competition_max_height_mm"] * 100.0
    out.append(f"高度占上限    : {hm:.1f}%")
    total_mass = sum(l["mass_kg"] for l in model["links"])
    out.append(f"质量合计      : {total_mass:.3f} kg (声明 {o['mass_kg']:.2f} kg)")
    out.append("")
    out.append("单侧臂长与腿长（零姿态近似，含末端半高）:")
    for leaf, label in (
        ("left_gripper", "左臂(肩->夹爪)"),
        ("left_foot", "左腿(髋->足底)"),
        ("head", "躯干顶->头顶"),
    ):
        out.append(f"  {label:<16}: {reach_mm(model, leaf):7.1f} mm")
    out.append("")
    out.append(f"单侧臂长上限  : {c['single_arm_max_length_mm']:.0f} mm")
    out.append("")
    out.append("关节清单:")
    for j in sorted(model["joints"], key=lambda x: x["id"]):
        lo, hi = j["limit_deg"]
        out.append(
            f"  [{j['id']:2d}] {j['name']:<22} {lo:>6.0f} .. {hi:>4.0f} deg"
            f"  axis {j['axis']}"
        )
    out.append("=" * 62)
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成并校验 A.T.R.I. URDF")
    parser.add_argument("--model", type=Path, default=MODEL_PATH)
    parser.add_argument("--output", type=Path, default=HERE / "atri.urdf")
    parser.add_argument("--validate", action="store_true", help="只做校验")
    parser.add_argument("--summary", action="store_true", help="打印摘要")
    parser.add_argument("--write", action="store_true", help="写出 URDF 文件")
    args = parser.parse_args(argv)

    model = load_model(args.model)
    problems = check(model)

    if args.summary:
        print(summary(model))
        print()

    if problems:
        print(f"校验未通过，共 {len(problems)} 项问题:")
        for p in problems:
            print(f"  - {p}")
        return 1

    print("校验通过: 关节同源、限位一致、尺寸合规、质量自洽。")

    if args.write or not args.validate:
        text = build_urdf(model)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
        print(f"已写出: {args.output}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
