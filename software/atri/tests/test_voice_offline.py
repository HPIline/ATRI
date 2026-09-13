"""T-05 离线语音：可选 vosk 后端 + 关键词门闩。

没装 vosk / 没模型时：真引擎用例 skip，主路径（匹配、假引擎、技能门闩、评测脚本）必须全绿。
禁止在本文件里 pip install。
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from atri.cerebellum import Cerebellum, MockServoBus
from atri.skills.base import SkillContext
from atri.skills.dance import DEFAULT_KEYWORDS, DanceSkill, UNKNOWN_SPEECH
from atri.voice import MockKeywordRecognizer, MockTTS, VoiceError, match_keyword
from atri.voice.vosk import (
    KeywordSpeechPerception,
    VoskKeywordRecognizer,
    build_recognizer,
    vosk_available,
)


def _has_real_vosk() -> bool:
    try:
        import vosk  # noqa: F401
    except ImportError:
        return False
    return True


class SpyDance(Cerebellum):
    def __init__(self):
        super().__init__(servo_bus=MockServoBus(), sleeper=lambda dt: None)
        self.dances = 0

    def dance(self, bars=2):
        self.dances += 1
        return super().dance(bars=bars)


class FakeKaldi:
    def __init__(self, text: str) -> None:
        self.text = text

    def AcceptWaveform(self, pcm: bytes) -> bool:
        return True

    def Result(self) -> str:
        return json.dumps({"text": self.text}, ensure_ascii=False)

    def FinalResult(self) -> str:
        return self.Result()


class FakeVosk:
    def __init__(self, text: str = "请跳舞") -> None:
        self.text = text
        self.grammar = None

    def Model(self, path: str):
        return SimpleNamespace(path=path)

    def KaldiRecognizer(self, model, sample_rate, grammar=None):
        self.grammar = grammar
        return FakeKaldi(self.text)


class TestKeywordMatch(unittest.TestCase):
    def test_longest_hit_wins(self):
        self.assertEqual(match_keyword("请跳舞吧", ("舞", "跳舞")), "跳舞")
        self.assertEqual(match_keyword("挥手鞠躬", ("挥", "挥手")), "挥手")

    def test_miss_is_empty(self):
        self.assertEqual(match_keyword("前进", ("跳舞", "挥手")), "")
        self.assertEqual(match_keyword("", DEFAULT_KEYWORDS), "")
        self.assertEqual(match_keyword("跳舞", ()), "")


class TestVoskOptional(unittest.TestCase):
    def test_missing_engine_not_available(self):
        rec = VoskKeywordRecognizer(model_path="/no/such/model")
        self.assertFalse(rec.available())
        self.assertIsNone(build_recognizer(model_path="/no/such/model"))

    def test_voice_package_import_does_not_need_vosk(self):
        import atri.voice as voice

        self.assertIs(voice.MockKeywordRecognizer, MockKeywordRecognizer)

    def test_injected_fake_engine_recognizes_keyword(self):
        fake = FakeVosk("现在请跳舞")
        rec = VoskKeywordRecognizer(
            model_path="/tmp/fake-vosk-model",
            vosk_module=fake,
            model=object(),
        )
        self.assertTrue(rec.available())
        self.assertEqual(rec.recognize(b"\x01\x00\x02\x00"), "跳舞")

    def test_injected_fake_engine_rejects_unknown(self):
        fake = FakeVosk("帮我起飞")
        rec = VoskKeywordRecognizer(
            model_path="/tmp/fake-vosk-model",
            vosk_module=fake,
            model=object(),
        )
        self.assertEqual(rec.recognize(b"\x01\x00"), "")

    def test_recognize_without_engine_raises(self):
        rec = VoskKeywordRecognizer(model_path="")
        rec._vosk = None
        rec._model = None
        with mock.patch.dict(sys.modules, {"vosk": None}):
            with self.assertRaises(VoiceError):
                rec.recognize(b"\x00\x00")

    def test_vosk_available_helper_false_without_model(self):
        self.assertFalse(vosk_available(vosk_module=FakeVosk(), model_path=""))


class TestKeywordSpeechPerception(unittest.TestCase):
    def test_found_false_when_engine_unavailable(self):
        rec = VoskKeywordRecognizer(model_path="")
        perception = KeywordSpeechPerception(rec)
        self.assertFalse(perception.available())
        result = perception.detect_speech(b"")
        self.assertEqual(result.kind, "speech")
        self.assertFalse(result.data.get("found"))
        self.assertNotEqual(perception.name, "mock")
        self.assertNotIn("mock", perception.name)

    def test_detect_speech_uses_recognizer(self):
        rec = MockKeywordRecognizer(keywords=("跳舞",))
        perception = KeywordSpeechPerception(rec)
        result = perception.detect_speech()
        self.assertTrue(result.data["found"])
        self.assertEqual(result.data["keyword"], "跳舞")


class TestDanceSpeechGate(unittest.TestCase):
    def test_unknown_keyword_fails(self):
        cere = SpyDance()
        tts = MockTTS()
        ctx = SkillContext(
            task_id="T-05",
            task_name="舞",
            params={"bars": 1},
            cerebellum=cere,
            observation={"speech": {"keyword": "起飞", "found": True}},
            tts_engine=tts,
        )
        result = DanceSkill().run(ctx)
        self.assertNotEqual(result.get("status"), "ok")
        self.assertEqual(cere.dances, 0)
        self.assertIn(UNKNOWN_SPEECH, tts.spoken)

    def test_params_fallback_without_channel(self):
        cere = SpyDance()
        tts = MockTTS()
        ctx = SkillContext(
            task_id="T-05",
            task_name="舞",
            params={"keyword": "跳舞", "bars": 1},
            cerebellum=cere,
            observation={},
            tts_engine=tts,
        )
        result = DanceSkill().run(ctx)
        self.assertEqual(result.get("status"), "ok")
        self.assertEqual(result.get("source"), "params")
        self.assertEqual(cere.dances, 1)
        self.assertNotIn(UNKNOWN_SPEECH, tts.spoken)

    def test_perception_recognizer_hit(self):
        cere = SpyDance()
        tts = MockTTS()
        rec = MockKeywordRecognizer(keywords=("挥手",))
        ctx = SkillContext(
            task_id="T-05",
            task_name="舞",
            params={"bars": 1, "keywords": list(DEFAULT_KEYWORDS)},
            cerebellum=cere,
            observation=None,
            perception=KeywordSpeechPerception(rec),
            tts_engine=tts,
        )
        result = DanceSkill().run(ctx)
        self.assertEqual(result.get("status"), "ok")
        self.assertEqual(result.get("keyword"), "挥手")
        self.assertEqual(result.get("source"), "perception")
        self.assertEqual(cere.dances, 1)
        self.assertNotIn(UNKNOWN_SPEECH, tts.spoken)


class TestDanceEvalTool(unittest.TestCase):
    def test_eval_keywords_and_gate(self):
        tools_dir = Path(__file__).resolve().parents[1] / "tools"
        if str(tools_dir) not in sys.path:
            sys.path.insert(0, str(tools_dir))
        import dance_eval

        rows = dance_eval.eval_keywords()
        gate = dance_eval.eval_skill_gate()
        self.assertTrue(all(row["ok"] for row in rows))
        self.assertTrue(gate["reject_unknown"])
        self.assertTrue(gate["params_fallback"])
        self.assertTrue(gate["hit_whitelist"])
        self.assertTrue(gate["reject_empty"])
        self.assertEqual(dance_eval.main([]), 0)


@unittest.skipUnless(_has_real_vosk(), "vosk 未安装：跳过真引擎用例（核心包零第三方）")
class TestRealVoskOptional(unittest.TestCase):
    def test_real_vosk_import_does_not_crash(self):
        rec = VoskKeywordRecognizer()
        self.assertIsInstance(rec.available(), bool)


if __name__ == "__main__":
    unittest.main()
