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

# 同目录的几何基元模块
sys.path.insert(0, str(HERE))
import geometry  # noqa: E402

# 软件侧的关节定义是"同源"依据：关节名与限位以它为准
sys.path.insert(0, str(REPO / "software" / "atri"))
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


def build_urdf(model: dict) -> str:
    """生成 URDF 文本，含 visual / collision / inertial。

    visual    使用真实几何基元（外观）
    collision 使用等效包围盒（标准工程做法：碰撞用简化体，更快更稳）
    inertial  按基元形状计算惯量（球/圆柱/胶囊用精确或等效公式）
    """
    lines: list[str] = []
    lines.append('<?xml version="1.0"?>')
    lines.append(f'<robot name="{model["name"]}">')
    lines.append("  <!-- 由 design/gen_urdf.py 生成，请勿手工编辑 -->")
    lines.append("  <!-- units: model mm -> urdf m; angles deg -> rad -->")
    lines.append("  <!-- visual = 真实基元；collision = 等效包围盒 -->")

    for link in model["links"]:
        name = link["name"]
        geom = link.get("geometry", {"type": "box", "size_mm": [100, 100, 100]})
        color = geom.get("color", [0.7, 0.7, 0.7])
        mass = float(link["mass_kg"])
        ixx, iyy, izz = geometry.inertia(geom, mass)
        coll = geometry.equivalent_box(geom)

        ox, oy, oz = geometry.geometry_origin(geom)
        origin = f"{mm_to_m(ox):.6f} {mm_to_m(oy):.6f} {mm_to_m(oz):.6f}"
        rpy = geometry.urdf_rpy(geom)

        lines.append(f'  <link name="{name}">')
        lines.append("    <visual>")
        lines.append(f'      <origin xyz="{origin}" rpy="{rpy}"/>')
        lines.append(geometry.urdf_xml(geom, indent="      "))
        lines.append("      <material>")
        lines.append(
            f'        <color rgba="{color[0]:.3f} {color[1]:.3f} {color[2]:.3f} 1.0"/>'
        )
        lines.append("      </material>")
        lines.append("    </visual>")
        lines.append("    <collision>")
        lines.append(f'      <origin xyz="{origin}" rpy="{rpy}"/>')
        lines.append(geometry.urdf_xml(coll, indent="      "))
        lines.append("    </collision>")
        # 附加体：舵机、电子件等"装在 link 上但不是主壳"的实体（v2 起）。
        # 只出 visual/collision，不重复计质量 —— 它们的质量已并入本 link 的 inertial，
        # 目的是让刚体引擎里的自碰撞与体积表达与真实装配一致。
        for extra in link.get("extra_geometry", []):
            exo = geometry.geometry_origin(extra)
            ex_origin = (f"{mm_to_m(exo[0]):.6f} {mm_to_m(exo[1]):.6f} "
                         f"{mm_to_m(exo[2]):.6f}")
            ex_rpy = geometry.urdf_rpy(extra)
            label = extra.get("label", "附件")
            ex_color = extra.get("color", [0.25, 0.27, 0.32])
            lines.append(f"    <!-- {label} -->")
            lines.append("    <visual>")
            lines.append(f'      <origin xyz="{ex_origin}" rpy="{ex_rpy}"/>')
            lines.append(geometry.urdf_xml(extra, indent="      "))
            lines.append("      <material>")
            lines.append(f'        <color rgba="{ex_color[0]:.3f} '
                         f'{ex_color[1]:.3f} {ex_color[2]:.3f} 1.0"/>')
            lines.append("      </material>")
            lines.append("    </visual>")
            lines.append("    <collision>")
            lines.append(f'      <origin xyz="{ex_origin}" rpy="{ex_rpy}"/>')
            lines.append(geometry.urdf_xml(geometry.equivalent_box(extra),
                                           indent="      "))
            lines.append("    </collision>")
        lines.append("    <inertial>")
        lines.append(f'      <origin xyz="{origin}" rpy="0 0 0"/>')
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

    # 8) 几何基元定义合法性
    for link in model["links"]:
        geom = link.get("geometry")
        if not geom:
            problems.append(f"{link['name']} 缺少 geometry")
            continue
        try:
            geometry.bounding_box(geom)
        except geometry.GeometryError as exc:
            problems.append(f"{link['name']} 几何定义错误: {exc}")
            continue
        try:
            ixx, iyy, izz = geometry.inertia(geom, link["mass_kg"])
            if min(ixx, iyy, izz) <= 0:
                problems.append(f"{link['name']} 惯量为非正值")
        except geometry.GeometryError as exc:
            problems.append(f"{link['name']} 惯量计算失败: {exc}")

    # 9) 由几何实际计算包络，与声明值比对
    try:
        actual = measured_envelope(model)
        for axis_name, key, limit_key in (
            ("高度", "height_mm", "competition_max_height_mm"),
            ("宽度", "width_mm", "competition_max_width_mm"),
            ("深度", "depth_mm", "competition_max_depth_mm"),
        ):
            declared = o[key]
            got = actual[key]
            if abs(declared - got) > 1.0:
                problems.append(
                    f"{axis_name}声明 {declared:.1f} mm 与几何实测 {got:.1f} mm 不符"
                )
    except Exception as exc:  # noqa: BLE001
        problems.append(f"包络计算失败: {exc}")

    return problems


