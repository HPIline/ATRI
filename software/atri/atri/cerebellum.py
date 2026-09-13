"""小脑控制层：20 关节舵机总线、步态生成、抓取/踢球/舞蹈动作与脚本运动调度。"""
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
    MAX_TURN_DEG,
    body_yaw_pose,
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
    """标准串行总线舵机抽象。无硬件时使用 MockServoBus。

    ⚠️ **真机实现必须遵守 `atri.config` 的换算口径**（`deg_to_pulse` / `pulse_to_deg` /
    `pulse_limits`），并实现下面这批"批量写 + 安全 + 遥测"语义；
    下位机固件（STM32）实现同一套语义，两端共用一份关节表（ID/符号/零偏/限位）。
    只实现 `set_angle` / `read_angle` 会导致：20 关节逐个发帧超时、
    标定前就带电锁轴、堵转时拿不到温度与电流。
    """

    # —— 基础 ——
    def set_angle(self, joint_id: int, deg: float) -> None:
        """模板方法：统一按关节限位钳制后，交给子类 _write_angle 下发。

        ``clamp_angle`` 会拒绝未知关节、非数字和 NaN/Inf，避免非有限值下发。
        真机驱动（如 ``Sts3215Bus``）可整体覆盖本方法。
        """
        name = JOINT_BY_ID.get(joint_id)
        if name is None:
            raise ValueError(f"未知关节 id: {joint_id!r}")
        self._write_angle(joint_id, clamp_angle(name, deg))

    def _write_angle(self, joint_id: int, deg: float) -> None:
        """子类实现：把已钳制的角度写入硬件（不再重复限位）。"""
        raise NotImplementedError

    def read_angle(self, joint_id: int) -> float:
        raise NotImplementedError

    # —— 批量写：一个控制周期内 20 关节一次发完（20 ms 周期的硬性前提）——
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
        """中位标定：以当前位置为零位（写成 2048）。

        ⚠️ 2026-09-12 订正：飞特的零位寄存器是 **31 号位置偏置**；旧注释写的
        「40 号地址写 128」有误——40 号是扭矩使能。真机实现见 `bus_sts3215.py`。
        """
        raise NotImplementedError


