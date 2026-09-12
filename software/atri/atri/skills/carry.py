"""物品搬运技能：视觉对齐（闭环）-> 夹取 -> 平移 -> 释放。"""
from __future__ import annotations

from typing import Any, Dict

from ..config import MAX_STEPS
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

# 步长约 2cm/步：上限与 MAX_STEPS 对齐，防止观测距离被放大成超长轨迹。
MAX_CARRY_DISTANCE_CM = 2.0 * MAX_STEPS

# 对准死区：目标横向偏差 ≤ 此值即认为对准，可以抓取。
CARRY_DEADBAND_CM = 2.0
# 单次任务内的闭环迭代上限。
CARRY_MAX_ITERS = 5
# 每轮偏航步长 = clamp(x_cm * CARRY_STEP_GAIN, ±CARRY_STEP_CLAMP_DEG)。
CARRY_STEP_GAIN = 0.5
CARRY_STEP_CLAMP_DEG = 10.0
# 放弃抓取阈值：闭环后横向偏差仍超此值，说明够不着，宁可失败也不盲抓。
CARRY_GIVE_UP_CM = 4.0


class CarrySkill(Skill):
    name = "carry"

    def run(self, ctx: SkillContext) -> Dict[str, Any]:
        obs, reason = perception_data(ctx, "object")
        if reason:
            return failed(self.name, reason)

        target = obs.get("target") or ctx.params.get("target") or "红块"
        raw_distance = obs.get("distance_cm", ctx.params.get("distance_cm"))
        distance_cm = as_finite_float(raw_distance)
        if distance_cm is None or distance_cm <= 0.0:
            return failed(self.name, f"搬运距离非法或缺测距: {raw_distance!r}")
        if distance_cm > MAX_CARRY_DISTANCE_CM:
            return failed(
                self.name,
                f"搬运距离 {distance_cm:g}cm 超出上限 {MAX_CARRY_DISTANCE_CM:g}cm",
            )
        x_cm = as_finite_float(obs.get("x_cm"))
        if x_cm is None:
            x_cm = 0.0

        deadband = _positive_param(ctx.params, "deadband_cm", CARRY_DEADBAND_CM)
        max_iters = _int_param(ctx.params, "max_iters", CARRY_MAX_ITERS)

        # 多轮闭环：感知 -> 增量偏航 -> 重新感知，直到目标进死区或达到上限。
        x_cm, iterations, aligned, reason = lateral_servo(
            ctx, "object", x_cm, deadband, max_iters, CARRY_STEP_GAIN, CARRY_STEP_CLAMP_DEG
        )
        if reason:
            return failed(self.name, reason)

        print(
            f"  [Carry] 目标={target}, 距离={distance_cm}cm, 横向={x_cm}cm, "
            f"迭代={iterations}, 对准={aligned}"
        )
        if abs(x_cm) > CARRY_GIVE_UP_CM:
            return failed(self.name, f"目标横向偏差 {x_cm:g}cm 过大，放弃抓取")

        steps = max(2, int(distance_cm // 2.0))
        grasp_result = ctx.cerebellum.grasp()
        walk_result = ctx.cerebellum.walk(steps=steps, **ctx.gait)
        release_result = ctx.cerebellum.release()

        ctx.tts(f"已将{target}搬运至目标区")
        return {
            "skill": self.name,
            "status": "ok",
            "target": target,
            "distance_cm": distance_cm,
            "steps": steps,
            "iterations": iterations,
            "aligned": aligned,
            "grasp": grasp_result,
            "walk": walk_result,
            "release": release_result,
        }
