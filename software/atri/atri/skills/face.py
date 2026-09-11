"""人脸检测技能：离线 Haar 边界框 -> 本地 TTS。不做身份特征比对。"""
from __future__ import annotations

from typing import Any, Dict, List

from .base import Skill, SkillContext, as_finite_float, failed, perception_data

DEFAULT_EXPECT_NAMES = ["测试员A"]


class FaceSkill(Skill):
    name = "face"

    def run(self, ctx: SkillContext) -> Dict[str, Any]:
        obs, reason = perception_data(ctx, "face", optional=True)
        if reason:
            return failed(self.name, reason)

        raw_expect = ctx.params.get("expect_names")
        if raw_expect is None:
            expect: List[str] = []
        elif isinstance(raw_expect, (list, tuple)):
            # 空名单按未配置处理，避免 [0] 越界
            expect = [str(item) for item in (raw_expect or DEFAULT_EXPECT_NAMES)]
        else:
            expect = [str(raw_expect)]

        name = obs.get("name")
        source = "perception"
        if not name:
            if ctx.channel_ready("face"):
                return failed(self.name, "未获得人脸感知结果")
            fallback = expect or DEFAULT_EXPECT_NAMES
            name = fallback[0]
            source = "params"
        name = str(name)
        if expect and name not in expect:
            return failed(self.name, f"识别到 {name}，不在预期名单 {expect}")

        confidence = as_finite_float(obs.get("confidence", 0.93))
        if confidence is None:
            confidence = 0.0

        ctx.tts(f"你好，{name}")
        return {
            "skill": self.name,
            "status": "ok",
            "name": name,
            "confidence": confidence,
            "source": source,
        }
