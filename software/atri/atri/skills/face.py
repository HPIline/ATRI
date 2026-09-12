"""人脸技能：真识别优先，未配置真识别通路时沿用原有感知接口路径。

**真识别通路**（需 ``ctx.face_recognizer`` + ``ctx.frame_source``，构造见 ``sim.build_face_recognizer``）：
    取帧 → 检测 → 对齐 → 128 维特征 → 人脸库比对 → 播报姓名 / 显式拒识
这是 T-01 的实际能力，实测见 ``design/handoff/T-01-LFW评测报告.md``。

**退化通路**（未配置上述两者时）保留原有实现不变：走感知接口，数据来源写在 ``source`` 字段里。

> 对外口径（2026-09-12 落地）：赛题原文是「人脸识别」，真识别通路优先。
> 退化通路仍允许 ``source="params"`` 的 ``expect_names[0]`` 兜底，演示日志必须打印 source，
> 不得把这条路径说成识别成功率。
"""
from __future__ import annotations

from typing import Any, Dict, List

from .base import Skill, SkillContext, as_finite_float, failed, perception_data

DEFAULT_EXPECT_NAMES = ["测试员A"]
UNKNOWN_SPEECH = "对不起，我不认识你"
NO_FACE_SPEECH = "我没有看到人脸"


class FaceSkill(Skill):
    name = "face"

    def run(self, ctx: SkillContext) -> Dict[str, Any]:
        if ctx.face_recognizer is not None and ctx.frame_source is not None:
            return self._run_recognition(ctx)
        return self._run_perception(ctx)

    # ────────────────── 真识别通路（新增） ──────────────────

    def _run_recognition(self, ctx: SkillContext) -> Dict[str, Any]:
        expect = self._expect_names(ctx)
        frame = ctx.grab_frame()
        if frame is None:
            return failed(self.name, "取帧来源返回空帧")

        result = ctx.face_recognizer.recognize(frame)
        name = result.recognized_name
        best = result.best

        if name is None:
            # 拒识 / 无人脸：**绝不猜**。没认出来就是没认出来，不从任务卡借名字。
            if result.found:
                ctx.tts(UNKNOWN_SPEECH)
                return {
                    "skill": self.name,
                    "status": "rejected",
                    "reason": "人脸已检出但相似度未达阈值，判定为不认识",
                    "source": "recognition",
                    "name": None,
                    "face_count": len(result.faces),
                    "faces": [f.to_dict() for f in result.faces],
                }
            ctx.tts(NO_FACE_SPEECH)
            return {
                "skill": self.name,
                "status": "no_face",
                "reason": "画面中未检出人脸",
                "source": "recognition",
                "name": None,
                "face_count": 0,
                "faces": [],
            }

        name = str(name)
        if expect and name not in expect:
            return failed(self.name, f"识别到 {name}，不在预期名单 {expect}")

        ctx.tts(f"你好，{name}")
        return {
            "skill": self.name,
            "status": "ok",
            "name": name,
            "source": "recognition",
            # 置信度用相似度表示：这是**实测**得到的可比量，不是拍出来的 0.93
            "confidence": round(best.similarity, 4) if best else 0.0,
            "similarity": round(best.similarity, 4) if best else None,
            "margin": round(best.margin, 4) if best else None,
            "face_count": len(result.faces),
            "faces": [f.to_dict() for f in result.faces],
        }

    # ────────────────── 退化通路（原有实现，未改动） ──────────────────

    def _expect_names(self, ctx: SkillContext) -> List[str]:
        """解析任务卡的 expect_names。语义与原实现保持一致（空列表按未配置处理）。"""
        raw_expect = ctx.params.get("expect_names")
        if raw_expect is None:
            return []
        if isinstance(raw_expect, (list, tuple)):
            return [str(item) for item in (raw_expect or DEFAULT_EXPECT_NAMES)]
        return [str(raw_expect)]

    def _run_perception(self, ctx: SkillContext) -> Dict[str, Any]:
        obs, reason = perception_data(ctx, "face", optional=True)
        if reason:
            return failed(self.name, reason)

        expect = self._expect_names(ctx)

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
