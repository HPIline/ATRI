#!/usr/bin/env python3
"""ATRI-v2 URDF → Webots R2025a world (import / kinematics smoke test).

Not a G4 / T1–T5 / hardware gate. Nested HingeJoint Robot, motor names = URDF
joint names, STL visuals scaled mm→m, masses from URDF allocations.

Layout (all under design/v2/out/webots, never out/sim — CAD export rmtree's that):

    out/webots/atri_v2.urdf
    out/webots/meshes/<link>.stl
    out/webots/worlds/atri_v2.wbt
    out/webots/controllers/atri_v2_import_check/atri_v2_import_check.py
    out/webots/urdf-meta.json
    out/webots/import-report.json   (written by the Supervisor)
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import struct
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SIM_URDF = HERE / "out" / "sim" / "atri_v2.urdf"
SIM_MESHES = HERE / "out" / "sim" / "meshes"
SIM_ZIP = HERE / "out" / "packages" / "ATRI-v2-simulation-review.zip"
OUT = HERE / "out" / "webots"
WORLD_VERSION = "R2025a"
BASIC_TIME_STEP = 32
JOINT_DAMPING = 0.5
MESH_SCALE = 0.001  # URDF STL is millimetres
MASS_ABSURD_HI = 20.0
MASS_ABSURD_LO = 1e-6


def num(value: float) -> str:
    if not math.isfinite(float(value)):
        raise ValueError(f"non-finite number {value}")
    if float(value) == int(value) and abs(value) < 1e12:
        return str(int(value))
    text = f"{float(value):.10f}".rstrip("0").rstrip(".")
    return text if text not in ("", "-0") else "0"


def vec(values: Sequence[float]) -> str:
    return " ".join(num(v) for v in values)


def vclose(a: Sequence[float], b: Sequence[float], tol: float = 1e-6) -> bool:
    if len(a) != len(b):
        return False
    return all(abs(float(x) - float(y)) <= tol for x, y in zip(a, b))


def parse_floats(text: str, n: int) -> List[float]:
    parts = (text or "").split()
    if len(parts) != n:
        raise ValueError(f"expected {n} floats, got {text!r}")
    return [float(p) for p in parts]


def rpy_to_axis_angle(rpy: Sequence[float]) -> Optional[List[float]]:
    """URDF RPY (Rz*Ry*Rx) → Webots SFRotation. None means identity (omit)."""
    roll, pitch, yaw = (float(v) for v in rpy)
    if abs(roll) + abs(pitch) + abs(yaw) < 1e-12:
        return None
    cr, sr = math.cos(roll), math.sin(roll)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cy, sy = math.cos(yaw), math.sin(yaw)
    # R = Rz(yaw) @ Ry(pitch) @ Rx(roll)
    r00 = cy * cp
    r01 = cy * sp * sr - sy * cr
    r02 = cy * sp * cr + sy * sr
    r10 = sy * cp
    r11 = sy * sp * sr + cy * cr
    r12 = sy * sp * cr - cy * sr
    r20 = -sp
    r21 = cp * sr
    r22 = cp * cr
    trace = r00 + r11 + r22
    cos_a = max(-1.0, min(1.0, (trace - 1.0) * 0.5))
    angle = math.acos(cos_a)
    if angle < 1e-12:
        return None
    if abs(angle - math.pi) < 1e-6:
        xx = max(0.0, (r00 + 1.0) * 0.5)
        yy = max(0.0, (r11 + 1.0) * 0.5)
        zz = max(0.0, (r22 + 1.0) * 0.5)
        axis = [math.sqrt(xx), math.sqrt(yy), math.sqrt(zz)]
        nrm = math.sqrt(sum(c * c for c in axis)) or 1.0
        return [axis[0] / nrm, axis[1] / nrm, axis[2] / nrm, angle]
    s = 2.0 * math.sin(angle)
    axis = [(r21 - r12) / s, (r02 - r20) / s, (r10 - r01) / s]
    nrm = math.sqrt(sum(c * c for c in axis)) or 1.0
    return [axis[0] / nrm, axis[1] / nrm, axis[2] / nrm, angle]


def stl_aabb_m(path: Path) -> Optional[Tuple[List[float], List[float]]]:
    """Return (center_m, size_m) of a binary/ASCII STL, or None."""
    data = path.read_bytes()
    if len(data) < 84:
        return None
    lo = [math.inf, math.inf, math.inf]
    hi = [-math.inf, -math.inf, -math.inf]

    def acc(x: float, y: float, z: float) -> None:
        lo[0] = min(lo[0], x); lo[1] = min(lo[1], y); lo[2] = min(lo[2], z)
        hi[0] = max(hi[0], x); hi[1] = max(hi[1], y); hi[2] = max(hi[2], z)

    ntri = struct.unpack_from("<I", data, 80)[0]
    if 84 + ntri * 50 == len(data) and ntri > 0:
        off = 84
        for _ in range(ntri):
            _n, x1, y1, z1, x2, y2, z2, x3, y3, z3 = struct.unpack_from("<10f", data, off)
            acc(x1, y1, z1); acc(x2, y2, z2); acc(x3, y3, z3)
            off += 50
    else:
        text = data.decode("utf-8", "ignore")
        found = False
        for line in text.splitlines():
            s = line.strip()
            if s.startswith("vertex"):
                parts = s.split()
                if len(parts) >= 4:
                    acc(float(parts[1]), float(parts[2]), float(parts[3]))
                    found = True
        if not found:
            return None
    if not math.isfinite(lo[0]) or not math.isfinite(hi[0]):
        return None
    size = [(hi[i] - lo[i]) * MESH_SCALE for i in range(3)]
    center = [((hi[i] + lo[i]) * 0.5) * MESH_SCALE for i in range(3)]
    for i in range(3):
        if size[i] < 1e-5:
            size[i] = 0.01
            center[i] = 0.0
    return center, size


def parse_urdf(path: Path) -> Dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    comments = [c.strip() for c in _xml_comments(raw)]
    root_xyz_mm = [0.0, 0.0, 232.0]
    for c in comments:
        if "root_xyz_mm=" in c:
            quoted = c.split("root_xyz_mm=", 1)[1].strip().strip('"').split()
            if len(quoted) == 3:
                root_xyz_mm = [float(quoted[0]), float(quoted[1]), float(quoted[2])]
    tree = ET.parse(path)
    robot = tree.getroot()
    links: Dict[str, Dict[str, Any]] = {}
    for link in robot.findall("link"):
        name = link.get("name") or ""
        vis = link.find("visual")
        mesh_el = None if vis is None else vis.find("geometry/mesh")
        mesh_name = None
        scale = [MESH_SCALE, MESH_SCALE, MESH_SCALE]
        if mesh_el is not None:
            fn = mesh_el.get("filename") or ""
            mesh_name = Path(fn.replace("\\", "/")).name
            if mesh_el.get("scale"):
                scale = parse_floats(mesh_el.get("scale") or "", 3)
        color = [0.55, 0.62, 0.72]
        col = None if vis is None else vis.find("material/color")
        if col is not None and col.get("rgba"):
            rgba = parse_floats(col.get("rgba") or "", 4)
            color = rgba[:3]
        inertial = link.find("inertial")
        mass = 0.0
        com = [0.0, 0.0, 0.0]
        inertia = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        if inertial is not None:
            m = inertial.find("mass")
            if m is not None:
                mass = float(m.get("value") or 0)
            org = inertial.find("origin")
            if org is not None and org.get("xyz"):
                com = parse_floats(org.get("xyz") or "0 0 0", 3)
            inn = inertial.find("inertia")
            if inn is not None:
                inertia = [
                    float(inn.get("ixx") or 0),
                    float(inn.get("iyy") or 0),
                    float(inn.get("izz") or 0),
                    float(inn.get("ixy") or 0),
                    float(inn.get("ixz") or 0),
                    float(inn.get("iyz") or 0),
                ]
        links[name] = {
            "name": name,
            "mesh": mesh_name,
            "scale": scale,
            "color": color,
            "mass": mass,
            "com": com,
            "inertia": inertia,  # ixx iyy izz ixy ixz iyz
        }
    joints: List[Dict[str, Any]] = []
    for joint in robot.findall("joint"):
        jtype = joint.get("type") or ""
        name = joint.get("name") or ""
        parent = (joint.find("parent").get("link") if joint.find("parent") is not None else "")
        child = (joint.find("child").get("link") if joint.find("child") is not None else "")
        org = joint.find("origin")
        xyz = parse_floats(org.get("xyz") or "0 0 0", 3) if org is not None else [0.0, 0.0, 0.0]
        rpy = parse_floats(org.get("rpy") or "0 0 0", 3) if org is not None else [0.0, 0.0, 0.0]
        axis_el = joint.find("axis")
        axis = parse_floats(axis_el.get("xyz") or "0 0 1", 3) if axis_el is not None else [0.0, 0.0, 1.0]
        lim = joint.find("limit")
        lower = float(lim.get("lower") or 0) if lim is not None else 0.0
        upper = float(lim.get("upper") or 0) if lim is not None else 0.0
        effort = float(lim.get("effort") or 10) if lim is not None else 10.0
        velocity = float(lim.get("velocity") or 10) if lim is not None else 10.0
        joints.append({
            "name": name,
            "type": jtype,
            "parent": parent,
            "child": child,
            "xyz": xyz,
            "rpy": rpy,
            "axis": axis,
            "lower": lower,
            "upper": upper,
            "effort": effort,
            "velocity": velocity,
        })
    child_links = {j["child"] for j in joints}
    root_links = [n for n in links if n not in child_links]
    if len(root_links) != 1:
        raise ValueError(f"expected one root link, got {root_links}")
    by_parent: Dict[str, List[Dict[str, Any]]] = {}
    for j in joints:
        by_parent.setdefault(j["parent"], []).append(j)
    return {
        "robot_name": robot.get("name") or "atri_v2",
        "comments": comments,
        "root_xyz_mm": root_xyz_mm,
        "links": links,
        "joints": joints,
        "root": root_links[0],
        "by_parent": by_parent,
    }


def _xml_comments(raw: str) -> List[str]:
    out: List[str] = []
    start = 0
    while True:
        i = raw.find("<!--", start)
        if i < 0:
            break
        j = raw.find("-->", i + 4)
        if j < 0:
            break
        out.append(raw[i + 4:j])
        start = j + 3
    return out


def copy_inputs(out: Path) -> Dict[str, Any]:
    """Snapshot URDF + link meshes so a concurrent CAD rmtree of out/sim cannot yank them."""
    out.mkdir(parents=True, exist_ok=True)
    mesh_dst = out / "meshes"
    mesh_dst.mkdir(parents=True, exist_ok=True)
    (out / "worlds").mkdir(exist_ok=True)
    (out / "logs").mkdir(exist_ok=True)
    src_urdf = SIM_URDF if SIM_URDF.is_file() else None
    src_meshes = SIM_MESHES if SIM_MESHES.is_dir() else None
    if src_urdf is None or src_meshes is None or not any(src_meshes.glob("*.stl")):
        if not SIM_ZIP.is_file():
            raise FileNotFoundError(
                f"no URDF/meshes at {SIM_URDF} and no zip at {SIM_ZIP}"
            )
        import zipfile
        with zipfile.ZipFile(SIM_ZIP) as zf:
            for info in zf.infolist():
                name = info.filename.replace("\\", "/")
                if name == "sim/atri_v2.urdf":
                    (out / "atri_v2.urdf").write_bytes(zf.read(info))
                elif name.startswith("sim/meshes/") and name.endswith(".stl"):
                    target = mesh_dst / Path(name).name
                    target.write_bytes(zf.read(info))
        src_note = f"zip:{SIM_ZIP}"
    else:
        shutil.copy2(src_urdf, out / "atri_v2.urdf")
        for stl in src_meshes.glob("*.stl"):
            shutil.copy2(stl, mesh_dst / stl.name)
        src_note = str(src_urdf)
    urdf_path = out / "atri_v2.urdf"
    model = parse_urdf(urdf_path)
    missing = []
    aabb: Dict[str, Dict[str, Any]] = {}
    for name, link in model["links"].items():
        mesh = link["mesh"]
        if not mesh:
            missing.append(name)
            continue
        path = mesh_dst / mesh
        if not path.is_file():
            missing.append(name)
            continue
        box = stl_aabb_m(path)
        if box:
            aabb[name] = {"center_m": box[0], "size_m": box[1], "bytes": path.stat().st_size}
        else:
            aabb[name] = {"center_m": [0, 0, 0], "size_m": [0.03, 0.03, 0.03], "bytes": path.stat().st_size}
    if missing:
        raise FileNotFoundError(f"link meshes missing after copy: {missing}")
    model["aabb"] = aabb
    model["source"] = src_note
    model["copied_meshes"] = sorted(p.name for p in mesh_dst.glob("*.stl"))
    return model


def render_visual(link: Dict[str, Any], indent: int) -> List[str]:
    pad = "  " * indent
    mesh = link["mesh"]
    color = link["color"]
    scale = link["scale"]
    lines = [
        f"{pad}Transform {{",
        f"{pad}  scale {vec(scale)}",
        f"{pad}  children [",
        f"{pad}    Shape {{",
        f"{pad}      castShadows FALSE",
        f"{pad}      appearance PBRAppearance {{",
        f"{pad}        baseColor {vec(color)}",
        f"{pad}        metalness 0.1",
        f"{pad}        roughness 0.6",
        f"{pad}      }}",
        f"{pad}      geometry Mesh {{",
        f"{pad}        url [",
        f'{pad}          "../meshes/{mesh}"',
        f"{pad}        ]",
        f"{pad}      }}",
        f"{pad}    }}",
        f"{pad}  ]",
        f"{pad}}}",
    ]
    return lines


def render_physics(link: Dict[str, Any], indent: int) -> List[str]:
    pad = "  " * indent
    ixx, iyy, izz, ixy, ixz, iyz = link["inertia"]
    com = link["com"]
    return [
        f"{pad}physics Physics {{",
        f"{pad}  density -1",
        f"{pad}  mass {num(link['mass'])}",
        f"{pad}  centerOfMass [",
        f"{pad}    {vec(com)}",
        f"{pad}  ]",
        f"{pad}  inertiaMatrix [",
        f"{pad}    {vec([ixx, iyy, izz])}",
        f"{pad}    {vec([ixy, ixz, iyz])}",
        f"{pad}  ]",
        f"{pad}}}",
    ]


def render_bounding(name: str, aabb: Dict[str, Any], indent: int) -> List[str]:
    pad = "  " * indent
    info = aabb.get(name) or {"center_m": [0, 0, 0], "size_m": [0.03, 0.03, 0.03]}
    center, size = info["center_m"], info["size_m"]
    return [
        f"{pad}boundingObject Pose {{",
        f"{pad}  translation {vec(center)}",
        f"{pad}  children [",
        f"{pad}    Box {{",
        f"{pad}      size {vec(size)}",
        f"{pad}    }}",
        f"{pad}  ]",
        f"{pad}}}",
    ]


def render_joint(model: Dict[str, Any], joint: Dict[str, Any], indent: int) -> List[str]:
    pad = "  " * indent
    child_link = model["links"][joint["child"]]
    lo, hi = joint["lower"], joint["upper"]
    rot = rpy_to_axis_angle(joint["rpy"])
    motor = [
        f"{pad}    RotationalMotor {{",
        f'{pad}      name "{joint["name"]}"',
        f"{pad}      maxVelocity {num(joint['velocity'])}",
        f"{pad}      minPosition {num(lo)}",
        f"{pad}      maxPosition {num(hi)}",
        f"{pad}      maxTorque {num(joint['effort'])}",
        f'{pad}      sound ""',
        f"{pad}    }}",
    ]
    lines = [
        f"{pad}DEF {joint['name']} HingeJoint {{",
        f"{pad}  jointParameters HingeJointParameters {{",
        f"{pad}    axis {vec(joint['axis'])}",
        f"{pad}    anchor {vec(joint['xyz'])}",
        f"{pad}    minStop {num(lo)}",
        f"{pad}    maxStop {num(hi)}",
        f"{pad}    dampingConstant {num(JOINT_DAMPING)}",
        f"{pad}  }}",
        f"{pad}  device [",
        *motor,
        f"{pad}    PositionSensor {{",
        f'{pad}      name "{joint["name"]}_sensor"',
        f"{pad}    }}",
        f"{pad}  ]",
        f"{pad}  endPoint DEF {joint['child']} Solid {{",
        f"{pad}    translation {vec(joint['xyz'])}",
    ]
    if rot is not None:
        lines.append(f"{pad}    rotation {vec(rot)}")
    lines += [
        f'{pad}    name "{joint["child"]}"',
        f"{pad}    children [",
        *render_visual(child_link, indent + 3),
    ]
    for nested in model["by_parent"].get(joint["child"], []):
        lines.extend(render_joint(model, nested, indent + 3))
    lines += [
        f"{pad}    ]",
        *render_bounding(joint["child"], model["aabb"], indent + 2),
        *render_physics(child_link, indent + 2),
        f"{pad}  }}",
        f"{pad}}}",
    ]
    return lines


def render_world(model: Dict[str, Any]) -> str:
    root_name = model["root"]
    root_link = model["links"][root_name]
    z = model["root_xyz_mm"][2] * MESH_SCALE
    n_rev = sum(1 for j in model["joints"] if j["type"] == "revolute")
    title = "ATRI-v2 URDF import / kinematics smoke test (NOT T1-T5)"
    lines = [
        f"#VRML_SIM {WORLD_VERSION} utf8",
        "",
        "# Generated by design/v2/webots_v2_import.py — do not hand-edit.",
        f"# Source robot name={model['robot_name']} root={root_name} revolute={n_rev}.",
        "# Units: URDF already m/rad; STL meshes are millimetres, visual Transform scale 0.001.",
        "# Masses are URDF target-mass allocations, not CAD/measured inertia.",
        "# Gravity 0: import/kinematics check only. NOT G4, NOT 5/5 task verification.",
        "# VL53L1X is a CAD part on the head link, not a URDF joint or link.",
        "# No EXTERNPROTO (offline). Motor sound disabled (default URL hits GitHub).",
        "",
        "WorldInfo {",
        f'  title "{title}"',
        f"  basicTimeStep {BASIC_TIME_STEP}",
        "  gravity 0",
        "  ERP 0.6",
        "  CFM 1e-05",
        "  physicsDisableTime 0",
        "  coordinateSystem \"ENU\"",
        "}",
        "",
        "Viewpoint {",
        "  orientation -0.1567 0.8935 0.4214 1.1077",
        "  position 0.62 -0.72 0.66",
        "  followType \"None\"",
        "}",
        "",
        f"DEF {root_name} Robot {{",
        f"  translation 0 0 {num(z)}",
        f'  name "{model["robot_name"]}"',
        f'  model "{model["robot_name"]}"',
        '  controller "atri_v2_import_check"',
        "  supervisor TRUE",
        "  synchronization TRUE",
        "  selfCollision FALSE",
        "  children [",
        *render_visual(root_link, 2),
    ]
    for joint in model["by_parent"].get(root_name, []):
        lines.extend(render_joint(model, joint, 2))
    lines += [
        "  ]",
        *render_bounding(root_name, model["aabb"], 1),
        *render_physics(root_link, 1),
        "}",
        "",
    ]
    return "\n".join(lines)


CONTROLLER_PY = r'''#!/usr/bin/env python3
"""Supervisor: list joints, check import, nudge one motor, write JSON, quit.

