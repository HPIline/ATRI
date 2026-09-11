"""体育运动技能：视觉伺服踢球。"""
from __future__ import annotations

from typing import Any, Dict

from .base import Skill, SkillContext, as_finite_float, failed, perception_data


class KickSkill(Skill):
    name = "kick"

    def run(self, ctx: SkillContext) -> Dict[str, Any]:
        obs, reason = perception_data(ctx, "ball")
        if reason:
            return failed(self.name, reason)

        # 观测 -> 任务卡参数 -> 判失败（与 carry 技能同一约定）：缺测距不能当成具体值。
        # OpenCV 路径在焦距未标定时把 distance_cm 置 None，与整条缺键等价。
        raw_x = obs.get("x_cm", ctx.params.get("x_cm", 0.0))
        ball_x = as_finite_float(raw_x)
        if ball_x is None:
            return failed(self.name, f"球的横向偏移非法: {raw_x!r}")
        raw_dist = obs.get("distance_cm", ctx.params.get("distance_cm"))
        ball_dist = as_finite_float(raw_dist)
        if ball_dist is None or ball_dist <= 0.0:
            return failed(self.name, f"球距离非法或缺测距: {raw_dist!r}")

        print(f"  [Kick] 球相对偏移 x={ball_x}cm, 距离={ball_dist}cm")
        # 视觉伺服：根据球的横向偏移微调朝向
        if abs(ball_x) > 1.0:
            yaw = max(-10.0, min(10.0, ball_x / 2.0))
            ctx.cerebellum.set_pose({"left_hip_yaw": yaw, "right_hip_yaw": yaw})
        kick_result = ctx.cerebellum.kick(foot="right" if ball_x >= 0 else "left")

        ctx.tts("踢球动作完成")
        return {
            "skill": self.name,
            "status": "ok",
            "ball_x_cm": ball_x,
            "distance_cm": ball_dist,
            "kick": kick_result,
        }
