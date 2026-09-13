#!/usr/bin/env python3
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
