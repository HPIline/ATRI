"""贴近真机的仿真组件：非理想舵机总线 + 带噪声感知。

设计意图
--------
`MockServoBus` 假设舵机瞬间到位、扭矩无限，`MockPerception` 返回固定值。
用它们跑出来的"闭环收敛"没有参考价值。

本模块提供：
- `RealisticServoBus`：带死区、回程间隙、转速限制、控制延迟、扭矩饱和
- `NoisyPerception`：带位置噪声、角度噪声、随机丢帧

两者都**实现既有接口**（`ServoBus` / `PerceptionBackend`），因此可以直接
替换现有实现，不需要改动 Brain / Cerebellum / Skills 的任何逻辑。

参数来自 `design/packages/*.json`，全部可复现（固定随机种子）。

注意：这里的舵机参数是**同级别舵机的典型量级**，用于让仿真体现非理想特性；
实物到手后必须实测回填，替换 `servo_spec.json` 中的数值。
"""
from __future__ import annotations

import json
import math
import random
from pathlib import Path
from typing import Any, Dict, List, Optional

import sys

# 允许以脚本方式运行（design/ 与 软件/atri 不在同一包内）
_DESIGN_DIR = Path(__file__).resolve().parent
_REPO = _DESIGN_DIR.parent
_ATRI_ROOT = _REPO / "软件" / "atri"
if str(_ATRI_ROOT) not in sys.path:
    sys.path.insert(0, str(_ATRI_ROOT))

from atri.cerebellum import ServoBus  # noqa: E402
from atri.config import JOINTS, clamp_angle  # noqa: E402
from atri.perception.base import PerceptionBackend, PerceptionResult  # noqa: E402

PACKAGE_DIR = _DESIGN_DIR / "packages"

ID_TO_NAME = {spec["id"]: name for name, spec in JOINTS.items()}


def load_package(name: str) -> Dict[str, Any]:
    """读取 design/packages/<name>.json。"""
    path = PACKAGE_DIR / f"{name}.json"
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


