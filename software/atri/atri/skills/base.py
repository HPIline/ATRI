"""技能基类与任务上下文。"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from ..perception.base import PerceptionError


@dataclass
class SkillContext:
    task_id: str
    task_name: str
    params: Dict[str, Any]
    cerebellum: Any
    observation: Optional[Dict[str, Any]] = None
    log: List[str] = None
    perception: Any = None
    tts_engine: Any = None
    gait: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.log is None:
            self.log = []

    def perceive(self, key: str) -> Dict[str, Any]:
        """读取感知项数据。

        感知后端抛错或观测值不是对象时，返回带 ``found=False`` 的失败标记，
        由技能统一判失败，避免异常把整张任务卡推入 ERROR。
        """
        if self.observation is not None and key in self.observation:
            value = self.observation[key]
            if isinstance(value, dict):
                return value
            return {"found": False, "error": f"观测 {key} 类型非法: {type(value).__name__}"}
        if self.perception is not None:
            method = getattr(self.perception, f"detect_{key}", None)
            if method is not None:
                try:
                    result = method()
                except PerceptionError as exc:
                    return {"found": False, "error": f"{type(exc).__name__}: {exc}"}
                if result is not None and getattr(result, "data", None):
                    return dict(result.data)
        return {}

    def channel_ready(self, key: str) -> bool:
        """该感知项是否有数据来源：观测里出现，或后端提供 detect_<key>。"""
        if self.observation is not None and key in self.observation:
            return True
        return self.perception is not None and hasattr(self.perception, f"detect_{key}")

    def tts(self, text: str) -> None:
        if self.tts_engine is not None:
            self.tts_engine.speak(text)
        else:
            print(f"  [TTS] {text}")
        self.log.append(f"tts: {text}")


def as_finite_float(value: Any) -> Optional[float]:
    """把观测/指令里的值转成有限 float；非数值或 NaN/Inf 返回 None。"""
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def as_int_in_range(value: Any, low: int, high: int) -> Optional[int]:
    """解析指定区间内的整数值；bool、字符串、非整数浮点与越界值返回 None。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        number = value
    elif isinstance(value, float) and value.is_integer():
        number = int(value)
    else:
        return None
    return number if low <= number <= high else None


def failed(skill: str, reason: str) -> Dict[str, Any]:
    """构造统一的技能失败结果。"""
    return {"skill": skill, "status": "failed", "reason": reason}


def perception_data(
    ctx: SkillContext, kind: str, *, optional: bool = False
) -> Tuple[Dict[str, Any], Optional[str]]:
    """读取并校验感知项，返回 ``(数据, 失败原因)``。

    ``found`` 键存在时必须是 bool：``False`` 判未命中，非 bool 判类型非法。
    仓库内所有感知后端都写 bool，非 bool 只可能来自外部注入的观测，而
    ``"False"``/``"0"`` 这类字符串在 Python 里为真，按真值判定会把"没看见"
    当成"看见了"并真的下发动作。观测项为空、或通道已接入却拿不到数据同样算失败；
    ``optional=True`` 且感知通道完全未接入（Mock 场景）时返回成功空数据，允许技能按任务卡参数兜底。
    """
    data = ctx.perceive(kind)
    if not isinstance(data, dict):
        return {}, f"{kind} 感知结果类型非法: {type(data).__name__}"
    if "found" in data:
        flag = data["found"]
        if not isinstance(flag, bool):
            return data, f"{kind} 感知 found 类型非法: {type(flag).__name__}（只接受 bool）"
        if not flag:
            detail = data.get("error")
            return data, (f"{kind} 感知未命中: {detail}" if detail
                          else f"{kind} 感知未命中（found 为假）")
    if not data:
        if optional and not ctx.channel_ready(kind):
            return data, None
        return data, f"未获得 {kind} 感知数据"
    return data, None


def _positive_param(params: Dict[str, Any], key: str, default: float) -> float:
    """取任务卡参数里的正数；非法/缺失回落到默认值，不因参数笔误把任务卡炸掉。"""
    value = as_finite_float(params.get(key, default))
    return value if value is not None and value > 0.0 else default


def _int_param(params: Dict[str, Any], key: str, default: int) -> int:
    """取任务卡参数里 1..100 的整数；非法/缺失回落到默认值。"""
    value = as_int_in_range(params.get(key, default), 1, 100)
    return value if value is not None else default


def lateral_servo(
    ctx: SkillContext,
    kind: str,
    x0: float,
    deadband_cm: float,
    max_iters: int,
    step_gain: float,
    step_clamp_deg: float,
) -> Tuple[float, int, bool, Optional[str]]:
    """多轮横向视觉伺服：沿 hip_yaw 做增量偏航修正，直到 |x| 进死区或达到上限。

    每轮：把本轮测到的横向偏差换算成一步偏航（``step = clamp(x * step_gain)``），
    **累加**进身体 yaw 并下发，然后重新感知。只有「增量累加」才能让
    ``x_cm = x_true - gain*yaw`` 的一维几何收敛；绝对定位会来回震荡。

    返回 ``(最终 x_cm, 迭代次数, 是否收敛, 失败原因)``。中途感知失败时返回
    失败原因，机器人停在当前 yaw，由技能决定是否放弃。``x0`` 是技能已校验过
    的首轮横向偏差。
    """
    yaw = 0.0
    x = x0
    iterations = 0
    while abs(x) > deadband_cm and iterations < max_iters:
        step = max(-step_clamp_deg, min(step_clamp_deg, x * step_gain))
        yaw += step
        ctx.cerebellum.set_pose({"left_hip_yaw": yaw, "right_hip_yaw": yaw})
        iterations += 1
        obs, reason = perception_data(ctx, kind)
        if reason:
            return x, iterations, False, reason
        # 与技能首轮读取同一兜底口径：观测缺 x_cm 时回落到任务卡参数，避免
        # 「首轮能用 params 兜底、闭环内却因缺键判失败」的不一致。
        new_x = as_finite_float(obs.get("x_cm", ctx.params.get("x_cm", 0.0)))
        if new_x is None:
            return x, iterations, False, f"第 {iterations} 轮重新感知 {kind} 横向偏移缺失"
        x = new_x
    return x, iterations, abs(x) <= deadband_cm, None


class Skill:
    name = "base"

    def run(self, ctx: SkillContext) -> Dict[str, Any]:
        raise NotImplementedError