This is an import/kinematics smoke test. It does NOT run T1–T5 and is NOT G4.
"""
from __future__ import annotations

import json
import math
import os
import sys
import traceback
from pathlib import Path

try:
    from controller import Node, Supervisor
except ImportError:
    print("controller module missing — this file must run inside Webots", file=sys.stderr)
    raise SystemExit(2)

HERE = Path(__file__).resolve().parent
OUT = HERE.parents[1]  # design/v2/out/webots
REPORT = Path(os.environ.get("ATRI_V2_IMPORT_REPORT") or (OUT / "import-report.json"))
META_PATH = OUT / "urdf-meta.json"
MASS_HI = 20.0
MASS_LO = 1e-6
STEPS = 16
COMMAND_RAD = 0.2


def _json_float(value):
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    if x != x or x in (float("inf"), float("-inf")):
        return None
    return x


def load_meta():
    if not META_PATH.is_file():
        return {}
    return json.loads(META_PATH.read_text(encoding="utf-8"))


def walk_tree(node, joints, solids, parent_solid=None):
    tname = node.getTypeName()
    if tname in ("Robot", "Solid"):
        name_f = node.getField("name")
        name = name_f.getSFString() if name_f else ""
        physics = node.getField("physics")
        phys = physics.getSFNode() if physics else None
        mass = None
        if phys is not None:
            mf = phys.getField("mass")
            mass = mf.getSFFloat() if mf else None
        trans_f = node.getField("translation")
        trans = list(trans_f.getSFVec3f()) if trans_f else None
        solids.append({
            "name": name,
            "def": node.getDef(),
            "type": tname,
            "mass": mass,
            "translation": trans,
            "parent_solid": parent_solid,
        })
        children = node.getField("children")
        if children is not None:
            for i in range(children.getCount()):
                child = children.getMFNode(i)
                if child is not None:
                    walk_tree(child, joints, solids, name)
        return
    if tname == "HingeJoint":
        params = node.getField("jointParameters").getSFNode() if node.getField("jointParameters") else None
        axis = list(params.getField("axis").getSFVec3f()) if params else None
        anchor = list(params.getField("anchor").getSFVec3f()) if params else None
        motor_name = None
        sensor_name = None
        devices = node.getField("device")
        if devices is not None:
            for i in range(devices.getCount()):
                d = devices.getMFNode(i)
                if d is None:
                    continue
                dn = d.getTypeName()
                nm = d.getField("name").getSFString() if d.getField("name") else ""
                if dn == "RotationalMotor":
                    motor_name = nm
                elif dn == "PositionSensor":
                    sensor_name = nm
        end = node.getField("endPoint").getSFNode() if node.getField("endPoint") else None
        child_name = None
        child_trans = None
        if end is not None:
            nf = end.getField("name")
            child_name = nf.getSFString() if nf else end.getDef()
            tf = end.getField("translation")
            child_trans = list(tf.getSFVec3f()) if tf else None
        joints.append({
            "def": node.getDef(),
            "motor": motor_name,
            "sensor": sensor_name,
            "axis": axis,
            "anchor": anchor,
            "child_solid": child_name,
            "child_translation": child_trans,
            "parent_solid": parent_solid,
        })
        if end is not None:
            walk_tree(end, joints, solids, parent_solid)
        return
    children = node.getField("children")
    if children is not None:
        for i in range(children.getCount()):
            child = children.getMFNode(i)
            if child is not None:
                walk_tree(child, joints, solids, parent_solid)


def flag_mass(mass):
    if mass is None:
        return "missing"
    if mass == 0:
        return "zero"
    if mass < MASS_LO:
        return "too_small"
    if mass > MASS_HI:
        return "too_large"
    return None


def vec_close(a, b, tol=1e-5):
    if a is None or b is None:
        return False
    if len(a) != len(b):
        return False
    return all(abs(float(x) - float(y)) <= tol for x, y in zip(a, b))


def main() -> int:
    robot = Supervisor()
    timestep = int(robot.getBasicTimeStep())
    meta = load_meta()
    failures = []
    notes = []
    report = {
        "kind": "atri_v2_urdf_import_check",
        "not_g4": True,
        "not_task_verification": True,
        "not_physical_robot_test": True,
        "controller": "atri_v2_import_check",
        "basic_time_step_ms": timestep,
        "failures": failures,
        "notes": notes,
    }
    try:
        n_dev = robot.getNumberOfDevices()
        motors = []
        sensors = []
        other = []
        for i in range(n_dev):
            dev = robot.getDeviceByIndex(i)
            name = dev.getName()
            ntype = dev.getNodeType()
            if ntype == Node.ROTATIONAL_MOTOR:
                motors.append(name)
            elif ntype == Node.POSITION_SENSOR:
                sensors.append(name)
            else:
                other.append({"name": name, "node_type": int(ntype)})
        report["devices"] = {
            "count": n_dev,
            "motors": motors,
            "sensors": sensors,
            "other": other,
        }
        hip = [n for n in motors + sensors if "hip_yaw" in n.lower()]
        report["hip_yaw_names"] = hip
        report["hip_yaw_absent"] = len(hip) == 0
        if hip:
            failures.append("hip_yaw present in device names: " + ",".join(hip))

        self_node = robot.getSelf()
        hinge_joints = []
        solids = []
        walk_tree(self_node, hinge_joints, solids, parent_solid=None)
        report["revolute_count"] = len(hinge_joints)
        report["expected_revolute"] = int(meta.get("n_revolute") or 20)
        if report["revolute_count"] != report["expected_revolute"]:
            failures.append(
                "revolute/hinge count %s != expected %s"
                % (report["revolute_count"], report["expected_revolute"])
            )
        solid_names = [s["name"] for s in solids]
        report["solid_names"] = solid_names
        report["left_grip_exists"] = "left_grip" in solid_names
        report["right_grip_exists"] = "right_grip" in solid_names
        if not report["left_grip_exists"]:
            failures.append("solid left_grip missing")
        if not report["right_grip_exists"]:
            failures.append("solid right_grip missing")

        urdf_joints = {j["name"]: j for j in meta.get("joints", [])}
        urdf_links = {l["name"]: l for l in meta.get("links", [])}
        zero_pose = []
        for hj in hinge_joints:
            jname = hj["motor"] or hj["def"]
            uj = urdf_joints.get(jname) or {}
            axis_ok = vec_close(hj["axis"], uj.get("axis")) if uj else False
            trans_ok = vec_close(hj["child_translation"], uj.get("xyz")) if uj else False
            zero_pose.append({
                "joint": jname,
                "child_solid": hj["child_solid"],
                "axis_wbt": hj["axis"],
                "axis_urdf": uj.get("axis"),
                "axis_match": axis_ok,
                "translation_wbt": hj["child_translation"],
                "xyz_urdf": uj.get("xyz"),
                "anchor_wbt": hj["anchor"],
                "zero_pose_match": trans_ok,
            })
            if uj and not axis_ok:
                failures.append("axis mismatch: " + str(jname))
            if uj and not trans_ok:
                failures.append("zero-pose translation mismatch: " + str(jname))
        report["zero_pose"] = zero_pose

        sample_names = ["pelvis", "torso", "head", "left_thigh", "left_grip", "right_grip", "atri_v2"]
        masses = {}
        mass_flags = []
        by_solid = {s["name"]: s for s in solids}
        # Robot node is the pelvis root; its name is atri_v2.
        if "pelvis" not in by_solid and self_node is not None:
            pf = self_node.getField("physics")
            phys = pf.getSFNode() if pf else None
            mass = phys.getField("mass").getSFFloat() if phys else None
            masses["pelvis_via_robot"] = {
                "wbt": mass,
                "urdf": (urdf_links.get(meta.get("root") or "pelvis") or {}).get("mass"),
                "flag": flag_mass(mass),
            }
        for s in solids:
            flag = flag_mass(s["mass"])
            if flag:
                mass_flags.append({"name": s["name"], "mass": s["mass"], "flag": flag})
                failures.append("mass %s on %s" % (flag, s["name"]))
        for name in sample_names:
            if name in by_solid:
                s = by_solid[name]
                urdf_name = "pelvis" if name == "atri_v2" else name
                masses[name] = {
                    "wbt": s["mass"],
                    "urdf": (urdf_links.get(urdf_name) or {}).get("mass"),
                    "flag": flag_mass(s["mass"]),
                }
        report["mass_sample"] = masses
        report["mass_flags"] = mass_flags
        report["solids"] = [
            {"name": s["name"], "type": s["type"], "mass": s["mass"]} for s in solids
        ]

        vl53 = {
            "urdf_joint": any("vl53" in (j.get("name") or "").lower() for j in meta.get("joints", [])),
            "urdf_link": any("vl53" in (l.get("name") or "").lower() for l in meta.get("links", [])),
            "solid": any("vl53" in (n or "").lower() for n in solid_names),
            "note": (
                "VL53L1X is a CAD part on the head link (electronics_cad.py), "
                "merged into meshes/head.stl. Not a URDF joint; missing ToF node is expected."
            ),
        }
        report["vl53l1x"] = vl53
        if vl53["urdf_joint"]:
            failures.append("VL53L1X unexpectedly present as URDF/Webots joint")

        if not report["hip_yaw_absent"]:
            notes.append("v2 A-route must not have hip_yaw")

        # Enable sensors, step, command one arm/head joint.
        motion = {"joint": None, "command_rad": COMMAND_RAD, "before": None, "after": None, "steps": 0}
        candidate = None
        for name in ("head_yaw", "head_pitch", "left_shoulder_pitch", "right_shoulder_pitch"):
            if name in motors:
                candidate = name
                break
        if candidate is None and motors:
            candidate = motors[0]
        if candidate is None:
            failures.append("no RotationalMotor devices")
        else:
            motor = robot.getDevice(candidate)
            sensor = robot.getDevice(candidate + "_sensor")
            if sensor is None:
                failures.append("missing position sensor for " + candidate)
            else:
                sensor.enable(timestep)
                motor.setVelocity(1.0)
                if robot.step(timestep) == -1:
                    failures.append("simulation ended before motion")
                else:
                    motion["joint"] = candidate
                    motion["before"] = _json_float(sensor.getValue())
                    motor.setPosition(COMMAND_RAD)
                    ran = 0
                    for _ in range(STEPS):
                        if robot.step(timestep) == -1:
                            failures.append("simulation ended during motion steps")
                            break
                        ran += 1
                    motion["steps"] = ran
                    motion["after"] = _json_float(sensor.getValue())
                    motion["delta"] = None
                    if motion["before"] is not None and motion["after"] is not None:
                        motion["delta"] = motion["after"] - motion["before"]
                    if ran < 10:
                        failures.append("stepped only %s times, need >= 10" % ran)
                    if motion["after"] is None:
                        failures.append("position sensor returned NaN")
                    elif abs(motion["after"] - COMMAND_RAD) > 0.15 and (
                        motion["delta"] is None or abs(motion["delta"]) < 0.02
                    ):
                        failures.append(
                            "motor %s did not move toward %.3f (after=%s delta=%s)"
                            % (candidate, COMMAND_RAD, motion["after"], motion["delta"])
                        )
        report["motion"] = motion
        report["sim_steps"] = int(motion.get("steps") or 0) + (1 if motion.get("before") is not None else 0)
        report["ok"] = len(failures) == 0
    except Exception as exc:
        failures.append("controller exception: %s" % exc)
        report["traceback"] = traceback.format_exc()
        report["ok"] = False
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("[atri_v2_import_check] wrote", REPORT)
    print("[atri_v2_import_check] ok=", report.get("ok"), "failures=", failures)
    sys.stdout.flush()
    robot.simulationQuit(0 if report.get("ok") else 1)
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
'''


def write_controller(out: Path) -> Path:
    dest = out / "controllers" / "atri_v2_import_check" / "atri_v2_import_check.py"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(CONTROLLER_PY, encoding="utf-8", newline="\n")
    dest.chmod(dest.stat().st_mode | 0o111)
    return dest


def write_meta(model: Dict[str, Any], out: Path) -> Path:
    vl53_joint = any("vl53" in j["name"].lower() for j in model["joints"])
    vl53_link = any("vl53" in n.lower() for n in model["links"])
    payload = {
        "robot_name": model["robot_name"],
        "root": model["root"],
        "root_xyz_mm": model["root_xyz_mm"],
        "n_revolute": sum(1 for j in model["joints"] if j["type"] == "revolute"),
        "n_joints": len(model["joints"]),
        "n_links": len(model["links"]),
        "comments": model["comments"],
        "source": model.get("source"),
        "copied_meshes": model.get("copied_meshes"),
        "hip_yaw_in_urdf": any("hip_yaw" in j["name"] for j in model["joints"]),
        "vl53l1x": {
            "urdf_joint": vl53_joint,
            "urdf_link": vl53_link,
            "note": "CAD part on head link; merged into head.stl; not a URDF joint.",
        },
        "joints": [
            {
                "name": j["name"],
                "type": j["type"],
                "parent": j["parent"],
                "child": j["child"],
                "xyz": j["xyz"],
                "rpy": j["rpy"],
                "axis": j["axis"],
                "lower": j["lower"],
                "upper": j["upper"],
                "effort": j["effort"],
                "velocity": j["velocity"],
            }
            for j in model["joints"]
        ],
        "links": [
            {
                "name": n,
                "mass": L["mass"],
                "com": L["com"],
                "inertia": L["inertia"],
                "mesh": L["mesh"],
                "aabb": model["aabb"].get(n),
            }
            for n, L in model["links"].items()
        ],
        "kind": "atri_v2_urdf_import_meta",
        "not_g4": True,
    }
    path = out / "urdf-meta.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def generate(out: Path = OUT) -> Dict[str, Any]:
    model = copy_inputs(out)
    world = render_world(model)
    world_path = out / "worlds" / "atri_v2.wbt"
    world_path.parent.mkdir(parents=True, exist_ok=True)
    with open(world_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(world)
    controller = write_controller(out)
    meta = write_meta(model, out)
    n_rev = sum(1 for j in model["joints"] if j["type"] == "revolute")
    hip = [j["name"] for j in model["joints"] if "hip_yaw" in j["name"]]
    info = {
        "world": str(world_path),
        "controller": str(controller),
        "meta": str(meta),
        "urdf": str(out / "atri_v2.urdf"),
        "n_revolute": n_rev,
        "n_links": len(model["links"]),
        "hip_yaw": hip,
        "root": model["root"],
        "robot_name": model["robot_name"],
        "mesh_count": len(model.get("copied_meshes") or []),
    }
    (out / "logs" / "generate.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return info


def run_webots(world: Path, report: Path, log: Path, timeout_sec: int = 180) -> Dict[str, Any]:
    """Launch Webots; quit when the Supervisor writes the report or the timeout fires."""
    import subprocess

    webots = shutil.which("webots") or "/usr/bin/webots"
    report.unlink(missing_ok=True)
    log.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["ATRI_V2_IMPORT_REPORT"] = str(report)
    cmd = [
        webots,
        "--mode=fast",
        "--no-rendering",
        "--batch",
        "--stdout",
        "--stderr",
        "--minimize",
        str(world),
    ]
    with open(log, "w", encoding="utf-8") as fh:
        fh.write("cmd: " + " ".join(cmd) + "\n")
        fh.flush()
        proc = subprocess.Popen(
            cmd,
            stdout=fh,
            stderr=subprocess.STDOUT,
            env=env,
            cwd=str(world.parent.parent),
        )
        deadline = time.time() + timeout_sec
        appeared = False
        while time.time() < deadline:
            if report.is_file() and report.stat().st_size > 20:
                appeared = True
                break
            rc = proc.poll()
            if rc is not None:
                break
            time.sleep(0.4)
        time.sleep(1.5)
        if proc.poll() is None:
            proc.kill()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                pass
        # leftover webots-bin
        subprocess.run(["pkill", "-KILL", "-x", "webots-bin"], check=False, capture_output=True)
        subprocess.run(["pkill", "-KILL", "-x", "webots"], check=False, capture_output=True)
    return {
        "cmd": cmd,
        "returncode": proc.returncode,
        "report_exists": report.is_file(),
        "appeared": appeared,
        "log": str(log),
        "pid": proc.pid,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Import ATRI-v2 URDF into a Webots R2025a world")
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--run", action="store_true", help="launch Webots after generating")
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args(list(argv) if argv is not None else None)
    info = generate(args.out)
    print(json.dumps(info, ensure_ascii=False, indent=2))
    if not args.run:
        return 0
    report = args.out / "import-report.json"
    log = args.out / "logs" / "webots-stdout.log"
    run_info = run_webots(Path(info["world"]), report, log, timeout_sec=args.timeout)
    print(json.dumps(run_info, ensure_ascii=False, indent=2, default=str))
    if not run_info["report_exists"]:
        print("Webots did not write import-report.json", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
