"""体育运动技能：视觉伺服踢球（多轮闭环）。

参数走 :mod:`atri.tuning`：任务卡 params > ``config/kick.json`` > 代码默认值。
本文件只加读 tuning 的薄封装，**默认数值与行为保持不变**：
死区 1 cm、最多 5 轮、不收敛也踢、球距 4–40 cm 门闩。
"""
from __future__ import annotations

from typing import Any, Dict

from ..tuning import load_tuning, param_or
from .base import (
    Skill,
    SkillContext,
    _int_param,
    as_finite_float,
    failed,
    lateral_servo,
    perception_data,
)

# 横向死区：球偏离 ≤ 此值即认为已对准，直接踢。
KICK_DEADBAND_CM = 1.0
# 单次任务内的闭环迭代上限：对静态/坏观测不会无限空转。
KICK_MAX_ITERS = 5
# 每轮偏航步长 = clamp(x_cm * KICK_STEP_GAIN, ±KICK_STEP_CLAMP_DEG)。
KICK_STEP_GAIN = 0.5
KICK_STEP_CLAMP_DEG = 10.0
# 桌面尺度保护：过近够不着摆腿，过远一步走不到。任务卡可覆写。
KICK_MIN_DISTANCE_CM = 4.0
KICK_MAX_DISTANCE_CM = 40.0

# 代码默认值 = 设计值（未标定）。键名同时也是 config/kick.json 里可覆盖的键。
KICK_DEFAULTS: Dict[str, Any] = {
    "deadband_cm": KICK_DEADBAND_CM,
    "max_iters": KICK_MAX_ITERS,
    "step_gain": KICK_STEP_GAIN,
    "step_clamp_deg": KICK_STEP_CLAMP_DEG,
    "min_distance_cm": KICK_MIN_DISTANCE_CM,
    "max_distance_cm": KICK_MAX_DISTANCE_CM,
}


def _num(ctx: SkillContext, tuning: Dict[str, Any], key: str, *, integer: bool = False) -> float:
    """按 任务卡 > tuning 文件 > 代码默认值 取值，非法则回落默认值。"""
    default = KICK_DEFAULTS[key]
    raw = param_or(ctx.params, tuning, key, default)
    if integer:
        return float(_int_param({key: raw}, key, int(default)))
    value = as_finite_float(raw)
    if value is None or value <= 0.0:
        return float(default)
    return float(value)


class KickSkill(Skill):
    name = "kick"

    def run(self, ctx: SkillContext) -> Dict[str, Any]:
        t = load_tuning("kick", KICK_DEFAULTS)
        tuning = t.values

        obs, reason = perception_data(ctx, "ball")
        if reason:
            return failed(self.name, reason)

        raw_x = obs.get("x_cm", ctx.params.get("x_cm", 0.0))
        ball_x = as_finite_float(raw_x)
        if ball_x is None:
            return failed(self.name, f"球的横向偏移非法: {raw_x!r}")
        raw_dist = obs.get("distance_cm", ctx.params.get("distance_cm"))
        ball_dist = as_finite_float(raw_dist)
        if ball_dist is None or ball_dist <= 0.0:
            return failed(self.name, f"球距离非法或缺测距: {raw_dist!r}")

        min_dist = _num(ctx, tuning, "min_distance_cm")
        max_dist = _num(ctx, tuning, "max_distance_cm")
        if ball_dist < min_dist or ball_dist > max_dist:
            return failed(
                self.name,
                f"球距离 {ball_dist:g}cm 不在 [{min_dist:g}, {max_dist:g}] cm",
            )

        deadband = _num(ctx, tuning, "deadband_cm")
        max_iters = int(_num(ctx, tuning, "max_iters", integer=True))
        step_gain = _num(ctx, tuning, "step_gain")
        step_clamp = _num(ctx, tuning, "step_clamp_deg")

        ball_x, iterations, converged, reason = lateral_servo(
            ctx, "ball", ball_x, deadband, max_iters, step_gain, step_clamp
        )
        if reason:
            return failed(self.name, reason)

        print(
            f"  [Kick] 球相对偏移 x={ball_x}cm, 距离={ball_dist}cm, "
            f"迭代={iterations}, 收敛={converged}"
        )
        # 不收敛也尽力踢：踢球是"接触即成功"的尽力而为动作，最后一轮朝向已是最优。
        kick_result = ctx.cerebellum.kick(foot="right" if ball_x >= 0 else "left")

        ctx.tts("踢球动作完成")
        return {
            "skill": self.name,
            "status": "ok",
            "ball_x_cm": ball_x,
            "distance_cm": ball_dist,
            "iterations": iterations,
            "converged": converged,
            "kick": kick_result,
            "tuning_source": t.source_path.name if t.overridden else "code-defaults",
            "tuning_overridden": list(t.overridden),
            "tuning_warnings": list(t.warnings),
        }
