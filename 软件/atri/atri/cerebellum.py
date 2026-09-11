"""小脑控制层：22 关节舵机总线、步态生成、抓取/踢球/舞蹈动作与脚本运动调度。"""
from __future__ import annotations

import math
import threading
import time
from typing import Any, Dict, List, Optional

from .config import (
    JOINT_BY_ID,
    JOINTS,
    MAX_BARS,
    MAX_STEPS,
    clamp_angle,
    rest_pose,
)


def _check_count(name: str, value: Any, hi: int) -> int:
    """校验步数/小节数为 1..hi 的整数（第二层防线，不依赖调用方先做校验）。"""
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= hi:
        raise ValueError(f"{name} 必须是 1..{hi} 的整数，收到 {value!r}")
    return value


def _warn_clamped(name: str, requested: float, applied: float) -> None:
    lo, hi = JOINTS[name]["limit_deg"]
    print(f"  [Cerebellum] 关节 {name} 请求 {requested}° 超出限位 [{lo}, {hi}]，实际下发 {applied}°")


class ServoBus:
    """标准串行总线舵机抽象。无硬件时使用 MockServoBus。"""

    def set_angle(self, joint_id: int, deg: float) -> None:
        """模板方法：统一按关节限位钳制后，交给子类 _write_angle 下发。"""
        name = JOINT_BY_ID.get(joint_id)
        if name is None:
            raise ValueError(f"未知关节 id: {joint_id!r}")
        self._write_angle(joint_id, clamp_angle(name, deg))

    def _write_angle(self, joint_id: int, deg: float) -> None:
        """子类实现：把已钳制的角度写入硬件（不再重复限位）。"""
        raise NotImplementedError

    def read_angle(self, joint_id: int) -> float:
        raise NotImplementedError


class MockServoBus(ServoBus):
    """内存舵机总线：记录指令并模拟绝对位置回传（限位由基类统一处理）。"""

    def __init__(self) -> None:
        self.angles = {spec["id"]: spec["rest_deg"] for spec in JOINTS.values()}
        self.command_log: List[Dict[str, float]] = []

    def _write_angle(self, joint_id: int, deg: float) -> None:
        self.angles[joint_id] = deg
        self.command_log.append({"id": joint_id, "deg": deg})

    def read_angle(self, joint_id: int) -> float:
        return self.angles[joint_id]


