"""体育运动技能：视觉伺服踢球（多轮闭环）。"""
from __future__ import annotations

from typing import Any, Dict

from .base import (
    Skill,
    SkillContext,
    _int_param,
    _positive_param,
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


class KickSkill(Skill):
    name = "kick"

    def run(self, ctx: SkillContext) -> Dict[str, Any]:
        obs, reason = perception_data(ctx, "ball")
        if reason:
            return failed(self.name, reason)

        # 观测 -> 任务卡参数 -> 判失败：缺测距不能当成具体值。
        # OpenCV 路径在焦距未标定时把 distance_cm 置 None，与整条缺键等价。
        raw_x = obs.get("x_cm", ctx.params.get("x_cm", 0.0))
        ball_x = as_finite_float(raw_x)
        if ball_x is None:
            return failed(self.name, f"球的横向偏移非法: {raw_x!r}")
        raw_dist = obs.get("distance_cm", ctx.params.get("distance_cm"))
        ball_dist = as_finite_float(raw_dist)
        if ball_dist is None or ball_dist <= 0.0:
            return failed(self.name, f"球距离非法或缺测距: {raw_dist!r}")

        deadband = _positive_param(ctx.params, "deadband_cm", KICK_DEADBAND_CM)
        max_iters = _int_param(ctx.params, "max_iters", KICK_MAX_ITERS)

        # 多轮闭环：感知 -> 增量偏航 -> 重新感知，直到球进死区或达到上限。
        ball_x, iterations, converged, reason = lateral_servo(
            ctx, "ball", ball_x, deadband, max_iters, KICK_STEP_GAIN, KICK_STEP_CLAMP_DEG
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
        }
