"""整机装配：把 22 个关节模块、8 根连杆、10 件电子件按 URDF 运动学装起来。

为什么以 URDF 为装配基准：
    `design/atri.urdf` 是运动学与质量的**单一真值源**（`check_fit.py` 校验过闭合）。
    装配体如果另起一套坐标，图纸与仿真必然对不上——v1 就吃过这个亏
    （webots 生成器手写常量，腿段 190 vs 235 mm）。

产出：
    out/step/ATRI-assembly.step    整机装配体（SolidWorks 可直接打开）
    out/stl/ATRI-assembly.stl      整机网格（看包络、做干涉预览）
    out/assembly_report.md         装配清单 + 质量闭合 + 干涉粗查

用法：
    .venv-cad/bin/python design/cad/assembly.py --all
"""
from __future__ import annotations

import json
import math
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))

import cadquery as cq

import skeleton as sk
from kit import MATERIALS, apply_trsf, box, cyl, printed_mass
from parts import sanitize
from standards import SERVOS, servo

OUT = HERE / "out"
DESIGN = REPO / "design"
SERVO_NAME = "STS3215"

# --------------------------------------------------------------------------
# 矩阵工具（4×4，行主序；纯 Python，避免为装配引入 numpy 依赖）
# --------------------------------------------------------------------------
Mat = List[List[float]]


def mat_identity() -> Mat:
    return [[1.0 if i == j else 0.0 for j in range(4)] for i in range(4)]


def mat_mul(a: Mat, b: Mat) -> Mat:
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)]
            for i in range(4)]


def mat_trans(x: float, y: float, z: float) -> Mat:
    m = mat_identity()
    m[0][3], m[1][3], m[2][3] = x, y, z
    return m