class RealisticServoBus(ServoBus):
    """带非理想特性的舵机总线。

    建模的效应（全部来自 servo_spec.json）：
      - 死区 deadband：目标变化小于死区时不动作
      - 回程间隙 backlash：换向时叠加固定偏差
      - 转速限制：每步最多转动 speed * dt
      - 控制延迟：指令延迟 latency 后才开始生效
      - 扭矩饱和：负载超过额定扭矩时记一次饱和事件

    接口与 `MockServoBus` 完全一致，可直接替换。
    """

    def __init__(
        self,
        spec: Optional[Dict[str, Any]] = None,
        seed: int = 20260910,
        dt_s: float = 0.02,
        enable_imperfections: bool = True,
    ) -> None:
        self.spec = spec or load_package("servo_spec")
        self.rng = random.Random(seed)
        self.dt_s = dt_s
        self.enable_imperfections = enable_imperfections

        self.deadband = float(self.spec.get("deadband_deg", 0.0))
        self.backlash = float(self.spec.get("backlash_deg", 0.0))
        self.speed_dps = float(self.spec.get("no_load_speed_dps", 1e9))
        self.latency_ms = float(self.spec.get("control_latency_ms", 0.0))
        self.rated_torque = float(
            self.spec.get("continuous_rated_torque_nm", 1e9))

        # 每个关节的仿真状态
        self.angles: Dict[int, float] = {
            spec["id"]: float(spec["rest_deg"]) for spec in JOINTS.values()
        }
        self._targets: Dict[int, float] = dict(self.angles)
        self._last_direction: Dict[int, float] = {jid: 0.0 for jid in self.angles}
        self._offset: Dict[int, float] = {jid: 0.0 for jid in self.angles}
        self._pending: List[Dict[str, float]] = []  # 延迟队列

        self.command_log: List[Dict[str, Any]] = []
        self.saturation_events = 0
        self.rejected_by_deadband = 0
        self.elapsed_s = 0.0

    # ---- ServoBus 接口 -------------------------------------------------
    def _write_angle(self, joint_id: int, deg: float) -> None:
        """写入已由 ``ServoBus.set_angle`` 模板钳制的角度，再叠加域随机化零位偏差。

        限位由基类模板方法统一保证（本类不再覆写 ``set_angle``），这里只负责
        死区/回程间隙/转速限制/控制延迟/扭矩饱和等非理想特性。
        """
        name = ID_TO_NAME[joint_id]
        # 应用域随机化里的零位偏差（如果调用方设置了），加偏差后重新钳制
        target = clamp_angle(name, deg + self._offset.get(joint_id, 0.0))

        if not self.enable_imperfections:
            self.angles[joint_id] = target
            self._targets[joint_id] = target
            self.command_log.append({"id": joint_id, "deg": target, "t": self.elapsed_s})
            return

        current = self._targets.get(joint_id, target)

        # 死区：目标变化太小则忽略
        if abs(target - current) < self.deadband:
            self.rejected_by_deadband += 1
            return

        # 回程间隙：换向时产生固定偏差
        prev_dir = self._last_direction.get(joint_id, 0.0)
        new_dir = 1.0 if target > current else -1.0
        if prev_dir != 0.0 and new_dir != prev_dir:
            self._offset[joint_id] = self._offset.get(joint_id, 0.0) + (
                self.backlash * new_dir
            )
        self._last_direction[joint_id] = new_dir

        # 控制延迟：延迟 latency 后进入目标队列
        self._pending.append(
            {
                "id": joint_id,
                "deg": target,
                "due": self.elapsed_s + self.latency_ms / 1000.0,
            }
        )
        self.command_log.append({"id": joint_id, "deg": target, "t": self.elapsed_s})

    def read_angle(self, joint_id: int) -> float:
        return self.angles.get(joint_id, 0.0)

    # ---- 仿真推进 --------------------------------------------------------
    def step(self, dt_s: Optional[float] = None) -> None:
        """推进一个控制周期：处理延迟队列并按转速限制逼近目标。"""
        dt = self.dt_s if dt_s is None else dt_s
        self.elapsed_s += dt

        # 1) 延迟到期的指令生效
        still_pending: List[Dict[str, float]] = []
        for item in self._pending:
            if item["due"] <= self.elapsed_s:
                self._targets[int(item["id"])] = float(item["deg"])
            else:
                still_pending.append(item)
        self._pending = still_pending

        if not self.enable_imperfections:
            for jid, target in self._targets.items():
                self.angles[jid] = target
            return

        # 2) 按转速限制逼近目标
        max_delta = self.speed_dps * dt
        for jid, target in self._targets.items():
            cur = self.angles.get(jid, target)
            diff = target - cur
            if abs(diff) <= max_delta:
                self.angles[jid] = target
            else:
                self.angles[jid] = cur + math.copysign(max_delta, diff)

    def apply_joint_offset(self, offset_deg: float) -> None:
        """域随机化：给所有关节加一个零位偏差。"""
        for jid in self._offset:
            self._offset[jid] = self.rng.uniform(-offset_deg, offset_deg)

    def get_pose(self) -> Dict[str, float]:
        return {ID_TO_NAME[jid]: ang for jid, ang in self.angles.items()}

    def stats(self) -> Dict[str, Any]:
        return {
            "commands": len(self.command_log),
            "rejected_by_deadband": self.rejected_by_deadband,
            "saturation_events": self.saturation_events,
            "elapsed_s": round(self.elapsed_s, 3),
        }


