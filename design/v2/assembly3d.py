"""A 路线三维装配：运动学树 + 零位网格。Z 上 X 前 Y 左，单位 mm。"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Sequence, Tuple

from . import mesh as M
from .layout import SANDWICH, SERVO_AXIAL, horn_center, idle_center
from .plates import Hole, all_plates
from .profile import JOINTS, K, SERVO, PELVIS, CAD_INTERFACE, standing_height_mm

Vec = Tuple[float, float, float]


def m_ident() -> List[float]:
    o = [0.0] * 16
    o[0] = o[5] = o[10] = o[15] = 1.0
    return o


def m_trans(x: float, y: float, z: float) -> List[float]:
    o = m_ident()
    o[12], o[13], o[14] = x, y, z
    return o


def m_axis_angle(ax: Sequence[float], th: float) -> List[float]:
    n = math.sqrt(ax[0] ** 2 + ax[1] ** 2 + ax[2] ** 2) or 1.0
    x, y, z = ax[0] / n, ax[1] / n, ax[2] / n
    c, s, C = math.cos(th), math.sin(th), 1.0 - math.cos(th)
    return [
        x * x * C + c, y * x * C + z * s, z * x * C - y * s, 0.0,
        x * y * C - z * s, y * y * C + c, z * y * C + x * s, 0.0,
        x * z * C + y * s, y * z * C - x * s, z * z * C + c, 0.0,
        0.0, 0.0, 0.0, 1.0,
    ]


def m_mul(a: Sequence[float], b: Sequence[float]) -> List[float]:
    o = [0.0] * 16
    for i in range(4):
        for j in range(4):
            s = 0.0
            for k in range(4):
                s += a[k * 4 + j] * b[i * 4 + k]
            o[i * 4 + j] = s
    return o


def m_apply(m: Sequence[float], p: Vec) -> Vec:
    x, y, z = p
    return (
        m[0] * x + m[4] * y + m[8] * z + m[12],
        m[1] * x + m[5] * y + m[9] * z + m[13],
        m[2] * x + m[6] * y + m[10] * z + m[14],
    )


PELVIS_Z = (
    K["foot_to_ankle_z"] + K["shank"] + K["thigh"] + K["hip_stack_z"]
)

# 两只 3215 轴向 35 mm，堆叠必须让开；头偏航/俯仰之间还要留立柱。
TORSO_UP = PELVIS["trunk_roll_z_mm"] + PELVIS["trunk_pitch_offset_mm"]
HEAD_PITCH_Z = PELVIS["head_pitch_z_mm"]


def kinematic_tree() -> Dict[str, Any]:
    """root = pelvis。joints 顺序 = JOINTS 顺序（滑条下标）。"""
    hw = K["hip_width"] / 2.0
    sw = K["shoulder_width"] / 2.0
    torso_up = TORSO_UP
    sh_z = K["pelvis_to_shoulder_z"] - torso_up  # 32；肩的世界高度仍是骨盆+72
    neck = K["shoulder_to_head_yaw"]
    links = [
        {"name": "pelvis", "parent": ""},
        {"name": "trunk_roll_link", "parent": "pelvis"},
        {"name": "torso", "parent": "trunk_roll_link"},
        {"name": "head_yaw_link", "parent": "torso"},
        {"name": "head", "parent": "head_yaw_link"},
        {"name": "left_hip_roll_link", "parent": "pelvis"},
        {"name": "left_thigh", "parent": "left_hip_roll_link"},
        {"name": "left_shank", "parent": "left_thigh"},
        {"name": "left_foot", "parent": "left_shank"},
        {"name": "right_hip_roll_link", "parent": "pelvis"},
        {"name": "right_thigh", "parent": "right_hip_roll_link"},
        {"name": "right_shank", "parent": "right_thigh"},
        {"name": "right_foot", "parent": "right_shank"},
        {"name": "left_upper", "parent": "torso"},
        {"name": "left_fore", "parent": "left_upper"},
        {"name": "left_hand", "parent": "left_fore"},
        {"name": "right_upper", "parent": "torso"},
        {"name": "right_fore", "parent": "right_upper"},
        {"name": "right_hand", "parent": "right_fore"},
    ]
    spec = [
        ("trunk_roll", "pelvis", "trunk_roll_link", [0, 0, PELVIS["trunk_roll_z_mm"]], [1, 0, 0]),
        ("trunk_pitch", "trunk_roll_link", "torso", [0, 0, PELVIS["trunk_pitch_offset_mm"]], [0, 1, 0]),
        ("head_yaw", "torso", "head_yaw_link", [0, 0, sh_z + neck], [0, 0, 1]),
        ("head_pitch", "head_yaw_link", "head", [0, 0, HEAD_PITCH_Z], [0, 1, 0]),
        ("left_hip_roll", "pelvis", "left_hip_roll_link", [0, hw, 0], [1, 0, 0]),
        ("left_hip_pitch", "left_hip_roll_link", "left_thigh", [0, 0, -K["hip_stack_z"]], [0, 1, 0]),
        ("left_knee_pitch", "left_thigh", "left_shank", [0, 0, -K["thigh"]], [0, 1, 0]),
        ("left_ankle_pitch", "left_shank", "left_foot", [0, 0, -K["shank"]], [0, 1, 0]),
        ("right_hip_roll", "pelvis", "right_hip_roll_link", [0, -hw, 0], [1, 0, 0]),
        ("right_hip_pitch", "right_hip_roll_link", "right_thigh", [0, 0, -K["hip_stack_z"]], [0, 1, 0]),
        ("right_knee_pitch", "right_thigh", "right_shank", [0, 0, -K["thigh"]], [0, 1, 0]),
        ("right_ankle_pitch", "right_shank", "right_foot", [0, 0, -K["shank"]], [0, 1, 0]),
        ("left_shoulder_pitch", "torso", "left_upper", [0, sw, sh_z], [0, 1, 0]),
        ("left_shoulder_roll", "left_upper", "left_fore", [0, 44, 0], [1, 0, 0]),
        ("left_elbow_pitch", "left_fore", "left_hand", [0, 0, -K["upper_arm"]], [0, 1, 0]),
        ("left_gripper", "left_hand", "left_hand", [0, 0, -K["forearm"]], [1, 0, 0]),
        ("right_shoulder_pitch", "torso", "right_upper", [0, -sw, sh_z], [0, 1, 0]),
        ("right_shoulder_roll", "right_upper", "right_fore", [0, -44, 0], [1, 0, 0]),
        ("right_elbow_pitch", "right_fore", "right_hand", [0, 0, -K["upper_arm"]], [0, 1, 0]),
        ("right_gripper", "right_hand", "right_hand", [0, 0, -K["forearm"]], [1, 0, 0]),
    ]
    # gripper 不能 parent=child。给手爪单独 link。
    links.append({"name": "left_grip", "parent": "left_hand"})
    links.append({"name": "right_grip", "parent": "right_hand"})
    spec[15] = ("left_gripper", "left_hand", "left_grip", [0, 0, -K["forearm"]], [1, 0, 0])
    spec[19] = ("right_gripper", "right_hand", "right_grip", [0, 0, -K["forearm"]], [1, 0, 0])

    name_to_j = {j["name"]: j for j in JOINTS}
    joints = []
    for name, parent, child, xyz, axis in spec:
        axis=CAD_INTERFACE['joint_axis_overrides'].get(name,axis)
        lim = name_to_j[name]["limit_deg"]
        joints.append({
            "name": name,
            "parent": parent,
            "child": child,
            "xyz": [float(v) for v in xyz],
            "rpy": [0.0, 0.0, 0.0],
            "axis": [float(v) for v in axis],
            "limit_deg": list(lim),
            "group": name_to_j[name]["group"],
        })
    return {
        "root": "pelvis",
        "root_xyz": [0.0, 0.0, PELVIS_Z],
        "links": links,
        "joints": joints,
        "height_mm": standing_height_mm(),
    }


def fk(tree: Dict[str, Any], angles_deg: Sequence[float] | None = None) -> Dict[str, List[float]]:
    joints = tree["joints"]
    if angles_deg is None:
        angles_deg = [0.0] * len(joints)
    W: Dict[str, List[float]] = {tree["root"]: m_trans(*tree["root_xyz"])}
    for i, j in enumerate(joints):
        th = float(angles_deg[i]) * math.pi / 180.0
        o = m_trans(*j["xyz"])
        if abs(th) > 1e-12:
            o = m_mul(o, m_axis_angle(j["axis"], th))
        W[j["child"]] = m_mul(W[j["parent"]], o)
    return W


def _servo(axis: Sequence[float]) -> M.Mesh:
    return M.servo_sts3215(M.axis_of(axis))


def _plate_on_axis(axis: Sequence[float], t: float, s: float, r: float = 3.0) -> M.Mesh:
    ax = M.axis_of(axis)
    if ax == "y":
        return M.rounded_box(s, t, s, r=r, axis="y")
    if ax == "x":
        return M.rounded_box(t, s, s, r=r, axis="x")
    return M.rounded_box(s, s, t, r=r, axis="z")


KINDS = {
    "connector_metal": {"label":"连接器金属外壳", "color":[175,180,184], "metal":0.9, "rough":0.3},
    "connector_white": {"label":"连接器绝缘壳", "color":[230,229,219], "metal":0.0, "rough":0.5},
    "strap": {"label":"电池魔术贴绑带", "color":[24,24,24], "metal":0.0, "rough":0.9},
    "optical": {"label":"镜头", "color":[20,24,30], "metal":0.3, "rough":0.2},
    "electronics_case": {"label":"电子件外形包络", "color":[45,45,48], "metal":0.0, "rough":0.5},
    "al": {"label": "铝合金夹层", "color": [186, 196, 206], "metal": 0.92, "rough": 0.28},
    "servo": {"label": "STS3215 舵机", "color": [42, 44, 48], "metal": 0.18, "rough": 0.42},
    "petg": {"label": "PETG 哑光白", "color": [232, 232, 230], "metal": 0.0, "rough": 0.62},
    "tpu": {"label": "TPU 鞋底", "color": [28, 28, 32], "metal": 0.0, "rough": 0.78},
    "elec": {"label": "电池", "color": [210, 128, 42], "metal": 0.12, "rough": 0.48},
    "pcb": {"label": "PCB", "color": [28, 92, 46], "metal": 0.08, "rough": 0.48},
    "horn": {"label": "25T 金属舵盘", "color": [212, 176, 64], "metal": 0.95, "rough": 0.22},
    "fastener": {"label": "M2/M2.5/M3 紧固件", "color": [150, 152, 156], "metal": 0.88, "rough": 0.32},
    "standoff": {"label": "标准隔离柱", "color": [196, 118, 48], "metal": 0.92, "rough": 0.38},
    "cable": {"label": "总线 / USB", "color": [28, 28, 30], "metal": 0.05, "rough": 0.72},
}


def build_parts() -> List[Dict[str, Any]]:
    tree = kinematic_tree()
    by_name = {j["name"]: j for j in tree["joints"]}
    parts: List[Dict[str, Any]] = []

    def add(name: str, link: str, kind: str, msh: M.Mesh, alpha: float = 1.0) -> None:
        parts.append({
            "name": name,
            "link": link,
            "kind": kind,
            "alpha": alpha,
            "verts": [round(v, 3) for v in msh.verts],
        })

    plates = {p.name: p for p in all_plates()}

    def plate_named(name: str, axis: str, center: Vec) -> M.Mesh:
        p = plates[name]
        return M.plate_mesh(p.outline, p.thickness_mm, p.holes, axis=axis, center=center)

    def pcd_screws(axis: Sequence[float], origin: Vec, link: str, tag: str) -> None:
        s = 4.95  # 9.90 方阵 / 2 = PCD14 上的 M2.5
        ax = M.axis_of(axis)
        for i, (u, v) in enumerate(((s, s), (s, -s), (-s, s), (-s, -s))):
            if ax == "y":
                c = (origin[0] + u, origin[1], origin[2] + v)
                sc = M.cylinder(1.15, 8.0, "y", 8, c)
                hd = M.cylinder(2.2, 1.6, "y", 8, (c[0], c[1] + 4.0, c[2]))
            elif ax == "x":
                c = (origin[0], origin[1] + u, origin[2] + v)
                sc = M.cylinder(1.15, 8.0, "x", 8, c)
                hd = M.cylinder(2.2, 1.6, "x", 8, (c[0] + 4.0, c[1], c[2]))
            else:
                c = (origin[0] + u, origin[1] + v, origin[2])
                sc = M.cylinder(1.15, 8.0, "z", 8, c)
                hd = M.cylinder(2.2, 1.6, "z", 8, (c[0], c[1], c[2] + 4.0))
            add(f"screw-{tag}-{i}", link, "fastener", sc)
            add(f"screwhead-{tag}-{i}", link, "fastener", hd)

    for j in tree["joints"]:
        ax = M.axis_of(j["axis"])
        jx, jy, jz = j["xyz"]
        sm = _servo(j["axis"])
        if j["name"] in CAD_INTERFACE["housing_clock_deg"]:
            sm = M.Mesh_rotated(sm, j["axis"], math.radians(CAD_INTERFACE["housing_clock_deg"][j["name"]]))
        if j["name"] in PELVIS["housing_clock_deg"]:
            sm = M.Mesh_rotated(sm, j["axis"], math.radians(PELVIS["housing_clock_deg"][j["name"]]))
        add(f"servo-{j['name']}", j["parent"], "servo", sm.translated(jx, jy, jz))
        hc = horn_center(j["axis"])
        pelvis_output = j["name"] in PELVIS["housing_clock_deg"]
        if pelvis_output:
            hc = (PELVIS["front_horn_inner_mm"] + PELVIS["horn_t_mm"] / 2, 0.0, 0.0)
        add(f"horn-{j['name']}", j["child"], "horn", M.horn_disc(ax).translated(*hc))
        if not pelvis_output:
            pcd_screws(j["axis"], hc, j["child"], f"h-{j['name']}")
        # 髋横滚/躯干横滚共用骨盆夹层，不再单独贴 idle（会和夹板对穿）。
        if j["name"] not in ("left_hip_roll", "right_hip_roll", "trunk_roll"):
            idle = plate_named("IDLE-PLATE", "z", (0.0, 0.0, 0.0))
            ic = idle_center(j["axis"])
            idle = M.orient_z_to_axis(idle, j["axis"]).translated(ic[0] + jx, ic[1] + jy, ic[2] + jz)
            add(f"idle-{j['name']}", j["parent"], "al", idle)
            pcd_screws(
                j["axis"],
                (ic[0] + jx, ic[1] + jy, ic[2] + jz),
                j["parent"],
                f"i-{j['name']}",
            )

    def side_arms(plate_name: str, length: float, link: str, tag: str) -> None:
        base = M.limb_side_plate(plate_named(plate_name, "z", (0.0, 0.0, 0.0)))
        for side, sy in (("a", SANDWICH), ("b", -SANDWICH)):
            add(f"c-{tag}-{side}", link, "al", base.translated(0.0, sy, -length / 2.0))

    side_arms("C-ARM-THIGH", K["thigh"], "left_thigh", "thigh-l")
    side_arms("C-ARM-SHANK", K["shank"], "left_shank", "shank-l")
    side_arms("C-ARM-THIGH", K["thigh"], "right_thigh", "thigh-r")
    side_arms("C-ARM-SHANK", K["shank"], "right_shank", "shank-r")
    side_arms("C-ARM-UPPER", K["upper_arm"], "left_fore", "upper-l")
    side_arms("C-ARM-FOREARM", K["forearm"], "left_hand", "fore-l")
    side_arms("C-ARM-UPPER", K["upper_arm"], "right_fore", "upper-r")
    side_arms("C-ARM-FOREARM", K["forearm"], "right_hand", "fore-r")

    # Manufacturing solids are also the source of the review meshes.
    import json
    from pathlib import Path
    pelvis_cache = Path(__file__).parent / "out" / "pelvis-revision" / "meshes.json"
    if not pelvis_cache.is_file():
        raise RuntimeError("Generate pelvis geometry with .venv-cad: python -m v2.pelvis_cad")
    from .geometry_cache import pelvis_source_hash
    source_record = pelvis_cache.with_name("geometry-source.json")
    if not source_record.is_file() or json.loads(source_record.read_text())["sha256"] != pelvis_source_hash():
        raise RuntimeError("Stale pelvis geometry: regenerate with .venv-cad/bin/python -m v2.pelvis_cad")
    parts.extend(json.loads(pelvis_cache.read_text()))
    # 胸腔是立柱笼子，不是 100×95 水平层板。
    add("torso-floor", "torso", "al", M.rounded_box(76, 56, 1.5, r=3.0, segs=3, center=(0, 0, 14)))
    sh_z = K["pelvis_to_shoulder_z"] - TORSO_UP
    add("shoulder-bar", "torso", "al", M.rounded_box(12, 112, 8, r=2.0, segs=2, center=(0, 0, sh_z)))
    post_h, post_z = 50.0, 38.0
    for name, xy in (
        ("torso-post-l", (22.0, 30.0)),
        ("torso-post-r", (22.0, -30.0)),
        ("torso-post-fl", (-22.0, 30.0)),
        ("torso-post-fr", (-22.0, -30.0)),
    ):
        add(name, "torso", "al", M.rounded_box(8, 8, post_h, r=1.0, segs=2, center=(xy[0], xy[1], post_z)))
    add("torso-rib-f", "torso", "al", M.rounded_box(1.5, 52, 36, r=1.0, segs=2, center=(26, 0, 36), axis="x"))
    add("torso-rib-b", "torso", "al", M.rounded_box(1.5, 52, 36, r=1.0, segs=2, center=(-26, 0, 36), axis="x"))
    # 偏航舵盘 → 底板（PCD14）→ 两侧夹板 → 俯仰舵机。立柱不再是实心方棒。
    add("neck-column", "head_yaw_link", "al", plate_named("HEAD-BRACKET", "z", (0.0, 0.0, 22.25)))
    neck_h = HEAD_PITCH_Z - 22.0
    for side, sy in (("a", SANDWICH), ("b", -SANDWICH)):
        add(
            f"neck-side-{side}",
            "head_yaw_link",
            "al",
            M.rounded_box(28, 1.5, neck_h, r=1.2, segs=2, center=(0.0, sy, 22.0 + neck_h / 2.0), axis="y"),
        )
    add("head-bracket", "head_yaw_link", "al", plate_named("HEAD-BRACKET", "z", (0.0, 0.0, HEAD_PITCH_Z)))

    foot_c = (K["foot_l"] / 2 - K["ankle_from_heel"], 0.0, -K["foot_to_ankle_z"] + 3.0)
    add("foot-l", "left_foot", "al", plate_named("FOOT", "z", foot_c))
    add("foot-r", "right_foot", "al", plate_named("FOOT", "z", foot_c))
    sole = M.rounded_box(K["foot_l"] - 2, K["foot_w"] - 2, K["sole_t"], r=6.0, segs=5,
                         center=(foot_c[0], 0.0, -K["foot_to_ankle_z"] + K["sole_t"] / 2), axis="z")
    add("sole-l", "left_foot", "tpu", sole)
    add("sole-r", "right_foot", "tpu", sole)

    add("cover-torso-l", "torso", "petg",
        M.rounded_box(78, 2.4, 50, r=4.0, segs=4, center=(2, 38, 38), axis="y"), 1.0)
    add("cover-torso-r", "torso", "petg",
        M.rounded_box(78, 2.4, 50, r=4.0, segs=4, center=(2, -38, 38), axis="y"), 1.0)
    add("cover-torso-f", "torso", "petg",
        M.rounded_box(2.4, 72, 50, r=4.0, segs=4, center=(28, 0, 38), axis="x"), 1.0)
    add("cover-torso-b", "torso", "petg",
        M.plate_mesh(
            M.round_rect_pts(72, 50, 4.0, 4),
            2.4,
            [Hole(-29.0, -8.0, 2.7, "pi"), Hole(29.0, -8.0, 2.7, "pi"),
             Hole(-29.0, 16.0, 2.7, "pi"), Hole(29.0, 16.0, 2.7, "pi"),
             Hole(0.0, -20.0, 8.0, "cable_neck")],
            axis="x",
            center=(-28.0, 0.0, 38.0),
        ), 1.0)
    add("cover-pelvis", "pelvis", "petg",
        M.rounded_box(44, 24, 2.4, r=3.0, segs=4, center=(0, 0, -16), axis="z"), 1.0)
    # 头壳：五片 2.4 mm 壁。前脸 Φ10 镜头孔，后脸 CSI 孔，底部给俯仰舵机。
    add("cover-head", "head", "petg",
        M.rounded_box(32, 2.4, 20, r=3.0, segs=4, center=(0, 15, 26), axis="y"), 1.0)
    add("cover-head-r", "head", "petg",
        M.rounded_box(32, 2.4, 20, r=3.0, segs=4, center=(0, -15, 26), axis="y"), 1.0)
    add("cover-head-t", "head", "petg",
        M.rounded_box(32, 32, 2.4, r=4.0, segs=4, center=(0, 0, 36), axis="z"), 1.0)
    add(
        "cover-head-f",
        "head",
        "petg",
        M.plate_mesh(
            M.round_rect_pts(32, 24, 4.0, 4),
            2.4,
            [Hole(0.0, 0.0, 10.0, "camera")],
            axis="x",
            center=(20.0, 0.0, 28.0),
        ),
        1.0,
    )
    add(
        "cover-head-b",
        "head",
        "petg",
        M.plate_mesh(
            M.round_rect_pts(32, 20, 3.0, 4),
            2.4,
            [Hole(0.0, -6.0, 8.0, "csi")],
            axis="x",
            center=(-16.0, 0.0, 26.0),
        ),
        1.0,
    )
    add("neck-collar", "head", "petg",
        M.rounded_box(30, 28, 4, r=3.0, segs=4, center=(0, 0, 16), axis="z"), 1.0)
    add("gland-neck", "torso", "petg", M.cylinder(4.0, 3.0, "z", 10, (0.0, 18.0, 62.0)))
    add("gland-leg-l", "pelvis", "petg", M.cylinder(3.5, 3.0, "z", 10, (0.0, 28.0, -18.0)))
    add("gland-leg-r", "pelvis", "petg", M.cylinder(3.5, 3.0, "z", 10, (0.0, -28.0, -18.0)))

    def channel(name: str, link: str, length: float) -> None:
        add(
            name,
            link,
            "petg",
            M.rounded_box(3.2, 8.0, length - 36.0, r=1.2, segs=3, center=(16.0, 0.0, -length / 2.0)),
        )

    channel("channel-thigh-l", "left_thigh", K["thigh"])
    channel("channel-shank-l", "left_shank", K["shank"])
    channel("channel-thigh-r", "right_thigh", K["thigh"])
    channel("channel-shank-r", "right_shank", K["shank"])
    channel("channel-upper-l", "left_fore", K["upper_arm"])
    channel("channel-fore-l", "left_hand", K["forearm"])
    channel("channel-upper-r", "right_fore", K["upper_arm"])
    channel("channel-fore-r", "right_hand", K["forearm"])

    add("battery", "torso", "elec", M.rounded_box(48, 24, 16, r=2.0, segs=3, center=(0, 0, 22)))
    # Pi 4B 官方 85×56，孔距 58×49；背挂在胸腔后。细模由 vendor STL 替换。
    add("sbc", "torso", "pcb", M.rounded_box(56, 85, 1.6, r=1.5, segs=2, center=(-36, 0, 48)))
    add("sbc-soc", "torso", "elec", M.rounded_box(16, 16, 1.2, r=0.4, segs=2, center=(-34, 8, 52)))
    add("sbc-gpio", "torso", "servo", M.rounded_box(5, 51, 8.5, r=0.4, segs=2, center=(-42, 0, 58)))
    add("sbc-usb3", "torso", "al", M.rounded_box(17, 15, 16, r=0.6, segs=2, center=(-36, 32, 22)))
    add("sbc-usb2", "torso", "al", M.rounded_box(17, 13, 16, r=0.6, segs=2, center=(-36, 18, 22)))
    add("sbc-eth", "torso", "elec", M.rounded_box(21, 16, 14, r=0.6, segs=2, center=(-36, -22, 22)))
    add("sbc-usbc", "torso", "al", M.rounded_box(9, 9, 3.2, r=0.4, segs=2, center=(-36, -28, 70)))
    add("sbc-hdmi0", "torso", "al", M.rounded_box(8, 7, 3.2, r=0.3, segs=2, center=(-36, -12, 58)))
    add("sbc-hdmi1", "torso", "al", M.rounded_box(8, 7, 3.2, r=0.3, segs=2, center=(-36, 4, 58)))
    # Camera Module 3：镜头 +X 穿头壳，PCB 在壳内，CSI 座朝下进脖子。
    add("camera", "head", "pcb", M.rounded_box(1.0, 25, 24, r=0.6, segs=2, center=(18, 0, 28), axis="x"))
    add("cam-sensor", "head", "servo", M.rounded_box(2.0, 8, 8, r=0.4, segs=2, center=(19.5, 0, 28)))
    add("lens", "head", "elec", M.cylinder(4.0, 6.0, "x", 16, (22, 0, 28)))
    add("cam-csi", "head", "pcb", M.rounded_box(3.0, 21, 8, r=0.4, segs=2, center=(16, 0, 16)))
    add("cam-flex", "head", "pcb", M.rounded_box(0.4, 16, 24, r=0.2, segs=2, center=(16, 0, 4), axis="x"))

    def bus(name: str, link: str, a: Tuple[float, float, float], b: Tuple[float, float, float]) -> None:
        add(name, link, "cable", M.cylinder_between(a, b, 1.6, 8))

    # STS3215 总线沿夹板空档；先穿线再上盖（Open Duck 小腿顺序）。
    bus("cable-thigh-l", "left_thigh", (8.0, 0.0, -4.0), (8.0, 0.0, -K["thigh"] + 4.0))
    bus("cable-shank-l", "left_shank", (8.0, 0.0, -4.0), (8.0, 0.0, -K["shank"] + 4.0))
    bus("cable-thigh-r", "right_thigh", (8.0, 0.0, -4.0), (8.0, 0.0, -K["thigh"] + 4.0))
    bus("cable-shank-r", "right_shank", (8.0, 0.0, -4.0), (8.0, 0.0, -K["shank"] + 4.0))
    bus("cable-upper-l", "left_fore", (8.0, 0.0, -4.0), (8.0, 0.0, -K["upper_arm"] + 4.0))
    bus("cable-fore-l", "left_hand", (8.0, 0.0, -4.0), (8.0, 0.0, -K["forearm"] + 4.0))
    bus("cable-upper-r", "right_fore", (8.0, 0.0, -4.0), (8.0, 0.0, -K["upper_arm"] + 4.0))
    bus("cable-fore-r", "right_hand", (8.0, 0.0, -4.0), (8.0, 0.0, -K["forearm"] + 4.0))
    bus("cable-hip-l", "left_hip_roll_link", (8.0, 0.0, -2.0), (8.0, 0.0, -K["hip_stack_z"] + 2.0))
    bus("cable-hip-r", "right_hip_roll_link", (8.0, 0.0, -2.0), (8.0, 0.0, -K["hip_stack_z"] + 2.0))
    bus("cable-csi-head", "head", (16.0, 0.0, 12.0), (0.0, 0.0, 2.0))
    bus("cable-csi-neck", "head_yaw_link", (0.0, 8.0, HEAD_PITCH_Z - 4.0), (0.0, 8.0, 8.0))
    bus("cable-csi-torso", "torso", (0.0, 18.0, 62.0), (-28.0, 12.0, 52.0))
    bus("cable-pwr", "torso", (0.0, 0.0, 30.0), (0.0, 0.0, 14.0))
    bus("cable-bus-pelvis", "pelvis", (0.0, 0.0, 8.0), (0.0, 28.0, -8.0))
    bus("cable-bus-pelvis-r", "pelvis", (0.0, 0.0, 8.0), (0.0, -28.0, -8.0))
    bus("cable-shoulder-l", "torso", (0.0, 20.0, 32.0), (0.0, K["shoulder_width"] / 2.0 - 8.0, 32.0))
    bus("cable-shoulder-r", "torso", (0.0, -20.0, 32.0), (0.0, -K["shoulder_width"] / 2.0 + 8.0, 32.0))

    for tag, link in (("l", "left_foot"), ("r", "right_foot")):
        for sy, side in ((SANDWICH, "a"), (-SANDWICH, "b")):
            add(
                f"foot-upright-{tag}-{side}",
                link,
                "al",
                M.rounded_box(32, 1.5, 28, r=1.2, segs=2, center=(4.0, sy, -8.0), axis="y"),
            )
        add(
            f"foot-heel-{tag}",
            link,
            "al",
            M.rounded_box(1.5, 26, 16, r=1.0, segs=2, center=(-12.0, 0.0, -12.0), axis="x"),
        )

    gz = -K["forearm"]
    for tag, hand, grip in (
        ("l", "left_hand", "left_grip"),
        ("r", "right_hand", "right_grip"),
    ):
        for sy, side in ((SANDWICH, "a"), (-SANDWICH, "b")):
            add(
                f"wrist-{tag}-{side}",
                hand,
                "al",
                M.rounded_box(28, 1.5, 24, r=1.2, segs=2, center=(0.0, 24.0 if sy > 0 else -24.0, gz), axis="y"),
            )
        add(f"palm-{tag}", grip, "petg", M.rounded_box(14, 22, 10, r=2.0, center=(30, 0, -6)))
        add(f"finger-{tag}-a", grip, "petg", M.rounded_box(7, 5, 32, r=1.6, center=(30, 9, -24)))
        add(f"finger-{tag}-b", grip, "petg", M.rounded_box(7, 5, 32, r=1.6, center=(30, -9, -24)))
        add(f"pad-{tag}-a", grip, "tpu", M.rounded_box(6, 3, 10, r=1.0, center=(33, 9, -36)))
        add(f"pad-{tag}-b", grip, "tpu", M.rounded_box(6, 3, 10, r=1.0, center=(33, -9, -36)))

    add("ground", "", "tpu", M.box(520, 380, 2, (40, 0, -1)), 0.22)

    _ = by_name
    return parts


def bbox_world(parts: List[Dict[str, Any]], tree: Dict[str, Any]) -> List[float]:
    W = fk(tree)
    xs: List[float] = []
    ys: List[float] = []
    zs: List[float] = []
    for p in parts:
        w = W.get(p["link"], m_ident()) if p["link"] else m_ident()
        v = p["verts"]
        for i in range(0, len(v), 6):
            x, y, z = m_apply(w, (v[i], v[i + 1], v[i + 2]))
            xs.append(x)
            ys.append(y)
            zs.append(z)
    return [min(xs), min(ys), min(zs), max(xs), max(ys), max(zs)]


def preview_payload(parts=None) -> Dict[str, Any]:
    tree = kinematic_tree()
    parts = build_parts() if parts is None else parts
    W0 = fk(tree)
    links_meta = []
    for lk in tree["links"]:
        w = W0.get(lk["name"], m_ident())
        # inv0: 几何已在 link 局部，零位世界 = W0。JS 用 W_q * I = W_q
        links_meta.append({"name": lk["name"], "zero": m_ident(), "inv0": m_ident()})
    # 零件几何在 link 局部，模型矩阵就是 W_q(link)。root pelvis 需要 W。
    # JS: MLINK = W * inv0。令 zero=W0, inv0=inv(W0) 则零位 M=I...
    # 我们的几何是 link 局部，应 M = W_q。令 inv0 = I, 但 W_root 不是 I。
    # 所以 links[].zero 未用；JS 现有公式 M = W * inv0。设 inv0=I 则 M=W。正确。
    return {
        "title": "ATRI-v2 A路线 铝夹层",
        "root": tree["root"],
        "root_xyz": tree["root_xyz"],
        "links": [{"name": lk["name"], "inv0": m_ident()} for lk in tree["links"]],
        "joints": tree["joints"],
        "fkOrder": list(range(len(tree["joints"]))),
        "parts": parts,
        "kinds": [{"kind": k, **v} for k, v in KINDS.items()],
        "bbox": bbox_world(parts, tree),
        "nTri": sum(len(p["verts"]) // 18 for p in parts),
    }