def measured_envelope(model: dict) -> dict:
    """从关节链几何与各 link 包围盒，实测零姿态包络（mm）。"""
    tfs = geometry.link_positions(model)
    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3
    for link in model["links"]:
        tf = tfs.get(link["name"])
        if tf is None:
            continue
        mins, maxs = geometry.link_world_aabb(model, link["name"], tf)
        for i in range(3):
            lo[i] = min(lo[i], mins[i])
            hi[i] = max(hi[i], maxs[i])
    # 足底为地面参考：height 取 z 跨度；width 取 y；depth 取 x
    return {
        "height_mm": hi[2] - lo[2],
        "width_mm": hi[1] - lo[1],
        "depth_mm": hi[0] - lo[0],
        "min_z_mm": lo[2],
        "max_z_mm": hi[2],
    }


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


def shoulder_to_gripper_mm(model: dict) -> float:
    """肩关节轴线 -> 夹爪末端 的直线距离（材料口径的"单侧臂长"）。

    与 :func:`reach_mm` 的区别：那个从**根 link（骨盆）**起算，标签容易被误读成臂长。
    """
    tfs = geometry.link_positions(model)
    links = {l["name"]: l for l in model["links"]}
    shoulder = geometry.transform_point(tfs["left_shoulder_pitch_link"], (0, 0, 0))
    grip_h = geometry.bounding_box(links["left_gripper"]["geometry"])[2]
    tip = geometry.transform_point(tfs["left_gripper"], (0, 0, -grip_h / 2.0))
    return math.sqrt(sum((tip[i] - shoulder[i]) ** 2 for i in range(3)))


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
    # reach_mm 从**根 link（骨盆）**累加到叶端，不是从肩/髋起算。
    # 标签必须写清起点，否则会被当成材料口径的"单侧臂长"（v1 就踩过这个坑）。
    out.append("各叶端到根（骨盆）的距离（零姿态，含末端半高）:")
    for leaf, label in (
        ("left_gripper", "骨盆->夹爪末端"),
        ("left_foot", "骨盆->足底"),
        ("head", "骨盆->头顶"),
    ):
        out.append(f"  {label:<16}: {reach_mm(model, leaf):7.1f} mm")
    out.append("")
    out.append("材料口径「单侧臂长」= 肩关节->夹爪末端（官方未定义测量基准，按此口径自测）:")
    out.append(f"  {'左臂':<16}: {shoulder_to_gripper_mm(model):7.1f} mm"
               f"  （上限 {c['single_arm_max_length_mm']:.0f} mm）")
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
