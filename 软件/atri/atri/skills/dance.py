"""娱乐交互技能：离线关键词 -> 音乐 -> 22 DOF 短舞。"""
from __future__ import annotations

from typing import Any, Dict

from .base import Skill, SkillContext


class DanceSkill(Skill):
    name = "dance"

    def run(self, ctx: SkillContext) -> Dict[str, Any]:
        obs = ctx.perceive("speech")
        keyword = obs.get("keyword") or ctx.params.get("keyword", "跳舞")
        print(f"  [Dance] 识别到离线关键词: {keyword}")
        ctx.cerebellum.execute_motion("dance", obs)
        dance_result = ctx.cerebellum.dance(bars=int(ctx.params.get("bars", 2)))
        ctx.tts("舞蹈结束，谢谢观看")
        return {"skill": self.name, "status": "ok", "keyword": keyword, "dance": dance_result}
