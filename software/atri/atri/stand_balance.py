"""Webots 自主站立用的开环 IMU PD（不是 ZMP，G4 仍开放）。

约定（Webots ENU + 本机 InertialUnit）：
- pitch>0：后仰，踝负向把脚尖压下去、把质心拉回。
- roll>0：向左倾，用左右髋 roll 反对称（与 body_yaw_pose 同号）。
"""
from __future__ import annotations

import math
from typing import Dict, List, Mapping, Optional

from atri.config import clamp_angle, rest_pose

DEFAULT_KP_PITCH = 1.2
DEFAULT_KP_ROLL = 0.8
# 盒体静立：非 0 的 IMU roll PD 会把机子绕 x 拧翻（Webots 2026-09-13 实测）。
STAND_KP_PITCH = 0.0
STAND_KP_ROLL = 0.0
DEFAULT_Z_LO_M = 0.15
DEFAULT_Z_HI_M = 0.30
DEFAULT_TILT_MAX_DEG = 15.0
STAND_CROUCH_DEG = 12.0
STAND_HIP_ABDUCT_DEG = 8.0
STAND_TRUNK_PITCH_DEG = 4.0
STAND_SETTLE_S = 2.0


def stand_base_pose() -> Dict[str, float]:
    """微蹲站立零位：膝微屈，髋外展，躯干略后仰。"""
    pose = rest_pose()
    c = STAND_CROUCH_DEG
    pose["left_hip_pitch"] = clamp_angle("left_hip_pitch", -c)
    pose["right_hip_pitch"] = clamp_angle("right_hip_pitch", -c)
    pose["left_knee_pitch"] = clamp_angle("left_knee_pitch", 2.0 * c)
    pose["right_knee_pitch"] = clamp_angle("right_knee_pitch", 2.0 * c)
    pose["left_ankle_pitch"] = clamp_angle("left_ankle_pitch", -c)
    pose["right_ankle_pitch"] = clamp_angle("right_ankle_pitch", -c)
    pose["left_hip_roll"] = clamp_angle("left_hip_roll", STAND_HIP_ABDUCT_DEG)
    pose["right_hip_roll"] = clamp_angle("right_hip_roll", -STAND_HIP_ABDUCT_DEG)
    pose["trunk_pitch"] = clamp_angle("trunk_pitch", STAND_TRUNK_PITCH_DEG)
    return pose


def pelvis_spawn_z_m(
    chain_z_m: float,
    foot_half_z_m: float,
    clearance_m: float = 0.002,
) -> float:
    """骨盆世界系高度，使脚底在地面上方 ``clearance_m``。

    ``chain_z_m`` 是骨盆原点到踝原点的 z 累加（URDF 零位，负值）。
    """
    return float(clearance_m) - float(chain_z_m) + float(foot_half_z_m)


def balance_offsets(
    roll_rad: float,
    pitch_rad: float,
    kp_pitch: float = DEFAULT_KP_PITCH,
    kp_roll: float = DEFAULT_KP_ROLL,
) -> Dict[str, float]:
    """由 IMU 姿态得到踝/髋附加角（度），已按 v2 限位钳制。"""
    pitch_deg = math.degrees(float(pitch_rad))
    roll_deg = math.degrees(float(roll_rad))
    ankle = -float(kp_pitch) * pitch_deg
    left_roll = float(kp_roll) * roll_deg
    right_roll = -float(kp_roll) * roll_deg
    return {
        "left_ankle_pitch": clamp_angle("left_ankle_pitch", ankle),
        "right_ankle_pitch": clamp_angle("right_ankle_pitch", ankle),
        "left_hip_roll": clamp_angle("left_hip_roll", left_roll),
        "right_hip_roll": clamp_angle("right_hip_roll", right_roll),
    }


def mix_pose(base: Mapping[str, float], offsets: Mapping[str, float]) -> Dict[str, float]:
    """把站立补偿叠到目标姿态上并再钳制一次。"""
    out = {name: float(deg) for name, deg in base.items()}
    for name, extra in offsets.items():
        out[name] = clamp_angle(name, out.get(name, 0.0) + float(extra))
    return out


def evaluate_stand(
    pelvis_z_m: List[float],
    roll_deg: List[float],
    pitch_deg: List[float],
    *,
    z_lo_m: float = DEFAULT_Z_LO_M,
    z_hi_m: float = DEFAULT_Z_HI_M,
    tilt_max_deg: float = DEFAULT_TILT_MAX_DEG,
    min_samples: int = 10,
) -> Dict[str, Optional[object]]:
    """根据高度/倾角序列判定静立是否成立。"""
    n = min(len(pelvis_z_m), len(roll_deg), len(pitch_deg))
    if n < min_samples:
        return {"ok": False, "reason": "too_few_samples", "n": n}
    zs = [float(z) for z in pelvis_z_m[:n]]
    tilts = [max(abs(float(roll_deg[i])), abs(float(pitch_deg[i]))) for i in range(n)]
    z_min, z_max = min(zs), max(zs)
    tilt_peak = max(tilts)
    if z_min < z_lo_m or z_max > z_hi_m:
        return {
            "ok": False,
            "reason": "pelvis_z",
            "n": n,
            "z_min": round(z_min, 4),
            "z_max": round(z_max, 4),
            "tilt_peak_deg": round(tilt_peak, 2),
        }
    if tilt_peak > tilt_max_deg:
        return {
            "ok": False,
            "reason": "tilt",
            "n": n,
            "z_min": round(z_min, 4),
            "z_max": round(z_max, 4),
            "tilt_peak_deg": round(tilt_peak, 2),
        }
    return {
        "ok": True,
        "reason": None,
        "n": n,
        "z_min": round(z_min, 4),
        "z_max": round(z_max, 4),
        "tilt_peak_deg": round(tilt_peak, 2),
    }
