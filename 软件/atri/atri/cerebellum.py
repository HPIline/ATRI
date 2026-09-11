"""小脑控制层：22 关节舵机总线、步态生成、抓取/踢球/舞蹈动作与脚本运动调度。"""
from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Optional

from .config import JOINTS, clamp_angle, rest_pose


class ServoBus:
    """标准串行总线舵机抽象。无硬件时使用 MockServoBus。

    ⚠️ **真机实现必须遵守 `atri.config` 的换算口径**（`deg_to_pulse` / `pulse_to_deg` /
    `pulse_limits`），并实现下面这批"批量写 + 安全 + 遥测"语义；
    下位机固件（STM32）实现同一套语义，两端共用一份关节表（ID/符号/零偏/限位）。
    只实现 `set_angle` / `read_angle` 会导致：22 关节逐个发帧超时、
    标定前就带电锁轴、堵转时拿不到温度与电流。
    """

    # —— 基础 ——
    def set_angle(self, joint_id: int, deg: float) -> None:
        raise NotImplementedError

    def read_angle(self, joint_id: int) -> float:
        raise NotImplementedError

    # —— 批量写：一个控制周期内 22 关节一次发完（20 ms 周期的硬性前提）——
    def sync_write(self, targets: Dict[int, float]) -> None:
        """默认退化为逐个写；真机应实现为舵机总线的 SYNC WRITE 指令。"""
        for jid, deg in targets.items():
            self.set_angle(jid, deg)

    # —— 安全：上电先松轴，标定/装调完成后再使能 ——
    def set_torque_enable(self, joint_ids: List[int], enable: bool) -> None:
        raise NotImplementedError

    def relax_all(self) -> None:
        self.set_torque_enable(sorted(s["id"] for s in JOINTS.values()), False)

    # —— 遥测：堵转保护与温升实测的数据来源 ——
    def read_telemetry(self, joint_id: int) -> Dict[str, Any]:
        """返回 {pos_deg, load_pct, voltage_v, temp_c, current_a, moving}。"""
        raise NotImplementedError

    # —— bring-up：扫描 / 写限位寄存器 / 中位标定 ——
    def scan(self) -> List[int]:
        """总线扫描，返回在线 ID（bring-up 第一个动作）。"""
        raise NotImplementedError

    def write_limits(self, joint_id: int, pulse_lo: int, pulse_hi: int) -> None:
        """把 min/max angle 寄存器写成"机械安全范围"（见 pulse_limits）。"""
        raise NotImplementedError

    def set_middle(self, joint_id: int) -> None:
        """中位标定：以当前位置为零位（飞特：40 号地址写 128）。"""
        raise NotImplementedError


class MockServoBus(ServoBus):
    """内存舵机总线：记录指令并做限位，模拟绝对位置回传与遥测。"""

    def __init__(self) -> None:
        self.angles = {spec["id"]: spec["rest_deg"] for spec in JOINTS.values()}
        self.command_log: List[Dict[str, float]] = []
        self.torque_on = True
        self.limits: Dict[int, tuple] = {}
        self.middle_set: List[int] = []

    def set_angle(self, joint_id: int, deg: float) -> None:
        name = [n for n, s in JOINTS.items() if s["id"] == joint_id][0]
        clamped = clamp_angle(name, deg)
        self.angles[joint_id] = clamped
        self.command_log.append({"id": joint_id, "deg": clamped})

    def read_angle(self, joint_id: int) -> float:
        return self.angles[joint_id]

    def set_torque_enable(self, joint_ids: List[int], enable: bool) -> None:
        self.torque_on = bool(enable)

    def read_telemetry(self, joint_id: int) -> Dict[str, Any]:
        """按"离中位越远越吃力"造一条合理曲线，供上层逻辑先行联调。"""
        deg = self.angles[joint_id]
        load = min(100.0, abs(deg) * 1.5)
        return {"pos_deg": deg, "load_pct": round(load, 1),
                "voltage_v": 11.1, "temp_c": round(28.0 + load * 0.15, 1),
                "current_a": round(0.15 + load * 0.02, 3),
                "moving": False}

    def scan(self) -> List[int]:
        return sorted(self.angles)

    def write_limits(self, joint_id: int, pulse_lo: int, pulse_hi: int) -> None:
        self.limits[joint_id] = (int(pulse_lo), int(pulse_hi))

    def set_middle(self, joint_id: int) -> None:
        self.middle_set.append(joint_id)
        self.angles[joint_id] = 0.0


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

    def set_pose(self, targets: Dict[str, float]) -> Dict[str, float]:
        """下发一组关节目标角（按名称），返回实际限位后的角度。

        走 `sync_write`：真机上是一条 SYNC WRITE 帧写完所有关节，
        而不是 22 次往返（后者在 20 ms 周期里会顶到总线时间上限）。
        """
        applied: Dict[str, float] = {}
        batch: Dict[int, float] = {}
        for name, deg in targets.items():
            if name not in JOINTS:
                continue
            deg = clamp_angle(name, deg)
            batch[JOINTS[name]["id"]] = deg
            applied[name] = deg
        if batch:
            self.bus.sync_write(batch)
        return applied

    def relax(self) -> None:
        """松轴（安全姿态）：装配、搬运、标定前必须调用。"""
        self.bus.relax_all()

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
        for frame in frames:
            self.set_pose(frame)
            self.sleeper(dt_s)
        return {"frames": len(frames), "duration_s": round(len(frames) * dt_s, 3)}

    def walk(self, steps: int = 6, **kwargs: Any) -> Dict[str, Any]:
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
            {hip: 18.0, knee: -8.0, ankle: 5.0},
            {hip: 26.0, knee: -18.0, ankle: 10.0},
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
        for frame in frames:
            joints = {k: float(v) for k, v in frame["joints"].items()}
            self.set_pose(joints)
            self.sleeper(float(frame["duration_s"]) * dt_scale)
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
        if any(k in ins for k in ("舞", "dance")):
            return self.dance(bars=2)
        if any(k in ins for k in ("走", "walk", "前", "循迹")):
            return self.walk(steps=4)
        if any(k in ins for k in ("转", "turn")):
            return self.set_pose({"left_hip_yaw": 8.0, "right_hip_yaw": 8.0})
        # 默认：视觉伺服对齐微调
        return self.set_pose({
            "trunk_pitch": 1.0,
            "left_hip_pitch": 4.0,
            "right_hip_pitch": -4.0,
        })
