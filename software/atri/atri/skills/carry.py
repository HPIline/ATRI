"""物品搬运技能：视觉对齐 -> 夹取 -> 平移 -> 释放。"""
from __future__ import annotations

from typing import Any, Dict

from ..config import MAX_STEPS
from .base import Skill, SkillContext, as_finite_float, failed, perception_data

# 步长约 2cm/步：上限与 MAX_STEPS 对齐，防止观测距离被放大成超长轨迹。
MAX_CARRY_DISTANCE_CM = 2.0 * MAX_STEPS


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
        steps = max(2, int(distance_cm // 2.0))

        x_cm = as_finite_float(obs.get("x_cm"))
        if x_cm is None:
            x_cm = 0.0
        print(f"  [Carry] 目标={target}, 距离={distance_cm}cm, 横向={x_cm}cm")
        if abs(x_cm) > 2.0:
            ctx.cerebellum.execute_motion("align", {"object": obs})
        if abs(x_cm) > 4.0:
            return failed(self.name, f"目标横向偏差 {x_cm:g}cm 过大，放弃抓取")

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
            "grasp": grasp_result,
            "walk": walk_result,
            "release": release_result,
        }