class Cerebellum:
    """小脑控制层：脚本动作库 + 步态生成 + 姿态微调。全部本地 CPU 可运行。"""

    def __init__(
        self,
        servo_bus: Optional[ServoBus] = None,
        sleeper: Any = None,
    ) -> None:
        self.bus = servo_bus or MockServoBus()
        # sleeper(dt_s) 用于推进时间；Webots 控制器传入 robot.step(ms) 包装，
        # 默认为 time.sleep，保持无仿真环境行为不变。
        self.sleeper = sleeper or time.sleep
        # 协作式中止信号：由 FSM（主线程）注册，帧循环边界检查；None 表示不中止。
        self._abort_event: Optional[threading.Event] = None

    def set_abort_event(self, event: Optional[threading.Event]) -> None:
        """注册/清除协作式中止信号（threading.Event），None 表示不中止。

        信号只在本类的帧循环边界被检查（线程安全）；命中后只提前结束自有轨迹，
        不会抢占正在阻塞的第三方调用，复位动作仍由调用方主线程执行。
        """
        self._abort_event = event

    def _aborted(self) -> bool:
        return self._abort_event is not None and self._abort_event.is_set()

    def set_pose(self, targets: Dict[str, float]) -> Dict[str, float]:
        """下发一组关节目标角（按名称），返回实际限位后的角度。"""
        unknown = [name for name in targets if name not in JOINTS]
        if unknown:
            raise ValueError("未知关节: " + ", ".join(repr(name) for name in unknown))
        applied: Dict[str, float] = {}
        for name, deg in targets.items():
            clamped = clamp_angle(name, deg)
            requested = float(deg)  # clamp_angle 已确保可转换
            if clamped != requested:
                _warn_clamped(name, requested, clamped)
            self.bus.set_angle(JOINTS[name]["id"], clamped)
            applied[name] = clamped
        return applied

    def home(self) -> Dict[str, float]:
        return self.set_pose(rest_pose())

    def get_pose(self) -> Dict[str, float]:
        pose = {}
        for name, spec in JOINTS.items():
            pose[name] = self.bus.read_angle(spec["id"])
        return pose

    def generate_gait(
        self,
        steps: int = 6,
        step_length_cm: float = 2.0,
        step_height_cm: float = 1.2,
        period_s: float = 0.8,
    ) -> List[Dict[str, float]]:
        """双足交替正弦步态（设计验证用）。返回按 20ms 采样的关键帧序列。"""
        steps = _check_count("steps", steps, MAX_STEPS)
        frames: List[Dict[str, float]] = []
        frames_per_step = max(10, int(period_s / 0.02))
        for i in range(steps * frames_per_step):
            t = i / frames_per_step
            phase = 2.0 * math.pi * t
            left_swing = math.sin(phase)
            right_swing = math.sin(phase + math.pi)
            left_amp = max(0.0, left_swing)
            right_amp = max(0.0, right_swing)

            frame = {
                "left_hip_pitch": 8.0 * left_amp * step_length_cm / 2.0,
                "left_knee_pitch": 12.0 * left_amp * step_height_cm,
                "left_ankle_pitch": -6.0 * left_amp,
                "right_hip_pitch": -8.0 * right_amp * step_length_cm / 2.0,
                "right_knee_pitch": 12.0 * right_amp * step_height_cm,
                "right_ankle_pitch": -6.0 * right_amp,
                "trunk_pitch": 1.5 * math.sin(phase),
                "trunk_roll": 1.0 * math.sin(phase / 2.0),
            }
            frames.append(frame)
        return frames

    def execute_trajectory(self, frames: List[Dict[str, float]], dt_s: float = 0.02) -> Dict[str, Any]:
        """按帧下发脚本轨迹，返回实际下发帧数与时长。

        每个帧边界检查 abort event（见 ``set_abort_event``）：置位后立即停止并返回
        已下发帧数（带 ``aborted=True``）。**只在自有帧循环内协作中止，无法抢占
        正在阻塞的第三方调用**；复位动作由调用方主线程在轨迹返回后执行。
        """
        executed = 0
        aborted = False
        for frame in frames:
            if self._aborted():
                aborted = True
                break
            self.set_pose(frame)
            executed += 1
            self.sleeper(dt_s)
        result: Dict[str, Any] = {
            "frames": executed,
            "duration_s": round(executed * dt_s, 3),
        }
        if aborted:
            result["aborted"] = True
        return result

    def walk(self, steps: int = 6, **kwargs: Any) -> Dict[str, Any]:
        steps = _check_count("steps", steps, MAX_STEPS)
        frames = self.generate_gait(steps=steps, **kwargs)
        return self.execute_trajectory(frames)

    def kick(self, foot: str = "right") -> Dict[str, Any]:
        """预标定踢球动作（仿真迁移用）。"""
        side = "right" if foot == "right" else "left"
        hip = f"{side}_hip_pitch"
        knee = f"{side}_knee_pitch"
        ankle = f"{side}_ankle_pitch"
        self.home()
        swing = [
            {hip: 18.0, knee: 8.0, ankle: 5.0},
            {hip: 26.0, knee: 18.0, ankle: 10.0},
            {hip: -10.0, knee: 5.0, ankle: -2.0},
            {},
        ]
        self.execute_trajectory(swing, dt_s=0.12)
        self.home()
        return {"action": "kick", "foot": foot}

    def grasp(self, side: str = "both") -> Dict[str, Any]:
        self.home()
        target = {}
        if side in ("left", "both"):
            target.update({
                "left_shoulder_pitch": 30.0,
                "left_shoulder_roll": 15.0,
                "left_elbow_pitch": -35.0,
                "left_gripper": 20.0,
            })
        if side in ("right", "both"):
            target.update({
                "right_shoulder_pitch": 30.0,
                "right_shoulder_roll": -15.0,
                "right_elbow_pitch": -35.0,
                "right_gripper": 20.0,
            })
        self.set_pose(target)
        self.sleeper(0.1)
        return {"action": "grasp", "side": side}

    def release(self, side: str = "both") -> Dict[str, Any]:
        target = {}
        if side in ("left", "both"):
            target["left_gripper"] = 0.0
        if side in ("right", "both"):
            target["right_gripper"] = 0.0
        self.set_pose(target)
        self.sleeper(0.1)
        self.home()
        return {"action": "release", "side": side}

    def dance(self, bars: int = 4) -> Dict[str, Any]:
        """22 DOF 短舞序列（音舞同步占位）。"""
        bars = _check_count("bars", bars, MAX_BARS)
        self.home()
        frames = []
        for i in range(bars * 8):
            t = i / 8.0
            frames.append({
                "head_yaw": 20.0 * math.sin(2.0 * math.pi * t),
                "head_pitch": 10.0 * math.sin(4.0 * math.pi * t),
                "trunk_roll": 4.0 * math.sin(2.0 * math.pi * t),
                "left_hip_pitch": 8.0 * math.sin(2.0 * math.pi * t),
                "right_hip_pitch": -8.0 * math.sin(2.0 * math.pi * t),
                "left_shoulder_pitch": 20.0 * math.sin(2.0 * math.pi * t),
                "right_shoulder_pitch": -20.0 * math.sin(2.0 * math.pi * t),
                "left_elbow_pitch": -25.0 + 15.0 * math.sin(4.0 * math.pi * t),
                "right_elbow_pitch": -25.0 - 15.0 * math.sin(4.0 * math.pi * t),
            })
        self.execute_trajectory(frames, dt_s=0.08)
        self.home()
        return {"action": "dance", "bars": bars}

    def play_action(self, action: Dict[str, Any], dt_scale: float = 1.0) -> Dict[str, Any]:
        """按动作库 JSON 执行关键帧序列（Webots 标定后可导入/回放）。

        action 使用 action_library 规范。执行前做轻量校验，失败抛 ActionLibraryError。
        """
        from .action_library import ActionLibraryError, validate_action

        errors = validate_action(action)
        if errors:
            raise ActionLibraryError("动作库校验失败:\n" + "\n".join(errors))
        frames = action["frames"]
        for i, frame in enumerate(frames):
            try:
                joints = {k: float(v) for k, v in frame["joints"].items()}
                duration_s = float(frame["duration_s"])
            except (TypeError, ValueError, KeyError) as exc:
                raise ActionLibraryError(f"frames[{i}] 关节角或时长不是数字: {exc}") from exc
            self.set_pose(joints)
            self.sleeper(duration_s * dt_scale)
        return {"action": action.get("action_id"), "frames": len(frames)}

    def execute_motion(self, instruction: str, observation: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """脚本运动调度：根据技能指令选择步态/关键帧动作。

        这是当前无 VLA 方案的核心入口。所有动作在 CPU 上本地完成，
        对应小脑层在 STM32 + IMU 上部署的规则控制。
        """
        ins = instruction or ""
        if any(k in ins for k in ("踢", "kick")):
            return self.kick(foot="right")
        if any(k in ins for k in ("抓", "grasp", "搬", "carry")):
            return self.grasp()
        if any(k in ins for k in ("放", "释放", "release")):
            return self.release()
        if any(k in ins for k in ("舞", "dance")):
            return self.dance(bars=2)
        if any(k in ins for k in ("走", "walk", "前", "循迹")):
            return self.walk(steps=4)
        if any(k in ins for k in ("转", "turn")):
            return self.set_pose({"left_hip_yaw": 8.0, "right_hip_yaw": 8.0})
        # 显式对齐分支：搬运技能会先做视觉伺服微调，这里不是未识别指令的兜底
        if any(k in ins for k in ("对齐", "微调", "align", "视觉")):
            return self.set_pose({
                "trunk_pitch": 1.0,
                "left_hip_pitch": 4.0,
                "right_hip_pitch": -4.0,
            })
        raise ValueError(f"未知指令: {instruction!r}")
