"""物品搬运技能：视觉对齐 -> 夹取 -> 平移 -> 释放。"""
from __future__ import annotations

from typing import Any, Dict

from .base import Skill, SkillContext


class CarrySkill(Skill):
    name = "carry"

    def run(self, ctx: SkillContext) -> Dict[str, Any]:
        obs = ctx.perceive("object")
        target = obs.get("target") or ctx.params.get("target", "红块")
        distance_cm = float(obs.get("distance_cm", 8.0))

        print(f"  [Carry] 目标={target}, 距离={distance_cm}cm, 视觉对齐中...")
        ctx.cerebellum.execute_motion("align", obs)

        grasp_result = ctx.cerebellum.grasp()
        walk_result = ctx.cerebellum.walk(steps=max(2, int(distance_cm // 2.0)))
        release_result = ctx.cerebellum.release()

        ctx.tts(f"已将{target}搬运至目标区")
        return {
            "skill": self.name,
            "status": "ok",
            "target": target,
            "grasp": grasp_result,
            "walk": walk_result,
            "release": release_result,
        }
