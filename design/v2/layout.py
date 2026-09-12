"""装配几何约定：夹板贴舵机端面，连杆是两侧铝板，不是悬空方块。"""
from __future__ import annotations

from typing import Sequence, Tuple

Vec = Tuple[float, float, float]

SERVO_AXIAL = 35.0
IDLE_T = 1.5
HORN_T = 4.0
SANDWICH = 13.2  # 舵机半宽 12.35 + 板半厚


def v_along(axis: Sequence[float], d: float) -> Vec:
    return (axis[0] * d, axis[1] * d, axis[2] * d)


def idle_center(axis: Sequence[float]) -> Vec:
    return v_along(axis, -(SERVO_AXIAL / 2.0 + IDLE_T / 2.0))


def horn_center(axis: Sequence[float]) -> Vec:
    return v_along(axis, SERVO_AXIAL / 2.0 + HORN_T / 2.0)
