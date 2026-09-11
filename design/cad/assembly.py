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
from fitcheck import overlap_report
from kit import DIRS, MATERIALS, apply_trsf, box, cyl, printed_mass, servo_frame
from parts import sanitize
from standards import SERVOS, servo

OUT = HERE / "out"
DESIGN = REPO / "design"
SERVO_NAME = "STS3215"

# 展示姿态（度）。机械零位右夹爪穿进 hip_yaw；预览把臂抬到身前。
# 不加 shoulder_roll（外展会超宽）。校核脚本继续用全 0。
DISPLAY_POSE_DEG = {
    "left_shoulder_pitch": -40.0,
    "right_shoulder_pitch": -40.0,
    "left_elbow_pitch": -55.0,
    "right_elbow_pitch": -55.0,
    "left_gripper": 20.0,
    "right_gripper": 20.0,
    "head_pitch": 8.0,
}

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


def mat_axis_angle(axis: Sequence[float], theta: float) -> Mat:
    """绕任意轴旋转（Rodrigues）。theta 为弧度。"""
    x, y, z = axis
    n = math.sqrt(x * x + y * y + z * z) or 1.0
    x, y, z = x / n, y / n, z / n
    c, s = math.cos(theta), math.sin(theta)
    C = 1.0 - c
    return [
        [x * x * C + c, x * y * C - z * s, x * z * C + y * s, 0.0],
        [y * x * C + z * s, y * y * C + c, y * z * C - x * s, 0.0],
        [z * x * C - y * s, z * y * C + x * s, z * z * C + c, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]


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
    def __init__(self, urdf: Path, pose_deg: Optional[Dict[str, float]] = None):
        """pose_deg：关节角（度）。默认全 0，与 URDF 零位一致。预览可传入展示姿态。"""
        self.pose_deg: Dict[str, float] = dict(pose_deg or {})
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
            jname = self.parent_of[child]
            j = self.joints[jname]
            origin = mat_mul(mat_trans(*j["xyz"]), mat_rpy(*j["rpy"]))
            theta = math.radians(self.pose_deg.get(jname, 0.0))
            if abs(theta) > 1e-12:
                origin = mat_mul(origin, mat_axis_angle(j["axis"], theta))
            self._fk(child, mat_mul(m, origin))

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
#   cage    母端笼：ortho / yaw / adapter / cluster（髋肩错轴抱箍）
#   fork    子端叉：fork / adapter / part
#   stagger 沿自身 shaft 的机体偏置 mm（来自 fit_stagger.py，禁止手写）
JOINT_SCHEME: Dict[str, Dict[str, Any]] = {
    "head_yaw":          {"shaft": "+z", "parent": "+z", "cage": "yaw",     "fork": "adapter", "clock": "flip"},
    "head_pitch":        {"shaft": "+y", "parent": "-z", "cage": "adapter", "fork": "part"},
    "trunk_roll":        {"shaft": "+x", "parent": "-z", "cage": "ortho",   "fork": "adapter"},
    "trunk_pitch":       {"shaft": "+y", "parent": "-z", "cage": "adapter", "fork": "part"},
    "left_hip_yaw":      {"shaft": "-z", "parent": "+z", "cage": "yaw",     "fork": "adapter", "clock": "flip"},
    "right_hip_yaw":     {"shaft": "-z", "parent": "+z", "cage": "yaw",     "fork": "adapter", "clock": "flip"},
    "left_hip_roll":     {"shaft": "-x", "parent": "+z", "cage": "cluster", "fork": "adapter", "stagger": 35.0},
    "right_hip_roll":    {"shaft": "-x", "parent": "+z", "cage": "cluster", "fork": "adapter", "clock": "flip", "stagger": 35.0},
    "left_hip_pitch":    {"shaft": "+y", "parent": "+z", "cage": "cluster", "fork": "fork", "clock": "flip", "stagger": 30.0},
    "right_hip_pitch":   {"shaft": "-y", "parent": "+z", "cage": "cluster", "fork": "fork", "stagger": 30.0},
    "left_knee_pitch":   {"shaft": "+y", "parent": "+z", "cage": "ortho",   "fork": "fork"},
    "right_knee_pitch":  {"shaft": "-y", "parent": "+z", "cage": "ortho",   "fork": "fork"},
    "left_ankle_pitch":  {"shaft": "+y", "parent": "+z", "cage": "ortho",   "fork": "part"},
    "right_ankle_pitch": {"shaft": "-y", "parent": "+z", "cage": "ortho",   "fork": "part"},
    "left_shoulder_pitch":  {"shaft": "+y", "parent": "-y", "cage": "cluster", "fork": "adapter", "clock": "flip", "stagger": 35.0},
    "right_shoulder_pitch": {"shaft": "-y", "parent": "+y", "cage": "cluster", "fork": "adapter", "clock": "flip", "stagger": 35.0},
    "left_shoulder_roll":   {"shaft": "-x", "parent": "+y", "cage": "cluster", "fork": "fork"},
    "right_shoulder_roll":  {"shaft": "+x", "parent": "-y", "cage": "cluster", "fork": "fork"},
    "left_elbow_pitch":  {"shaft": "+y", "parent": "+z", "cage": "ortho",   "fork": "fork"},
    "right_elbow_pitch": {"shaft": "-y", "parent": "+z", "cage": "ortho",   "fork": "fork"},
    "left_gripper":      {"shaft": "+y", "parent": "+z", "cage": "ortho",   "fork": "part"},
    "right_gripper":     {"shaft": "-y", "parent": "+z", "cage": "ortho",   "fork": "part"},
}

# 每个 link 的"长件"（管/大件），放在 link 位姿上
LINK_BULK: Dict[str, List[Tuple[str, Dict[str, Any]]]] = {
    "pelvis": [("pelvis_frame", {})],
    # ⚠️ electronics_deck 不再装配：加宽后小件直接坐框架层板，插入托盘会与电池抽屉
    #    挤同一层（实测 9 942 mm³）。零件定义保留，待上层布局定了再决定去留。
    "torso_upper": [("torso_frame", {}),
                    ("battery_tray", {}), ("pdb_mount", {}),
                    ("backpack_plate", {})],
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
    "right_foot": [("foot_plate", {"mirror": True})],
    "left_gripper": [("gripper_jaw", {})],
    "right_gripper": [("gripper_jaw", {})],
}

# 紧凑转接块：只留给颈/腰短链（轴距 27.5，不走错轴）
ADAPTERS: Dict[str, Dict[str, Any]] = {
    "head_yaw_link": {"in_shaft": "+z", "out_shaft": "+y", "drop": 27.5},
    "trunk_roll_link": {"in_shaft": "+x", "out_shaft": "+y", "drop": 27.5},
}

# 髋/肩错轴：单侧臂锁上一级舵盘，把下一级轴线拉到 19.6 mm；
# stagger 取被托住的那只舵机（fit_stagger.py 的数，禁止在这里另写一套）。
CLUSTER_ARMS: Dict[str, Dict[str, Any]] = {
    "left_hip_yaw_link": {"in_shaft": "-z", "out_shaft": "-x", "drop": 19.6,
                          "stagger_of": "left_hip_roll"},
    "right_hip_yaw_link": {"in_shaft": "-z", "out_shaft": "-x", "drop": 19.6,
                           "stagger_of": "right_hip_roll"},
    "left_hip_roll_link": {"in_shaft": "-x", "out_shaft": "+y", "drop": 19.6,
                           "stagger_of": "left_hip_pitch"},
    "right_hip_roll_link": {"in_shaft": "-x", "out_shaft": "-y", "drop": 19.6,
                            "stagger_of": "right_hip_pitch"},
    "left_shoulder_pitch_link": {"in_shaft": "+y", "out_shaft": "-x", "drop": 0.0,
                                 "stagger_of": "left_shoulder_roll"},
    "right_shoulder_pitch_link": {"in_shaft": "-y", "out_shaft": "+x", "drop": 0.0,
                                  "stagger_of": "right_shoulder_roll"},
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

    ⚠️ 2026-09-11 两处订正（此前导致整机预览**每个关节都差 90°**并大面积穿模）：
      ① 本函数原按"输出轴沿 +Z"建模，但 `kit.orient()` 的约定是**局部 +Y → 输出轴**、
         +Z → 母端。两者差 90°，22 个关节全错位。
      ② 原按"机身居中"建模，实际**轴心不在长度中点**（距 +X 端面 10.2、距 −X 端面 35.0），
         所以机身相对轴线是偏置的。

    现在的标准姿态（与 `kit.servo_frame()` 同源）：
        X = 机身长度 45.2（轴心在原点 ⇒ x ∈ [−35.0, +10.2]）
        Y = 沿输出轴厚度 35.0（输出端 +Y）；Z = 宽度 24.7
        +Y：Φ20 × 2.5 输出凸台 + Φ5.9 × 1.5 花键
        −Y：Φ6 × 4.1 副轴（官方图纸值；开源模型只建了 0.6）
    """
    f = servo_frame(name)
    part = box(f["len"], f["axial"], f["width"],
               at=((f["x_min"] + f["x_max"]) / 2.0, 0.0, -f["z_half"]))
    # 输出端：凸台 + 花键（花键实际是 25T 齿，干涉检查用包络圆柱代替）
    part = part.union(cyl(f["boss_d"], f["boss_t"],
                          at=(0.0, f["y_half"], 0.0), axis="Y"))
    part = part.union(cyl(f["spline_d"], f["spline_h"],
                          at=(0.0, f["boss_face"], 0.0), axis="Y"))
    # 副轴端：Φ6 副轴（伸向 −Y）
    part = part.union(cyl(f["stub_dia"], f["stub_len"],
                          at=(0.0, -f["y_half"] - f["stub_len"], 0.0), axis="Y"))
    return part


def electronics_placeholder(size: Sequence[float]) -> cq.Workplane:
    """电子件占位体。

    ⚠️ **以几何中心为基准**——必须与调用方语义一致：`build_assembly` 按
    `pos[2] = 层板上表面 + 自身高/2` 落座，`placements.json` 的 `position_mm`
    也按"中心"理解。原来这里是"底面在原点"（`box` 默认），每件都高了半个身位，
    电池顶部因此穿进电控层托盘（9 215 mm³，重合率 49%）。
    """
    return box(size[0], size[1], size[2], at=(0.0, 0.0, -size[2] / 2.0))


# 电子件的摆放姿态（placements.json 只给位置与尺寸，姿态在这里定）
ELEC_ROT_DEG = {"compute": 90.0}      # 树莓派 85 mm 边沿 Y 向（躯干内净空 90）
# 头壳前脸 visor x≈32–38。占位体 8×25×8，厚度沿 X，收在罩内下沿。
ELEC_HEAD = {"mic": (35.0, 0.0, -12.0)}
# 躯干骨架重排（给俯仰叉让位）后，舱内件要落在**各自的那块托盘/仓底**上。
# 托盘上表面（torso 局部坐标，见 skeleton.torso_frame）：
# 托盘上表面（torso 局部坐标，见 skeleton.torso_frame 的绝对布局）
# ⚠️ 这些标高**不再在这里写死**：来自 skeleton 的唯一真值来源
#    （曾因"零件建在 z=0、规则写 42.0+2.6"，导致托盘与电池仓两个打印件自己先撞上）
ELEC_DECK_TOP = {
    "compute": sk.TORSO_DECK_TOP_Z,    # 树莓派**直接坐框架层板**（抬高 3 mm 就会顶到顶环）
    "battery": sk.TORSO_BAY_LOAD_Z,    # 电池坐在抽屉底板的上表面
}

# 容积超额订阅：STM32 / URT-1 / XL4015 / 功放 / 喇叭塞不进躯干（见
# 电子件背挂模块，改挂到躯干背面。
# 这不是"随便挪一下"：躯干内 俯仰叉 32 + 电池 19 + 树莓派 17 = 68 mm，
# 而到 head_yaw 轴线只有 82.4 mm，还要留给颈座与偏转舵机笼。
# 舱内实测（2026-09-11）：下层净高 21.4、上层净高 18.4，7 件里只有两件真塞不下：
#   bec（XL4015，25 mm 高 > 两层净高）、speaker（Φ28，比下层空带宽 2 mm）
# 其余 5 件（电池/树莓派/STM32/URT-1/功放）全部回舱内。背挂件**贴背板安装**：
# 厚度方向朝外（而不是把 65 mm 长边朝外），深度只增加自身厚度。
ELEC_BACKPACK = {
    "bec": 0, "speaker": 1,
}
# 舱内下层两侧空带（电池占 y ±17，加宽后净宽 ±44 → 两条 27 mm 空带）
ELEC_BAY_SIDE = {
    "mcu":          (-22.0, 30.0),
    "servo_driver": (24.0, 30.0),
    "amp":          (-40.0, -30.0),
}
# 背挂件的贴板位置（y 错开，避免 90° 装法下长边互相重叠）
BACKPACK_YZ = {"bec": (0.0, 26.0), "speaker": (-32.0, 10.0)}
BACK_X = 48.0               # 躯干背面（躯干本体 x ∈ [−48, +48]）
BACKPACK_PITCH = 16.0

# 显式声明"就按 placements.json 原始坐标摆、不需要规则"的躯干件（目前为空）。
# 加进来等于签字确认"原始坐标是对的"，避免用沉默掩盖失配。
ELEC_RAW_OK: set = set()

# 稳定 key 解析：显示名 → 短 kind。
# ⚠️ 这条映射是为了兼容"placements.json 的 id 被写成显示名"的历史数据
#    （生成器 design/gen_v2_baseline.py 里本来是短 id，二者脱节过一次）。
ELEC_KIND_HINTS = {
    "compute": ("raspberry", "树莓派"),
    "battery": ("锂聚合物", "battery", "3s"),
    "mcu": ("stm32",),
    "servo_driver": ("urt-1", "总线驱动"),
    "bec": ("xl4015",),
    "amp": ("pam8403",),
    "speaker": ("喇叭",),
    "camera": ("相机",),
    "mic": ("拾音",),
    "imu": ("icm-42688",),
}


def elec_kind(entry: Dict[str, Any]) -> str:
    """把 placements.json 的一条电子件解析成稳定 kind。

    优先级：显式 `kind` → `id` → `name` 里的关键词。
    解析不出来返回空串——调用方必须把它当成**错误**，不能静默跳过。
    """
    for field in ("kind", "id"):
        v = str(entry.get(field, "")).strip()
        if v in ELEC_KIND_HINTS:
            return v
    hay = f"{entry.get('id', '')} {entry.get('name', '')}".lower()
    for kind, words in ELEC_KIND_HINTS.items():
        if any(w in hay for w in words):
            return kind
    return ""


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
        except Exception as cop:  # noqa: BLE001
            fail(f"{link}/compact_adapter", "adapter", cop)

    # --- 2b. 髋/肩错轴单侧臂（锁上一级舵盘，托住错开后的下一级轴线）---
    for link, cfg in CLUSTER_ARMS.items():
        if link not in kin.world:
            continue
        try:
            src = cfg["stagger_of"]
            stagger = float(JOINT_SCHEME[src].get("stagger", 0.0))
            parent_j = link[:-5] if link.endswith("_link") else ""
            parent_stagger = float(JOINT_SCHEME.get(parent_j, {}).get("stagger", 0.0) or 0.0)
            add(f"{link}__cluster_horn_arm",
                _place(sk.build("cluster_horn_arm",
                                in_shaft=cfg["in_shaft"],
                                out_shaft=cfg["out_shaft"],
                                drop=cfg["drop"],
                                stagger=stagger,
                                parent_stagger=parent_stagger),
                       kin.world[link]),
                "cluster_arm")
        except Exception as cop:  # noqa: BLE001
            fail(f"{link}/cluster_horn_arm", "cluster_arm", cop)

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
        elif sc["cage"] == "cluster":
            try:
                par = sc["parent"]
                if par.strip("+-") == sc["shaft"].strip("+-"):
                    par = next(d for d in ("+z", "-z", "+y", "-y", "+x", "-x")
                               if d.strip("+-") != sc["shaft"].strip("+-"))
                add(f"outrigger__{jname}",
                    _place(sk.build("cluster_outrigger",
                                    shaft=sc["shaft"],
                                    parent=par,
                                    stagger=float(sc.get("stagger", 0.0))),
                           m),
                    "cluster")
            except Exception as cop:  # noqa: BLE001
                fail(f"outrigger/{jname}", "cluster", cop)
        if sc["fork"] == "fork":
            try:
                # 肘叉用紧凑型：前臂只有 39.2 mm，标准叉芯棒会顶进夹爪舵机。
                compact = "elbow" in jname
                add(f"fork__{jname}",
                    _place(sk.build("limb_fork", shaft=sc["shaft"],
                                    parent=sc["parent"],
                                    compact=compact,
                                    spigot=not compact), m), "fork")
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
            # 钟点位翻转：舵机两个端面的 4×Φ2.5 是方形（4 重对称），
            # 所以绕自身轴转 180° 不影响拧螺钉，却能把机身 45.2 的长边调头、
            # 避开相邻舵机。取值由 design/cad/fit_clocking.py 求解后写在此表。
            if sc.get("clock") == "flip":
                par = OPP[par]
            body = orient(servo_placeholder(), sc["shaft"], par)
            # stagger：沿自身输出轴平移机体，关节原点不动（fit_stagger.py）
            pose = kin.joint_world(jname)
            st = float(sc.get("stagger", 0.0) or 0.0)
            if abs(st) > 1e-9:
                dx, dy, dz = DIRS[sc["shaft"]]
                pose = mat_mul(pose, mat_trans(dx * st, dy * st, dz * st))
            add(f"servo__{jname}", _place(body, pose), "servo")
        except Exception as exc:  # noqa: BLE001
            fail(f"servo/{jname}", "servo", exc)

    # --- 5. 电子件（host link 位姿 × 局部偏移 × 姿态）---
    for e in placements["electronics"]:
        link = e["link"]
        if link not in kin.world:
            continue
        kind = elec_kind(e)          # 稳定 key：不再依赖"id 里必须写短名"
        # ⚠️ 躯干件必须命中一条摆位规则，否则**直接报错**。
        #    历史 bug：placements.json 的 id 被写成显示名（"Raspberry Pi 4B (4GB)"），
        #    而规则表用短 key（compute/battery/…），于是 7/7 件全部静默停在原始坐标，
        #    正好落进 trunk_pitch 舵机的空间 → 27 683 mm³ 的"假干涉"。
        if link == "torso_upper" and kind not in ELEC_DECK_TOP \
                and kind not in ELEC_BACKPACK and kind not in ELEC_BAY_SIDE \
                and e.get("id") not in ELEC_RAW_OK:
            fail(f"elec/{e.get('id')}", "elec",
                 KeyError(f"躯干电子件 {e.get('id')!r} 没有匹配的摆位规则"
                          f"（解析出 kind={kind!r}）：请补 ELEC_DECK_TOP / "
                          f"ELEC_BACKPACK，或显式加入 ELEC_RAW_OK"))
            continue
        try:
            pos = list(e["position_mm"])
            rot_y = 0.0
            if link == "head" and kind in ELEC_HEAD:
                pos = list(ELEC_HEAD[kind])
            if kind in ELEC_DECK_TOP:
                # 底面坐在托盘上表面：中心 z = 盘面 + 自身高/2
                pos[2] = ELEC_DECK_TOP[kind] + e["size_mm"][2] / 2.0
            elif kind in ELEC_BAY_SIDE:
                # 舱内下层两侧空带（电池旁边），坐在框架层板上
                ox, oy = ELEC_BAY_SIDE[kind]
                pos = [ox, oy, sk.TORSO_BAY_TOP_Z + e["size_mm"][2] / 2.0]
            elif kind in ELEC_BACKPACK:
                # 背挂（贴背板）：厚度方向朝外 → 深度只增加自身厚度
                oy, oz = BACKPACK_YZ[kind]
                pos = [-(BACK_X + e["size_mm"][2] / 2.0), oy, oz]
                rot_y = 90.0
            local = mat_mul(mat_trans(*pos),
                            mat_rpy(0.0, math.radians(rot_y),
                                    math.radians(ELEC_ROT_DEG.get(kind, 0.0))))
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
    ap.add_argument("--no-fit-check", action="store_true",
                    help="跳过装配后的干涉校验（只为快速出图时用）")
    ap.add_argument("--strict", action="store_true",
                    help="出现『摆放错误』级干涉时以非 0 退出（CI 用）")
    ap.add_argument("--fit-threshold", type=float, default=5000.0,
                    help="判定『摆放错误』的相交体积阈值 mm³（默认 5000）")
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

    # ---- 装配后立即校验：把"摆错"从事后体检提前到构建时 ----
    n_bad = 0
    if not args.no_fit_check and items:
        hits = overlap_report(items, threshold=1.0)
        bad_place = [h for h in hits if h["verdict"] == "❌ 摆放错误"]
        n_bad = len(bad_place)
        print(f"\n装配校验：干涉 {len(hits)} 对，其中"
              f"『摆放错误』{n_bad} 对（阈值 {args.fit_threshold:.0f} mm³）")
        for h in bad_place[:10]:
            print(f"  ❌ `{h['a']}` ↔ `{h['b']}`：{h['vol']:.0f} mm³"
                  f"（重合率 {h['frac'] * 100:.0f}%）")
        if n_bad > 10:
            print(f"  …（其余 {n_bad - 10} 对见 audit_assembly.py）")

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
    if bad or (args.strict and n_bad):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
