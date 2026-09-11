"""娱乐交互技能：离线关键词 -> 音乐 -> 22 DOF 短舞。"""
from __future__ import annotations

from typing import Any, Dict

from ..config import MAX_BARS
from .base import Skill, SkillContext, as_int_in_range, failed, perception_data


class DanceSkill(Skill):
    name = "dance"

    def run(self, ctx: SkillContext) -> Dict[str, Any]:
        obs, reason = perception_data(ctx, "speech", optional=True)
        if reason:
            return failed(self.name, reason)

        keyword = obs.get("keyword") or ctx.params.get("keyword") or "跳舞"
        bars = as_int_in_range(ctx.params.get("bars", 2), 1, MAX_BARS)
        if bars is None:
            return failed(
                self.name, f"bars 非法: {ctx.params.get('bars')!r}（应为 1..{MAX_BARS} 整数）"
            )

        print(f"  [Dance] 识别到离线关键词: {keyword}")
        dance_result = ctx.cerebellum.dance(bars=bars)
        ctx.tts("舞蹈结束，谢谢观看")
        return {"skill": self.name, "status": "ok", "keyword": keyword, "dance": dance_result}