def mat_rpy(r: float, p: float, yw: float) -> Mat:
    """URDF 的固定轴 XYZ 外旋（R = Rz·Ry·Rx）。"""
    cr, sr = math.cos(r), math.sin(r)
    cp, sp = math.cos(p), math.sin(p)
    cy, sy = math.cos(yw), math.sin(yw)
    return [
        [cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr, 0.0],
        [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr, 0.0],
        [-sp, cp * sr, cp * cr, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]


def apply(m: Mat, v: Sequence[float]) -> Tuple[float, float, float]:
    x, y, z = v
    return (m[0][0] * x + m[0][1] * y + m[0][2] * z + m[0][3],
            m[1][0] * x + m[1][1] * y + m[1][2] * z + m[1][3],
            m[2][0] * x + m[2][1] * y + m[2][2] * z + m[2][3])


def rot3(m: Mat) -> List[List[float]]:
    return [row[:3] for row in m[:3]]


# --------------------------------------------------------------------------
# URDF 运动学
# --------------------------------------------------------------------------
class Kin:
    def __init__(self, urdf: Path):
        root = ET.parse(urdf).getroot()
        self.joints: Dict[str, Dict[str, Any]] = {}
        self.parent_of: Dict[str, str] = {}
        self.children: Dict[str, List[str]] = {}
        links = [l.get("name") for l in root.findall("link")]
        for l in links:
            self.children[l] = []
        for j in root.findall("joint"):
            name = j.get("name")
            parent = j.find("parent").get("link")
            child = j.find("child").get("link")
            o = j.find("origin")
            # URDF 单位是 m，本 CAD 层全用 mm —— 这里换算一次，下游不再管
            xyz = [float(v) * 1000.0
                   for v in (o.get("xyz") or "0 0 0").split()]
            rpy = [float(v) for v in (o.get("rpy") or "0 0 0").split()]
            ax = j.find("axis")
            axis = [float(v) for v in (ax.get("xyz") if ax is not None
                                       else "0 0 1").split()]
            self.joints[name] = {"parent": parent, "child": child,
                                 "xyz": xyz, "rpy": rpy, "axis": axis}
            self.parent_of[child] = name
            self.children[parent].append(child)
        self.root = [l for l in links if l not in self.parent_of][0]
        self.world: Dict[str, Mat] = {}
        self._fk(self.root, mat_identity())

    def _fk(self, link: str, m: Mat) -> None:
        self.world[link] = m
        for child in self.children[link]:
            j = self.joints[self.parent_of[child]]
            self._fk(child, mat_mul(m, mat_mul(mat_trans(*j["xyz"]),
                                               mat_rpy(*j["rpy"]))))

    def joint_world(self, joint: str) -> Mat:
        """关节坐标系的世界位姿（= 父 link 位姿 × 关节 origin）。"""
        j = self.joints[joint]
        return mat_mul(self.world[j["parent"]],
                       mat_mul(mat_trans(*j["xyz"]), mat_rpy(*j["rpy"])))

    def axis_world(self, joint: str) -> Tuple[float, float, float]:
        j = self.joints[joint]
        m = self.joint_world(joint)
        v = (m[0][0] * j["axis"][0] + m[0][1] * j["axis"][1] + m[0][2] * j["axis"][2],
             m[1][0] * j["axis"][0] + m[1][1] * j["axis"][1] + m[1][2] * j["axis"][2],
             m[2][0] * j["axis"][0] + m[2][1] * j["axis"][1] + m[2][2] * j["axis"][2])
        n = math.sqrt(sum(c * c for c in v)) or 1.0
        return (round(v[0] / n, 3), round(v[1] / n, 3), round(v[2] / n, 3))


# --------------------------------------------------------------------------
# 装配方案（本文件的核心：谁装在谁身上、朝哪边）
# --------------------------------------------------------------------------
AXIS_NAME = {(1, 0, 0): "+x", (-1, 0, 0): "-x", (0, 1, 0): "+y",
             (0, -1, 0): "-y", (0, 0, 1): "+z", (0, 0, -1): "-z"}
OPP = {"+x": "-x", "-x": "+x", "+y": "-y", "-y": "+y", "+z": "-z", "-z": "+z"}

# 每个关节：输出轴方向（世界）、母端结构朝向（世界）、母端零件类型
# 22 个关节的装配方案：
#   shaft  输出轴方向（世界系，零位）
#   parent 母端结构朝向（= 舵机笼往哪边固定在上级结构上）
#   cage   母端笼的实现：ortho=独立关节笼 / yaw=偏转笼 / adapter=集成在紧凑转接块里
#   fork   子端叉的实现：fork=独立连杆叉 / adapter=转接块自带舵盘面 / part=大件自带
JOINT_SCHEME: Dict[str, Dict[str, str]] = {
    "head_yaw":          {"shaft": "+z", "parent": "+z", "cage": "yaw",     "fork": "adapter"},
    "head_pitch":        {"shaft": "+y", "parent": "-z", "cage": "adapter", "fork": "part"},
    "trunk_roll":        {"shaft": "+x", "parent": "-z", "cage": "ortho",   "fork": "adapter"},
    "trunk_pitch":       {"shaft": "+y", "parent": "-z", "cage": "adapter", "fork": "part"},
    "left_hip_yaw":      {"shaft": "-z", "parent": "+z", "cage": "yaw",     "fork": "adapter"},
    "right_hip_yaw":     {"shaft": "-z", "parent": "+z", "cage": "yaw",     "fork": "adapter"},
    "left_hip_roll":     {"shaft": "-x", "parent": "+z", "cage": "adapter", "fork": "adapter"},
    "right_hip_roll":    {"shaft": "-x", "parent": "+z", "cage": "adapter", "fork": "adapter"},
    "left_hip_pitch":    {"shaft": "+y", "parent": "+z", "cage": "adapter", "fork": "fork"},
    "right_hip_pitch":   {"shaft": "-y", "parent": "+z", "cage": "adapter", "fork": "fork"},
    "left_knee_pitch":   {"shaft": "+y", "parent": "+z", "cage": "ortho",   "fork": "fork"},
    "right_knee_pitch":  {"shaft": "-y", "parent": "+z", "cage": "ortho",   "fork": "fork"},
    "left_ankle_pitch":  {"shaft": "+y", "parent": "+z", "cage": "ortho",   "fork": "part"},
    "right_ankle_pitch": {"shaft": "-y", "parent": "+z", "cage": "ortho",   "fork": "part"},
    "left_shoulder_pitch":  {"shaft": "+y", "parent": "-y", "cage": "yaw",     "fork": "adapter"},
    "right_shoulder_pitch": {"shaft": "-y", "parent": "+y", "cage": "yaw",     "fork": "adapter"},
    "left_shoulder_roll":   {"shaft": "-x", "parent": "+y", "cage": "adapter", "fork": "fork"},
    "right_shoulder_roll":  {"shaft": "+x", "parent": "-y", "cage": "adapter", "fork": "fork"},
    "left_elbow_pitch":  {"shaft": "+y", "parent": "+z", "cage": "ortho",   "fork": "fork"},
    "right_elbow_pitch": {"shaft": "-y", "parent": "+z", "cage": "ortho",   "fork": "fork"},
    "left_gripper":      {"shaft": "+y", "parent": "+z", "cage": "ortho",   "fork": "part"},
    "right_gripper":     {"shaft": "-y", "parent": "+z", "cage": "ortho",   "fork": "part"},
}

# 每个 link 的"长件"（管/大件），放在 link 位姿上
LINK_BULK: Dict[str, List[Tuple[str, Dict[str, Any]]]] = {
    "pelvis": [("pelvis_frame", {})],
    "torso_upper": [("torso_frame", {}), ("electronics_deck", {}),
                    ("battery_tray", {}), ("pdb_mount", {})],
    "head": [("head_shell", {})],
    "left_thigh": [("limb_tube", {"length": 62.8, "z0": -62.8})],
    "right_thigh": [("limb_tube", {"length": 62.8, "z0": -62.8})],
    "left_shank": [("limb_tube", {"length": 62.8, "z0": -62.8})],
    "right_shank": [("limb_tube", {"length": 62.8, "z0": -62.8})],
    "left_upper_arm": [("limb_tube", {"length": 47.1, "z0": -47.1})],
    "right_upper_arm": [("limb_tube", {"length": 47.1, "z0": -47.1})],
    "left_forearm": [("limb_tube", {"length": 39.2, "z0": -39.2})],
    "right_forearm": [("limb_tube", {"length": 39.2, "z0": -39.2})],
    "left_foot": [("foot_plate", {})],
    "right_foot": [("foot_plate", {})],
    "left_gripper": [("gripper_jaw", {})],
    "right_gripper": [("gripper_jaw", {})],
}

# 紧凑转接块：一次覆盖"上一级舵盘 + 下一级舵机笼"两件事
ADAPTERS: Dict[str, Dict[str, Any]] = {
    "head_yaw_link": {"in_shaft": "+z", "out_shaft": "+y", "drop": 27.5},
    "trunk_roll_link": {"in_shaft": "+x", "out_shaft": "+y", "drop": 27.5},
    "left_hip_yaw_link": {"in_shaft": "-z", "out_shaft": "-x", "drop": 19.6},
    "right_hip_yaw_link": {"in_shaft": "-z", "out_shaft": "-x", "drop": 19.6},
    "left_hip_roll_link": {"in_shaft": "-x", "out_shaft": "+y", "drop": 19.6},
    "right_hip_roll_link": {"in_shaft": "-x", "out_shaft": "-y", "drop": 19.6},
    "left_shoulder_pitch_link": {"in_shaft": "+y", "out_shaft": "-x", "drop": 0.0},
    "right_shoulder_pitch_link": {"in_shaft": "-y", "out_shaft": "+x", "drop": 0.0},
}


def _place(shape: cq.Workplane, m: Mat) -> cq.Workplane:
    """按 4×4 矩阵放置（旋转 + 平移）。"""
    from OCP.gp import gp_Trsf

    r = rot3(m)
    trsf = gp_Trsf()
    trsf.SetValues(r[0][0], r[0][1], r[0][2], m[0][3],
                   r[1][0], r[1][1], r[1][2], m[1][3],
                   r[2][0], r[2][1], r[2][2], m[2][3])
    return apply_trsf(shape, trsf)


def servo_placeholder(name: str = SERVO_NAME) -> cq.Workplane:
    """舵机占位实体（干涉检查用；真实外形见 standards.SERVOS）。

    ⚠️ 2026-09-11 订正（见 design/handoff/STS3215-机械接口核验.md）：
    本函数原来在机身两侧 union 两个 `ear_extend_mm` 方块来表示"安装耳"，
    但 **STS3215 根本没有安装耳** —— 实物包装标签（A:45.22mm）、实物照片、
    以及 B-rep 模型三方一致证伪，`ear_*` 字段已从 standards.py 删除。
    那些方块会让每个舵机的包络虚增 6 mm，并使干涉检查报**假干涉**。

    现按实测真实接口重建：
        机身     45.2 × 24.7 × 35.0
        ±Z 两端面各一个 Φ20 圆盘（厚 2.1 / 2.5）
        → 总高 35.0 + 2.1 + 2.5 = 39.6，与模型实测包络 39.619 吻合 ✅
    """
    s = servo(name)
    L, W, H = s["body_mm"]
    part = box(L, W, H)

    disc_d = s["body_mount_disc_od_mm"]
    t_bottom, t_top = s["body_mount_disc_thickness_mm"]
    # ⚠️ 轴心 X 偏移为 provisional（模型坐标系 vs 实物基准面尚未完全对应），
    #    见 standards.py 的 body_mount_axis_note。数据坐实后自动生效。
    ax, ay = s["body_mount_axis_xy_mm"]
    part = part.union(cyl(disc_d, t_bottom, at=(ax, ay, -t_bottom), axis="Z"))
    part = part.union(cyl(disc_d, t_top, at=(ax, ay, H), axis="Z"))
    return part


def electronics_placeholder(size: Sequence[float]) -> cq.Workplane:
    return box(size[0], size[1], size[2])


# 电子件的摆放姿态（placements.json 只给位置与尺寸，姿态在这里定）
ELEC_ROT_DEG = {"compute": 90.0}      # 树莓派 85 mm 边沿 Y 向（躯干内净空 90）
# 躯干骨架重排（给俯仰叉让位）后，舱内件要落在**各自的那块托盘/仓底**上。
# 托盘上表面（torso 局部坐标，见 skeleton.torso_frame）：
# 托盘上表面（torso 局部坐标，见 skeleton.torso_frame 的绝对布局）
ELEC_DECK_TOP = {
    "compute": 42.0 + 2.6,                    # 树莓派托盘
    "battery": 18.0 + 2.6,                    # 电池仓底板
}

# 容积超额订阅：STM32 / URT-1 / XL4015 / 功放 / 喇叭塞不进躯干（见
# 项目文档/骨架结构与集成方案.md §3.1），改挂到躯干背面（背挂模块）。
# 这不是"随便挪一下"：躯干内 俯仰叉 32 + 电池 19 + 树莓派 17 = 68 mm，
# 而到 head_yaw 轴线只有 82.4 mm，还要留给颈座与偏转舵机笼。
ELEC_BACKPACK = {
    "mcu": 0, "servo_driver": 1, "bec": 2, "amp": 3, "speaker": 4,
}
BACKPACK_X = -60.0          # 躯干背面（躯干本体 x ∈ [−48, +48]）
BACKPACK_PITCH = 16.0


def build_assembly(kin: Kin, placements: Dict[str, Any],
                   parts_out: Optional[List[Dict[str, Any]]] = None
                   ) -> Tuple[List[Tuple[str, cq.Workplane]], List[Dict[str, Any]]]:
    """按 URDF 零位装配整机，返回 [(名称, 实体)] 与日志。"""
    items: List[Tuple[str, cq.Workplane]] = []
    log: List[Dict[str, Any]] = []

    def add(name: str, shape: cq.Workplane, kind: str, note: str = "") -> None:
        items.append((name, shape))
        log.append({"kind": kind, "name": name, "note": note, "ok": True})

    def fail(name: str, kind: str, exc: Exception) -> None:
        log.append({"kind": kind, "name": name, "ok": False,
                    "err": f"{type(exc).__name__}: {exc}"})

    # --- 1. 长件与大件（管 / 框架 / 托盘），放在 link 位姿上 ---
    for link, parts in LINK_BULK.items():
        if link not in kin.world:
            continue
        for pname, kw in parts:
            try:
                add(f"{link}__{pname}", _place(sk.build(pname, **kw),
                                               kin.world[link]), "bulk")
            except Exception as exc:  # noqa: BLE001
                fail(f"{link}/{pname}", "bulk", exc)

    # --- 2. 紧凑转接块（自带上一级舵盘面 + 下一级舵机笼）---
    for link, cfg in ADAPTERS.items():
        if link not in kin.world:
            continue
        try:
            add(f"{link}__compact_adapter",
                _place(sk.build("compact_adapter", **cfg), kin.world[link]),
                "adapter")
        except Exception as exc:  # noqa: BLE001
            fail(f"{link}/compact_adapter", "adapter", exc)

    # --- 3. 每个关节：母端笼（装在父 link）+ 子端叉（装在子 link）---
    for jname, sc in JOINT_SCHEME.items():
        try:
            m = kin.joint_world(jname)
        except Exception as exc:  # noqa: BLE001
            fail(jname, "joint", exc)
            continue
        if sc["cage"] == "ortho":
            try:
                add(f"cage__{jname}",
                    _place(sk.build("joint_cage", shaft=sc["shaft"],
                                    parent=sc["parent"]), m), "cage")
            except Exception as exc:  # noqa: BLE001
                fail(f"cage/{jname}", "cage", exc)
        elif sc["cage"] == "yaw":
            try:
                add(f"cage__{jname}",
                    _place(sk.build("joint_cage_yaw", parent=sc["parent"],
                                    shaft=sc["shaft"]), m),
                    "cage")
            except Exception as exc:  # noqa: BLE001
                fail(f"cage/{jname}", "cage", exc)
        if sc["fork"] == "fork":
            try:
                add(f"fork__{jname}",
                    _place(sk.build("limb_fork", shaft=sc["shaft"],
                                    parent=sc["parent"]), m), "fork")
            except Exception as exc:  # noqa: BLE001
                fail(f"fork/{jname}", "fork", exc)

    # --- 4. 舵机（父 link 的关节原点）---
    for jname, sc in JOINT_SCHEME.items():
        try:
            # 定向放在调用点做（不依赖 servo_placeholder 的签名——
            # 该函数正被另一个会话订正，见 handoff/STS3215-机械接口核验.md）
            from kit import orient
            # 轴与母端同向（yaw/肩）时 orient() 退化：用一个垂直方向定"钟表位"
            par = sc["parent"]
            if par.replace("+", "").replace("-", "") == \
               sc["shaft"].replace("+", "").replace("-", ""):
                par = next(d for d in ("+z", "-z", "+y", "-y", "+x", "-x")
                           if d.replace("+", "").replace("-", "") !=
                           sc["shaft"].replace("+", "").replace("-", ""))
            body = orient(servo_placeholder(), sc["shaft"], par)
            add(f"servo__{jname}", _place(body, kin.joint_world(jname)), "servo")
        except Exception as exc:  # noqa: BLE001
            fail(f"servo/{jname}", "servo", exc)

    # --- 5. 电子件（host link 位姿 × 局部偏移 × 姿态）---
    for e in placements["electronics"]:
        link = e["link"]
        if link not in kin.world:
            continue
        try:
            pos = list(e["position_mm"])
            if link == "torso_upper" and e["id"] in ELEC_DECK_TOP:
                # 底面坐在托盘上表面：中心 z = 盘面 + 自身高/2
                pos[2] = ELEC_DECK_TOP[e["id"]] + e["size_mm"][2] / 2.0
            elif link == "torso_upper" and e["id"] in ELEC_BACKPACK:
                # 背挂：沿 −X 挂在躯干背面，按序号纵向排开
                k = ELEC_BACKPACK[e["id"]]
                pos = [BACKPACK_X - e["size_mm"][0] / 2.0,
                       0.0,
                       30.0 - k * BACKPACK_PITCH]
            local = mat_mul(mat_trans(*pos),
                            mat_rpy(0.0, 0.0, math.radians(
                                ELEC_ROT_DEG.get(e["id"], 0.0))))
            add(f"elec__{e['id']}",
                _place(electronics_placeholder(e["size_mm"]),
                       mat_mul(kin.world[link], local)), "elec")
        except Exception as exc:  # noqa: BLE001
            fail(f"elec/{e['id']}", "elec", exc)
    return items, log


def main(argv: Optional[List[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="A.T.R.I. 整机装配")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--no-export", action="store_true")
    args = ap.parse_args(argv)

    kin = Kin(DESIGN / "atri.urdf")
    placements = json.loads((DESIGN / "placements.json").read_text(encoding="utf-8"))
    items, log = build_assembly(kin, placements)

    ok = [l for l in log if l.get("ok")]
    bad = [l for l in log if not l.get("ok")]
    print(f"装配件 {len(items)} 个（成功 {len(ok)}，失败 {len(bad)}）")
    for b in bad:
        print(f"  [ERR] {b['name']}: {b.get('err')}")

    bb = None
    for _, w in items:
        b = w.val().BoundingBox()
        bb = b if bb is None else bb.add(b)
    if bb:
        print(f"整机包络 {bb.xlen:.0f} × {bb.ylen:.0f} × {bb.zlen:.0f} mm")

    if not args.no_export and items:
        (OUT / "step").mkdir(parents=True, exist_ok=True)
        path = OUT / "step" / "ATRI-assembly.step"
        comp = cq.Compound.makeCompound([w.val() for _, w in items])
        cq.exporters.export(cq.Workplane("XY").newObject([comp]), str(path))
        print(f"已导出 {path}（{path.stat().st_size/1e6:.1f} MB）")
        stl = OUT / "stl" / "ATRI-assembly.stl"
        cq.exporters.export(cq.Workplane("XY").newObject([comp]), str(stl),
                            tolerance=0.4, angularTolerance=0.4)
        print(f"已导出 {stl}（{stl.stat().st_size/1e6:.1f} MB）")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