class MockServoBus(ServoBus):
    """内存舵机总线：记录指令并模拟绝对位置回传与遥测（限位由基类统一处理）。"""

    def __init__(self) -> None:
        self.angles = {spec["id"]: spec["rest_deg"] for spec in JOINTS.values()}
        self.command_log: List[Dict[str, float]] = []
        self.torque_on = True
        self.limits: Dict[int, tuple] = {}
        self.middle_set: List[int] = []

    def _write_angle(self, joint_id: int, deg: float) -> None:
        self.angles[joint_id] = deg
        self.command_log.append({"id": joint_id, "deg": deg})

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
        """模拟中位标定：记下 ID，并把内存角度归零。真机写的是寄存器 31。"""
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
        # 协作式中止信号：由 FSM（主线程）注册，帧循环边界检查；None 表示不中止。
        self._abort_event: Optional[threading.Event] = None

    def set_abort_event(self, event: Optional[threading.Event]) -> None:
        """注册/清除协作式中止信号（threading.Event），None 表示不中止。

        信号只在本类的帧循环边界被检查（线程安全）；命中后只提前结束自有轨迹，
        不会抢占正在阻塞的第三方调用，复位动作仍由调用方主线程执行。
        超时看门狗在 FSM/Brain：到期只置位本事件，不从定时器线程碰舵机。
        """
        self._abort_event = event

    def _aborted(self) -> bool:
        return self._abort_event is not None and self._abort_event.is_set()

    def aborted(self) -> bool:
        """对外可读的中止信号状态。

        多段路径（如二维码指示的一串动作）需要**在段与段之间**也检查中止：
        否则超时只在单段轨迹内部生效，下一段还会照跑，总时长失控。
        """
        return self._aborted()

    def set_pose(self, targets: Dict[str, float]) -> Dict[str, float]:
        """下发一组关节目标角（按名称），返回实际限位后的角度。

        走 `sync_write`：真机上是一条 SYNC WRITE 帧写完所有关节，
        而不是 20 次往返（后者在 20 ms 周期里会顶到总线时间上限）。
        未知关节名、NaN/Inf 一律抛 ValueError，不静默丢弃。
        """
        unknown = [name for name in targets if name not in JOINTS]
        if unknown:
            raise ValueError("未知关节: " + ", ".join(repr(name) for name in unknown))
        applied: Dict[str, float] = {}
        batch: Dict[int, float] = {}
        for name, deg in targets.items():
            clamped = clamp_angle(name, deg)
            requested = float(deg)  # clamp_angle 已确保可转换
            if clamped != requested:
                _warn_clamped(name, requested, clamped)
            batch[JOINTS[name]["id"]] = clamped
            applied[name] = clamped
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

    def turn(self, deg: float, **kwargs: Any) -> Dict[str, Any]:
        """踩步转体：若干步正弦步态，每步叠加髋 roll 转向占位。

        桌面尺度下约 30°/步；符号与 ``deg`` 同向。v2 没有 hip_yaw，用左右髋
        roll 反对称侧倾代替偏航（G4 未关闭）。开环关键帧，不是动力学平衡。
        """
        if isinstance(deg, bool):
            raise ValueError(f"deg 必须是有限数值，收到 {deg!r}")
        try:
            angle = float(deg)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"deg 必须是有限数值，收到 {deg!r}") from exc
        if not math.isfinite(angle):
            raise ValueError(f"deg 必须是有限数值，收到 {deg!r}")

        if abs(angle) > MAX_TURN_DEG:
            raise ValueError(f"deg={angle:g} 超出 ±{MAX_TURN_DEG:g}")

        steps = max(1, int(math.ceil(abs(angle) / 30.0)))
        yaw_per_step = angle / steps
        frames = self.generate_gait(steps=steps, **kwargs)
        frames_per_step = max(1, len(frames) // steps)
        applied = []
        for i, frame in enumerate(frames):
            progress = min(1.0, (i + 1) / max(1, len(frames)))
            yaw = yaw_per_step * math.ceil(progress * steps)
            # 无 hip_yaw：髋 roll 反对称侧倾作为转向占位。
            frame.update(body_yaw_pose(yaw))
            applied.append(frame)
        result = self.execute_trajectory(applied)
        result.update({"action": "turn", "deg": angle, "steps": steps,
                       "frames_per_step": frames_per_step})
        return result

    def kick(self, foot: str = "right") -> Dict[str, Any]:
        """预标定踢球动作（仿真迁移用）。"""
        side = "right" if foot == "right" else "left"
        hip = f"{side}_hip_pitch"
        knee = f"{side}_knee_pitch"
        ankle = f"{side}_ankle_pitch"
        self.home()
        # 膝限位是 [0, 90]；负膝角会被钳到 0，踢球必须用正膝角。
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
        """20 DOF 短舞序列（音舞同步占位）。"""
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
        executed = 0
        aborted = False
        for i, frame in enumerate(frames):
            if self._aborted():
                aborted = True
                break
            try:
                joints = {k: float(v) for k, v in frame["joints"].items()}
                duration_s = float(frame["duration_s"])
            except (TypeError, ValueError, KeyError) as exc:
                raise ActionLibraryError(f"frames[{i}] 关节角或时长不是数字: {exc}") from exc
            self.set_pose(joints)
            executed += 1
            self.sleeper(duration_s * dt_scale)
        result: Dict[str, Any] = {
            "action": action.get("action_id"),
            "frames": executed,
        }
        if aborted:
            result["aborted"] = True
        return result

    def execute_motion(self, instruction: str, observation: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """脚本运动调度：根据技能指令选择步态/关键帧动作。

        这是当前无 VLA 方案的核心入口。所有动作在 CPU 上本地完成，
        对应小脑层在 STM32 + IMU 上部署的规则控制。
        未知指令必须抛错，不能假装对齐成功。
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
            deg = 30.0
            if isinstance(observation, dict):
                raw = observation.get("deg", observation.get("turn_deg", 30.0))
                try:
                    number = float(raw)
                except (TypeError, ValueError, OverflowError):
                    number = 30.0
                if math.isfinite(number):
                    deg = number
            return self.turn(deg)
        # 显式对齐：用目标横向偏移动手臂，不是写死髋角
        if any(k in ins for k in ("对齐", "微调", "align", "视觉")):
            return self._align_arm(observation)
        raise ValueError(f"未知指令: {instruction!r}")

    def _align_arm(self, observation: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        obs = observation or {}
        blob = obs.get("object") if isinstance(obs.get("object"), dict) else obs
        x_cm = None
        if isinstance(blob, dict):
            raw = blob.get("x_cm")
            if raw is not None and not isinstance(raw, bool):
                try:
                    number = float(raw)
                except (TypeError, ValueError, OverflowError):
                    number = None
                if number is not None and math.isfinite(number):
                    x_cm = number
        if x_cm is None:
            return {"action": "align", "aligned": False}
        yaw = max(-15.0, min(15.0, x_cm * 1.5))
        reach = max(-15.0, min(15.0, -abs(x_cm)))
        elbow = max(-120.0, min(0.0, -10.0 - abs(x_cm)))
        if x_cm >= 0.0:
            targets = {
                "right_shoulder_roll": -abs(yaw),
                "right_shoulder_pitch": reach,
                "right_elbow_pitch": elbow,
            }
        else:
            targets = {
                "left_shoulder_roll": abs(yaw),
                "left_shoulder_pitch": reach,
                "left_elbow_pitch": elbow,
            }
        applied = self.set_pose(targets)
        applied["action"] = "align"
        applied["aligned"] = abs(x_cm) <= 2.0
        applied["x_cm"] = x_cm
        return applied
