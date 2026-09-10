"""机器人拓扑与配置加载。

关节拓扑严格对齐申报方案：22 DOF = 双腿 10 + 双臂 8 + 躯干 2 + 头部 2。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

DOF_COUNT = 22

JOINTS: Dict[str, Dict[str, Any]] = {
    "head_yaw":        {"id": 0,  "group": "head",    "limit_deg": [-90, 90],   "rest_deg": 0.0},
    "head_pitch":      {"id": 1,  "group": "head",    "limit_deg": [-45, 45],   "rest_deg": 0.0},
    "trunk_roll":      {"id": 2,  "group": "trunk",   "limit_deg": [-10, 10],   "rest_deg": 0.0},
    "trunk_pitch":     {"id": 3,  "group": "trunk",   "limit_deg": [-15, 15],   "rest_deg": 0.0},

    "left_hip_yaw":    {"id": 4,  "group": "leg_l",   "limit_deg": [-45, 45],   "rest_deg": 0.0},
    "left_hip_roll":   {"id": 5,  "group": "leg_l",   "limit_deg": [-25, 25],   "rest_deg": 0.0},
    "left_hip_pitch":  {"id": 6,  "group": "leg_l",   "limit_deg": [-60, 60],   "rest_deg": 0.0},
    "left_knee_pitch": {"id": 7,  "group": "leg_l",   "limit_deg": [0, 90],     "rest_deg": 0.0},
    "left_ankle_pitch":{"id": 8,  "group": "leg_l",   "limit_deg": [-40, 40],   "rest_deg": 0.0},

    "right_hip_yaw":    {"id": 9,  "group": "leg_r",  "limit_deg": [-45, 45],   "rest_deg": 0.0},
    "right_hip_roll":   {"id": 10, "group": "leg_r",  "limit_deg": [-25, 25],   "rest_deg": 0.0},
    "right_hip_pitch":  {"id": 11, "group": "leg_r",  "limit_deg": [-60, 60],   "rest_deg": 0.0},
    "right_knee_pitch": {"id": 12, "group": "leg_r",  "limit_deg": [0, 90],     "rest_deg": 0.0},
    "right_ankle_pitch":{"id": 13, "group": "leg_r",  "limit_deg": [-40, 40],   "rest_deg": 0.0},

    "left_shoulder_pitch":  {"id": 14, "group": "arm_l", "limit_deg": [-90, 90],  "rest_deg": 0.0},
    "left_shoulder_roll":   {"id": 15, "group": "arm_l", "limit_deg": [-90, 90],  "rest_deg": 0.0},
    "left_elbow_pitch":     {"id": 16, "group": "arm_l", "limit_deg": [-120, 0],  "rest_deg": -10.0},
    "left_gripper":         {"id": 17, "group": "arm_l", "limit_deg": [0, 60],    "rest_deg": 0.0},

    "right_shoulder_pitch": {"id": 18, "group": "arm_r", "limit_deg": [-90, 90],  "rest_deg": 0.0},
    "right_shoulder_roll":  {"id": 19, "group": "arm_r", "limit_deg": [-90, 90],  "rest_deg": 0.0},
    "right_elbow_pitch":    {"id": 20, "group": "arm_r", "limit_deg": [-120, 0],  "rest_deg": -10.0},
    "right_gripper":        {"id": 21, "group": "arm_r", "limit_deg": [0, 60],    "rest_deg": 0.0},
}

GROUP_DOF = {
    "head": 2,
    "trunk": 2,
    "leg_l": 5,
    "leg_r": 5,
    "arm_l": 4,
    "arm_r": 4,
}


def _assert_topology() -> None:
    ids = [v["id"] for v in JOINTS.values()]
    assert len(JOINTS) == DOF_COUNT, f"joint count {len(JOINTS)} != {DOF_COUNT}"
    assert ids == list(range(DOF_COUNT)), "joint ids must be 0..21"
    assert sum(GROUP_DOF.values()) == DOF_COUNT, "group DOF sum != 22"


_assert_topology()


def clamp_angle(name: str, deg: float) -> float:
    lo, hi = JOINTS[name]["limit_deg"]
    return max(lo, min(hi, float(deg)))


def rest_pose() -> Dict[str, float]:
    return {name: float(spec["rest_deg"]) for name, spec in JOINTS.items()}


def load_robot_config(path: str | Path | None = None) -> Dict[str, Any]:
    if path is None:
        path = Path(__file__).resolve().parent.parent / "config" / "robot.json"
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)
