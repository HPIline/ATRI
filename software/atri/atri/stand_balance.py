"""通电静立：开环微蹲 + 质心相对脚心（不是 ZMP，G4 仍开放）。

IMU PD 关掉：仿真里 IMU 后仰约 8°，质心却在脚心偏前约 2 cm，用 IMU 会推错方向。

约定（Webots ENU）：
- 质心在脚前（+X）→ 踝负向，脚尖压下，把质心往回拉。
- 质心偏 +Y（左）→ 左髋 roll 正、右髋负（与 body_yaw_pose 同号）。
- IMU pitch>0：后仰（仅文档；站立环不用）。
"""
from __future__ import annotations

import math
from typing import Dict, List, Mapping, Optional, Sequence

from atri.config import clamp_angle, rest_pose

DEFAULT_KP_PITCH = 1.2
DEFAULT_KP_ROLL = 0.8
# IMU 环实测会加大倾角。站立用质心-支撑，不用 IMU。
STAND_KP_PITCH = 0.0
STAND_KP_ROLL = 0.0
# 质心相对接触均值，deg/m。0.02 m → 约 1.6° 踝。
STAND_KP_COM_X = 80.0
# 髋 roll 会把脚底翘成棱（与 STAND_HIP_ABDUCT 同一失败模式）。Y 向先不调。
STAND_KP_COM_Y = 0.0
STAND_COM_DEADZONE_M = 0.005
STAND_COM_ANKLE_MAX_DEG = 6.0
STAND_COM_HIP_MAX_DEG = 4.0
# Webots 电机 PID。P=50 在 settle 就前倾 18° 摔倒；P=400 能抱住，髋会过冲约 2.5°。
STAND_CONTROL_P = 400.0
STAND_CONTROL_I = 0.0
STAND_CONTROL_D = 20.0
DEFAULT_Z_LO_M = 0.15
DEFAULT_Z_HI_M = 0.30
DEFAULT_TILT_MAX_DEG = 15.0
DEFAULT_XY_MAX_M = 0.05
# STS3215-C018 堵转 2.94 N·m（profile.SERVO["stall_nm"]）。禁止再用 20 N·m。
STAND_AVAILABLE_TORQUE_NM = 2.94
# 无 ankle_roll：髋外展会把 TPU 底侧倾成棱。微蹲且髋滚=0 时 xy 漂移最小。
STAND_CROUCH_DEG = 12.0
STAND_HIP_ABDUCT_DEG = 0.0
STAND_TRUNK_PITCH_DEG = 4.0
STAND_SETTLE_S = 2.0


def stand_base_pose() -> Dict[str, float]:
    """微蹲站立零位：膝微屈，脚底水平，躯干略后仰。"""
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


def flat_sole_ankles(pose: Mapping[str, float]) -> Dict[str, float]:
    """按髋+膝改踝，使 ``hip+knee+ankle=0``（无 ankle_roll 时脚底才水平）。"""
    out = {name: float(deg) for name, deg in pose.items()}
    for side in ("left", "right"):
        hip = float(out.get(f"{side}_hip_pitch", 0.0))
        knee = float(out.get(f"{side}_knee_pitch", 0.0))
        out[f"{side}_ankle_pitch"] = clamp_angle(
            f"{side}_ankle_pitch", -(hip + knee)
        )
    return out


def com_hold_offsets(
    com_m: Optional[Sequence[float]],
    contacts_xy: Optional[Sequence[Sequence[float]]],
    *,
    kp_x: float = STAND_KP_COM_X,
    kp_y: float = STAND_KP_COM_Y,
    deadzone_m: float = STAND_COM_DEADZONE_M,
) -> Dict[str, float]:
    """把质心拉回接触点均值。缺接触或质心则空字典。"""
    if not com_m or len(com_m) < 2 or not contacts_xy:
        return {}
    xs: List[float] = []
    ys: List[float] = []
    for pt in contacts_xy:
        if pt is None or len(pt) < 2:
            continue
        xs.append(float(pt[0]))
        ys.append(float(pt[1]))
    if len(xs) < 2:
        return {}
    dx = float(com_m[0]) - sum(xs) / len(xs)
    dy = float(com_m[1]) - sum(ys) / len(ys)
    if math.hypot(dx, dy) < float(deadzone_m):
        return {
            "left_ankle_pitch": 0.0,
            "right_ankle_pitch": 0.0,
            "left_hip_roll": 0.0,
            "right_hip_roll": 0.0,
        }
    ankle = max(-STAND_COM_ANKLE_MAX_DEG, min(STAND_COM_ANKLE_MAX_DEG, -float(kp_x) * dx))
    hip = max(-STAND_COM_HIP_MAX_DEG, min(STAND_COM_HIP_MAX_DEG, float(kp_y) * dy))
    return {
        "left_ankle_pitch": clamp_angle("left_ankle_pitch", ankle),
        "right_ankle_pitch": clamp_angle("right_ankle_pitch", ankle),
        "left_hip_roll": clamp_angle("left_hip_roll", hip),
        "right_hip_roll": clamp_angle("right_hip_roll", -hip),
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
    xy_m: Optional[List[List[float]]] = None,
    z_lo_m: float = DEFAULT_Z_LO_M,
    z_hi_m: float = DEFAULT_Z_HI_M,
    tilt_max_deg: float = DEFAULT_TILT_MAX_DEG,
    xy_max_m: float = DEFAULT_XY_MAX_M,
    min_samples: int = 10,
) -> Dict[str, Optional[object]]:
    """根据高度/倾角/水平漂移判定静立是否成立。"""
    n = min(len(pelvis_z_m), len(roll_deg), len(pitch_deg))
    if n < min_samples:
        return {"ok": False, "reason": "too_few_samples", "n": n}
    zs = [float(z) for z in pelvis_z_m[:n]]
    tilts = [max(abs(float(roll_deg[i])), abs(float(pitch_deg[i]))) for i in range(n)]
    z_min, z_max = min(zs), max(zs)
    tilt_peak = max(tilts)
    xy_drift = 0.0
    if xy_m:
        pts = xy_m[:n]
        x0, y0 = float(pts[0][0]), float(pts[0][1])
        xy_drift = max(
            math.hypot(float(p[0]) - x0, float(p[1]) - y0) for p in pts
        )
    payload = {
        "n": n,
        "z_min": round(z_min, 4),
        "z_max": round(z_max, 4),
        "tilt_peak_deg": round(tilt_peak, 2),
        "xy_drift_m": round(xy_drift, 4),
    }
    if z_min < z_lo_m or z_max > z_hi_m:
        return {"ok": False, "reason": "pelvis_z", **payload}
    if tilt_peak > tilt_max_deg:
        return {"ok": False, "reason": "tilt", **payload}
    if xy_m is not None and xy_drift > xy_max_m:
        return {"ok": False, "reason": "xy_drift", **payload}
    return {"ok": True, "reason": None, **payload}
