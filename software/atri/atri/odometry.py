"""标称位移模型（Nominal Odometry）—— **未标定，不是实测**。

## 为什么需要它

赛题场景判据（``design/packages/scenario_set.json`` 的 S-02）里有一条
``path_error_mm_max: 50``（到位误差）。而小脑层目前**不记录机器人走到哪了**：
``Cerebellum.walk()`` 只生成关节轨迹往下发，没有任何位移或里程计概念。
所以「按指示路径行走」今天只能验到「指令序列正确」，**到位程度无从谈起**。

本模块补一个**标称**位移模型：按步态参数把每段动作折算成名义位移与朝向变化，
让路径"算得出来"，并给实机标定留好接口（``config/odometry.json``）。

## ⚠ 三条必须记住的限制

1. 这是**几何折算**，既不是测量值，也不是物理仿真的结果；
2. 折算系数（每步位移、转向效率）**从未在实物上标定过**；
3. 因此本模块输出的任何"终点 / 路径误差"都是**设计值**，
   在文档与报告里必须标注 ``nominal / 未标定``，**不得当作实测指标引用**。

标定方式（实机阶段）：让机器人直走 N 步、原地转 90°，量出真实位移与角度，
把结果写进 ``config/odometry.json``，本模块会自动切到 ``calibrated`` 状态。
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path as _FilePath
from typing import Any, Dict, List, Optional

from .path_plan import Path as QrPath
from .path_plan import PathError

# 默认值来自 config/robot.json 的 motion.gait（设计值，非实测）
DEFAULT_STEP_LENGTH_CM = 2.0
DEFAULT_TURN_EFFICIENCY = 1.0

CALIBRATION_PATH = _FilePath(__file__).resolve().parent.parent / "config" / "odometry.json"

STATUS_NOMINAL = "nominal-uncalibrated"
STATUS_CALIBRATED = "calibrated"

# 这些动作不产生平面位移，但会占用时间；显式列出以免"忘了算"被当成没走
NO_DISPLACEMENT_ACTIONS = {"dance", "kick", "carry", "grasp", "release"}


def _safe_float(value: Any, default: float = 0.0) -> float:
    """把可能脏的参数转成有限 float。

    标称模型是**事后推演**，不该因为某个参数是 NaN/字符串就抛异常把整个技能结果毁掉
    （参数合法性由路径校验负责，这里只是不崩）。转不动就按默认值算，并在段上留 note。
    """
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return number if math.isfinite(number) else default


@dataclass
class Pose:
    """平面位姿：起点坐标系，x 前、y 左（右手系），heading 为朝向角（度）。"""

    x_cm: float = 0.0
    y_cm: float = 0.0
    heading_deg: float = 0.0

    def to_dict(self) -> Dict[str, float]:
        return {
            "x_cm": round(self.x_cm, 3),
            "y_cm": round(self.y_cm, 3),
            "heading_deg": round(self.heading_deg, 3),
        }


@dataclass
class SegmentTrace:
    index: int
    action: str
    params: Dict[str, Any]
    pose_after: Pose
    displacement_cm: float
    heading_change_deg: float
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "action": self.action,
            "params": self.params,
            "pose_after": self.pose_after.to_dict(),
            "displacement_cm": round(self.displacement_cm, 3),
            "heading_change_deg": round(self.heading_change_deg, 3),
            "note": self.note,
        }


@dataclass
class PathTrace:
    """一条路径的标称轨迹。"""

    start: Pose
    segments: List[SegmentTrace] = field(default_factory=list)
    status: str = STATUS_NOMINAL
    step_length_cm: float = DEFAULT_STEP_LENGTH_CM
    turn_efficiency: float = DEFAULT_TURN_EFFICIENCY

    @property
    def end(self) -> Pose:
        return self.segments[-1].pose_after if self.segments else self.start

    @property
    def total_distance_cm(self) -> float:
        return sum(seg.displacement_cm for seg in self.segments)

    @property
    def is_calibrated(self) -> bool:
        return self.status == STATUS_CALIBRATED

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "calibrated": self.is_calibrated,
            "step_length_cm": self.step_length_cm,
            "turn_efficiency": self.turn_efficiency,
            "start": self.start.to_dict(),
            "end": self.end.to_dict(),
            "total_distance_cm": round(self.total_distance_cm, 3),
            "segments": [seg.to_dict() for seg in self.segments],
            "caveat": (
                "标称值：按步态参数几何折算，**未经实物标定**，不可当作实测指标"
                if not self.is_calibrated
                else "已按 config/odometry.json 标定"
            ),
        }


class NominalOdometry:
    """把路径折算成标称位移。**不是仿真，也不代表真机会这么走。**"""

    def __init__(
        self,
        step_length_cm: float = DEFAULT_STEP_LENGTH_CM,
        turn_efficiency: float = DEFAULT_TURN_EFFICIENCY,
        status: str = STATUS_NOMINAL,
    ) -> None:
        if not math.isfinite(step_length_cm) or step_length_cm <= 0:
            raise PathError(f"step_length_cm 必须是正有限值，收到 {step_length_cm!r}")
        if not math.isfinite(turn_efficiency) or turn_efficiency <= 0:
            raise PathError(f"turn_efficiency 必须是正有限值，收到 {turn_efficiency!r}")
        self.step_length_cm = float(step_length_cm)
        self.turn_efficiency = float(turn_efficiency)
        self.status = status

    @classmethod
    def from_config(cls, path: str | _FilePath | None = None) -> "NominalOdometry":
        """读 ``config/odometry.json``；文件不存在就返回未标定的默认模型。

        格式::

            {"step_length_cm": 1.8, "turn_efficiency": 0.94,
             "measured_at": "2026-10-01", "method": "直走 10 步量位移 / 原地转 90°"}
        """
        p = _FilePath(path) if path is not None else CALIBRATION_PATH
        if not p.exists():
            return cls()
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        return cls(
            step_length_cm=float(data.get("step_length_cm", DEFAULT_STEP_LENGTH_CM)),
            turn_efficiency=float(data.get("turn_efficiency", DEFAULT_TURN_EFFICIENCY)),
            status=STATUS_CALIBRATED,
        )

    def simulate(self, path: QrPath, start: Optional[Pose] = None) -> PathTrace:
        """逐段推演标称位姿。"""
        pose = start or Pose()
        trace = PathTrace(
            start=Pose(**pose.to_dict()),
            status=self.status,
            step_length_cm=self.step_length_cm,
            turn_efficiency=self.turn_efficiency,
        )

        for index, seg in enumerate(path.segments):
            before = Pose(**pose.to_dict())
            note = ""

            if seg.action == "walk":
                raw_steps = seg.params.get("steps", 0)
                steps = _safe_float(raw_steps, 0.0)
                if steps != raw_steps:
                    note = f"steps={raw_steps!r} 非有限数值，标称位移按 0 计"
                distance = steps * self.step_length_cm
                rad = math.radians(pose.heading_deg)
                pose.x_cm += distance * math.cos(rad)
                pose.y_cm += distance * math.sin(rad)
            elif seg.action == "turn":
                raw_deg = seg.params.get("deg", 0.0)
                deg = _safe_float(raw_deg, 0.0) * self.turn_efficiency
                if deg != raw_deg:
                    note = f"deg={raw_deg!r} 非有限数值，标称转角按 0 计"
                pose.heading_deg = (pose.heading_deg + deg) % 360.0
            elif seg.action in NO_DISPLACEMENT_ACTIONS:
                note = "该动作不产生平面位移"
            else:
                note = "未知动作，按不产生位移处理"

            trace.segments.append(
                SegmentTrace(
                    index=index,
                    action=seg.action,
                    params=dict(seg.params),
                    pose_after=Pose(**pose.to_dict()),
                    displacement_cm=math.hypot(pose.x_cm - before.x_cm, pose.y_cm - before.y_cm),
                    heading_change_deg=pose.heading_deg - before.heading_deg,
                    note=note,
                )
            )
        return trace


def path_length_cm(trace: PathTrace) -> float:
    """标称路径总长（cm）。"""
    return trace.total_distance_cm


def endpoint_error_cm(a: Pose, b: Pose) -> float:
    """两个位姿的平面距离（cm）。用于实机阶段比较"标称终点 vs 实测终点"。"""
    return math.hypot(a.x_cm - b.x_cm, a.y_cm - b.y_cm)