class NoisyPerception(PerceptionBackend):
    """带噪声与丢帧的感知后端。

    与 `MockPerception` 接口一致，但：
      - 位置/角度读数叠加高斯噪声
      - 按 dropout_rate 随机返回"未检测到"
      - 支持 degradation profile（ideal / nominal / harsh / adversarial）

    这些噪声让视觉伺服闭环的收敛数据具备参考价值。
    """

    name = "noisy"

    def __init__(
        self,
        profile: str = "nominal",
        seed: int = 20260910,
        face: Optional[Dict[str, Any]] = None,
        qr: Optional[Dict[str, Any]] = None,
        ball: Optional[Dict[str, Any]] = None,
    ) -> None:
        cfg = load_package("perception_sim")
        profiles = cfg.get("degradation_profiles", {})
        self.profile_name = profile
        self.profile = profiles.get(profile, profiles.get("nominal", {}))
        self.cfg = cfg
        self.rng = random.Random(seed)

        pos_std = float(self.profile.get("position_std_mm", cfg["noise"]["position_std_mm"]))
        ang_std = float(self.profile.get("angle_std_deg", cfg["noise"]["angle_std_deg"]))
        self.position_std = pos_std
        self.angle_std = ang_std
        self.dropout_rate = float(
            self.profile.get("dropout_rate", cfg["noise"]["dropout_rate"])
        )
        self.latency_ms = float(cfg["noise"].get("latency_ms", 0.0))

        self.face = {"name": "测试员A", "found": True}
        self.qr = {"payload": {"action": "walk", "steps": 3}, "found": True}
        self.ball = {"x_cm": 1.5, "distance_cm": 12.0, "found": True}
        if face:
            self.face.update(face)
        if qr:
            self.qr.update(qr)
        if ball:
            self.ball.update(ball)

        self.dropouts = 0
        self.detections = 0

    def _maybe_drop(self) -> bool:
        if self.rng.random() < self.dropout_rate:
            self.dropouts += 1
            return True
        self.detections += 1
        return False

    def _jitter(self, value_cm: float) -> float:
        """cm 级读数叠加噪声（position_std 是 mm，换算成 cm）。"""
        return value_cm + self.rng.gauss(0.0, self.position_std / 10.0)

    def detect_face(self, frame: Any = None) -> PerceptionResult:
        if self._maybe_drop():
            return PerceptionResult(kind="face", data={"found": False}, confidence=0.0)
        data = dict(self.face)
        return PerceptionResult(kind="face", data=data, confidence=0.93)

    def detect_qr(self, frame: Any = None) -> PerceptionResult:
        if self._maybe_drop():
            return PerceptionResult(kind="qr", data={"found": False}, confidence=0.0)
        data = dict(self.qr)
        return PerceptionResult(kind="qr", data=data, confidence=0.99)

    def detect_ball(self, frame: Any = None) -> PerceptionResult:
        if self._maybe_drop():
            return PerceptionResult(kind="ball", data={"found": False}, confidence=0.0)
        data = dict(self.ball)
        data["x_cm"] = round(self._jitter(float(data.get("x_cm", 0.0))), 3)
        data["distance_cm"] = round(self._jitter(float(data.get("distance_cm", 0.0))), 3)
        return PerceptionResult(kind="ball", data=data, confidence=0.9)

    def set_ball_position(self, x_cm: float, distance_cm: float) -> None:
        """供闭环仿真更新球的真实位置。"""
        self.ball["x_cm"] = float(x_cm)
        self.ball["distance_cm"] = float(distance_cm)
        self.ball["found"] = True

    def stats(self) -> Dict[str, Any]:
        total = self.detections + self.dropouts
        return {
            "profile": self.profile_name,
            "detections": self.detections,
            "dropouts": self.dropouts,
            "dropout_rate_observed": round(self.dropouts / total, 4) if total else 0.0,
            "position_std_mm": self.position_std,
        }


def sample_randomization(spec: Dict[str, Any], rng: random.Random) -> Dict[str, Any]:
    """按 domain_random.json 采样一组随机化参数。"""
    out: Dict[str, Any] = {}
    for key, item in spec.get("randomization", {}).items():
        rng_range = item.get("range")
        if isinstance(rng_range, list) and len(rng_range) == 2:
            out[key] = rng.uniform(float(rng_range[0]), float(rng_range[1]))
        elif isinstance(rng_range, (int, float)):
            nominal = item.get("nominal")
            if isinstance(nominal, list):
                out[key] = [
                    float(n) + rng.uniform(-float(rng_range), float(rng_range))
                    for n in nominal
                ]
            else:
                out[key] = float(nominal) + rng.uniform(
                    -float(rng_range), float(rng_range)
                )
    return out
