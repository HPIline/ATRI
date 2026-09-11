"""机器人拓扑与配置加载。

关节拓扑严格对齐申报方案：22 DOF = 双腿 10 + 双臂 8 + 躯干 2 + 头部 2。
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict

DOF_COUNT = 22

# 单条指令上限：技能层与运动层共用的合法性边界，防止越界参数生成超长轨迹。
MAX_STEPS = 20
MAX_BARS = 8
MAX_TURN_DEG = 135.0
VALID_ACTIONS = {"walk", "turn", "kick", "carry", "dance", "grasp", "release"}

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

# 舵机总线按 id 下发，需要 O(1) 反查关节名以统一做限位。
JOINT_BY_ID: Dict[int, str] = {spec["id"]: name for name, spec in JOINTS.items()}


def _assert_topology() -> None:
    ids = [v["id"] for v in JOINTS.values()]
    if len(JOINTS) != DOF_COUNT:
        raise RuntimeError(f"关节数量 {len(JOINTS)} != {DOF_COUNT}")
    if ids != list(range(DOF_COUNT)):
        raise RuntimeError("关节 id 必须为连续的 0..21")
    if sum(GROUP_DOF.values()) != DOF_COUNT:
        raise RuntimeError(f"分组自由度之和 != {DOF_COUNT}")


_assert_topology()


def clamp_angle(name: str, deg: float) -> float:
    """把关节角钳制到限位内；未知关节、非数字或非有限值一律抛 ValueError。"""
    spec = JOINTS.get(name)
    if spec is None:
        raise ValueError(f"未知关节: {name!r}")
    try:
        value = float(deg)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"关节 {name} 收到无效角度: {deg!r}") from exc
    if not math.isfinite(value):
        raise ValueError(f"关节 {name} 收到非有限角度: {deg!r}")
    lo, hi = spec["limit_deg"]
    return max(float(lo), min(float(hi), value))


def rest_pose() -> Dict[str, float]:
    return {name: float(spec["rest_deg"]) for name, spec in JOINTS.items()}


# ---------------------------------------------------------------------------
# 真机接口契约：角度 ↔ 舵机脉冲
#
# ⚠️ **上位机与下位机唯一的换算口径**，固件必须实现同一套公式：
#      pulse = zero_pulse + sign × deg × 4096/360
#      deg   = (pulse − zero_pulse) × 360/4096 × sign
#   其中：
#      sign       = +1 / −1，机械装配决定的转向（左右镜像件必然相反）
#      zero_pulse = 该关节机械零位对应的脉冲（出厂中位 2048，装配标定后修正）
#   所以**装配完必须回填 sign / zero_pulse**（见 config/calibration.json），
#   否则会出现"两条腿往相反方向走"这类现场事故。
# ---------------------------------------------------------------------------
MID_PULSE = 2048
PULSE_PER_DEG = 4096.0 / 360.0          # ≈ 11.378 脉冲/度
LIMIT_MARGIN_DEG = 3.0                  # 舵机限位寄存器相对软件限位再放宽的量

# 走线分支：只用于线束标识与故障定位；**电气上是同一条并联总线**
BRANCH_OF_GROUP = {
    "head": "torso_head", "trunk": "torso_head",
    "leg_l": "leg_l", "leg_r": "leg_r",
    "arm_l": "arms", "arm_r": "arms",
}

for _n, _s in JOINTS.items():
    _s.setdefault("sign", 1)                   # 默认 +1，装配标定后回填
    _s.setdefault("zero_pulse", MID_PULSE)     # 默认出厂中位
    _s.setdefault("branch", BRANCH_OF_GROUP[_s["group"]])
del _n, _s


def deg_to_pulse(name: str, deg: float) -> int:
    """角度（度，软件正方向）→ 舵机绝对位置脉冲（0–4095）。"""
    spec = JOINTS[name]
    pulse = spec["zero_pulse"] + spec["sign"] * float(deg) * PULSE_PER_DEG
    return int(round(max(0.0, min(4095.0, pulse))))


def pulse_to_deg(name: str, pulse: float) -> float:
    """舵机绝对位置脉冲 → 角度（度，软件正方向）。"""
    spec = JOINTS[name]
    return (float(pulse) - spec["zero_pulse"]) / PULSE_PER_DEG * spec["sign"]


def pulse_limits(name: str, margin_deg: float = LIMIT_MARGIN_DEG) -> tuple:
    """要写进舵机 min/max angle 寄存器的脉冲范围。

    比**软件限位**再放宽 `margin_deg`（避免软件抖动一下就被舵机自己截断），
    但仍必须落在**机械硬限位之内**——装配后请核对每只关节的实际可转范围。
    """
    lo, hi = JOINTS[name]["limit_deg"]
    a, b = deg_to_pulse(name, lo - margin_deg), deg_to_pulse(name, hi + margin_deg)
    return (min(a, b), max(a, b))


def joint_table() -> Dict[str, Dict[str, Any]]:
    """真机调试/固件对齐用的关节总表（ID、分支、方向、零偏、脉冲限位）。"""
    out: Dict[str, Dict[str, Any]] = {}
    for name, spec in JOINTS.items():
        lo, hi = pulse_limits(name)
        out[name] = {
            "id": spec["id"], "group": spec["group"], "branch": spec["branch"],
            "limit_deg": list(spec["limit_deg"]), "rest_deg": spec["rest_deg"],
            "sign": spec["sign"], "zero_pulse": spec["zero_pulse"],
            "pulse_range": [lo, hi],
        }
    return out


CALIBRATION_PATH = (Path(__file__).resolve().parent.parent
                    / "config" / "calibration.json")


def load_calibration(path: str | Path | None = None) -> Dict[str, Any]:
    """读入装配标定表并**就地覆盖** JOINTS 的 sign / zero_pulse。

    文件不存在时返回 {}（表示仍用出厂默认值）。格式：
        {"joints": {"head_yaw": {"sign": -1, "zero_pulse": 2043}, ...}}
    调用者：真机总线构造时、bring-up 工具、系统启动自检。
    """
    p = Path(path) if path is not None else CALIBRATION_PATH
    if not p.exists():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    applied: Dict[str, Any] = {}
    for name, cal in (data.get("joints") or {}).items():
        if name not in JOINTS:
            continue
        spec = JOINTS[name]
        if "sign" in cal:
            spec["sign"] = -1 if int(cal["sign"]) < 0 else 1
        if "zero_pulse" in cal:
            spec["zero_pulse"] = int(max(0, min(4095, int(cal["zero_pulse"]))))
        applied[name] = {"sign": spec["sign"], "zero_pulse": spec["zero_pulse"]}
    return applied


def load_robot_config(path: str | Path | None = None) -> Dict[str, Any]:
    if path is None:
        path = Path(__file__).resolve().parent.parent / "config" / "robot.json"
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)
