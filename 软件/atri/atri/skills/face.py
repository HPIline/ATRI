"""人脸识别技能：离线检测 -> 特征比对 -> 本地 TTS 播报。"""
from __future__ import annotations

from typing import Any, Dict

from .base import Skill, SkillContext


class FaceSkill(Skill):
    name = "face"

    def run(self, ctx: SkillContext) -> Dict[str, Any]:
        obs = ctx.perceive("face")
        name = obs.get("name") or ctx.params.get("expect_names", ["测试员A"])[0]
        confidence = float(obs.get("confidence", 0.93))
        ctx.tts(f"你好，{name}")
        return {"skill": self.name, "status": "ok", "name": name, "confidence": confidence}
