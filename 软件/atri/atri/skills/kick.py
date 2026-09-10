"""体育运动技能：视觉伺服踢球。"""
from __future__ import annotations

from typing import Any, Dict

from .base import Skill, SkillContext


class KickSkill(Skill):
    name = "kick"

    def run(self, ctx: SkillContext) -> Dict[str, Any]:
        obs = ctx.perceive("ball")
        ball_x = float(obs.get("x_cm", 0.0))
        ball_dist = float(obs.get("distance_cm", 12.0))

        print(f"  [Kick] 球相对偏移 x={ball_x}cm, 距离={ball_dist}cm")
        # 视觉伺服：根据球的横向偏移微调朝向
        if abs(ball_x) > 1.0:
            yaw = max(-10.0, min(10.0, ball_x / 2.0))
            ctx.cerebellum.set_pose({"left_hip_yaw": yaw, "right_hip_yaw": yaw})
        ctx.cerebellum.execute_motion("kick", obs)
        kick_result = ctx.cerebellum.kick(foot="right" if ball_x >= 0 else "left")

        ctx.tts("踢球动作完成")
        return {"skill": self.name, "status": "ok", "ball_x_cm": ball_x, "kick": kick_result}
