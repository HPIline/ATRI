"""体育运动技能：视觉伺服踢球（多轮闭环）。

参数走 :mod:`atri.tuning`：任务卡 params > ``config/kick.json`` > 代码默认值。
本文件只加读 tuning 的薄封装，**默认数值与行为保持不变**：
死区 1 cm、最多 5 轮、不收敛也踢、球距 4–40 cm 门闩。
"""
from __future__ import annotations

from typing import Any, Dict

from ..tuning import effective_overrides, load_tuning, param_or, tuning_source_label
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


def _fail(t: Any, reason: str, params: Any = None) -> Dict[str, Any]:
    """统一的技能失败结果：带上参数出处与告警，否则现场"改了没生效"查不出来。

    （与 ``skills/carry.py::_fail`` / ``skills/dance.py`` 同一口径：
    失败路径也必须能看到 ``tuning_warnings``。）
    """
    result = failed("kick", reason)
    result["tuning_source"] = tuning_source_label(t, params)
    result["tuning_overridden"] = list(effective_overrides(t, params))
    result["tuning_warnings"] = list(t.warnings)
    return result


class KickSkill(Skill):
    name = "kick"

    def run(self, ctx: SkillContext) -> Dict[str, Any]:
        # warn=print：配置写错时现场要看得见（与 carry/dance 同口径）。
        t = load_tuning("kick", KICK_DEFAULTS, warn=print)
        tuning = t.values
        def fail(reason: str) -> Dict[str, Any]:
            """本技能的失败出口：绑好本次的任务卡 params（出处标注要用）。"""
            return _fail(t, reason, ctx.params)


        obs, reason = perception_data(ctx, "ball")
        if reason:
            return fail(reason)

        # 横向偏移取值顺序：观测 → 任务卡 params → **判失败**。
        # 不再有 0.0 这个隐含默认：把"没量到"当成"正前方"就是对着空气摆腿，
        # 与 carry（缺 x_cm 不夹）和 validation.py 的「转换失败返回 None，绝不猜」同口径。
        obs_x = obs.get("x_cm") if "x_cm" in obs else None
        ball_x = as_finite_float(obs_x)
        if ball_x is None:
            ball_x = as_finite_float(ctx.params.get("x_cm"))
        if ball_x is None:
            return fail(
                f"球的横向偏移缺失或非法: 观测={obs.get('x_cm')!r} 任务卡={ctx.params.get('x_cm')!r}"
                "（不把「没量到」当成正前方）",
            )
        raw_dist = obs.get("distance_cm", ctx.params.get("distance_cm"))
        ball_dist = as_finite_float(raw_dist)
        if ball_dist is None or ball_dist <= 0.0:
            return fail(f"球距离非法或缺测距: {raw_dist!r}")

        min_dist = _num(ctx, tuning, "min_distance_cm")
        max_dist = _num(ctx, tuning, "max_distance_cm")
        if ball_dist < min_dist or ball_dist > max_dist:
            return fail(
                f"球距离 {ball_dist:g}cm 不在 [{min_dist:g}, {max_dist:g}] cm"
            )

        deadband = _num(ctx, tuning, "deadband_cm")
        max_iters = int(_num(ctx, tuning, "max_iters", integer=True))
        step_gain = _num(ctx, tuning, "step_gain")
        step_clamp = _num(ctx, tuning, "step_clamp_deg")

        ball_x, iterations, converged, reason = lateral_servo(
            ctx, "ball", ball_x, deadband, max_iters, step_gain, step_clamp
        )
        if reason:
            return fail(reason)

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
            "tuning_source": tuning_source_label(t, ctx.params),
            "tuning_overridden": list(effective_overrides(t, ctx.params)),
            "tuning_warnings": list(t.warnings),
        }
