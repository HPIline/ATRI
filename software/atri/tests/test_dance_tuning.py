"""T-05 舞蹈技能的**可调参数层**与"诚实记账"回归测试。

分三块：
1. ``TestDanceTuning``：``config/dance.json`` 的三层优先级与非法值回落——"实物到手只改
   JSON 就能标定"这条承诺的守门测试。
2. ``TestDanceSpeechGate``：白名单门闩与"通道接入却听不清必须失败"。
3. ``TestAsrAccounting``：``asr_engine`` / ``asr_real`` **绝不能**把 Mock 说成识别。

（语音引擎本身的测试在 ``tests/test_voice_offline.py``；真引擎解码证据由
``tools/asr_decode_eval.py`` 跑，不在单元测试里——它要外部解释器和 65 MB 模型。）
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from atri.perception import PerceptionResult
from atri.skills.base import SkillContext
from atri.skills.dance import DANCE_DEFAULTS, DanceSkill
from atri.tuning import load_tuning

SOFTWARE_ROOT = Path(__file__).resolve().parents[1]


class SpyCerebellum:
    """记录下发动作的假小脑。"""

    def __init__(self) -> None:
        self.calls = []

    def dance(self, bars: int = 2) -> dict:
        self.calls.append(("dance", bars))
        return {"action": "dance", "bars": bars}

    def home(self):
        self.calls.append(("home", None))
        return {}

    def count(self, name: str) -> int:
        return sum(1 for call, _ in self.calls if call == name)


class SpyTTS:
    def __init__(self) -> None:
        self.spoken = []

    def speak(self, text: str) -> None:
        self.spoken.append(text)


def _ctx(observation=None, params=None, perception=None, tts=None):
    return SkillContext(
        task_id="T-05",
        task_name="娱乐休闲-舞蹈",
        params=dict(params or {}),
        cerebellum=SpyCerebellum(),
        observation=observation,
        perception=perception,
        tts_engine=tts or SpyTTS(),
    )


def _speech(**data):
    return {"speech": {"found": True, **data}}


class TestDanceTuning(unittest.TestCase):
    """三层优先级 + 非法值回落，全部用**可观测行为**断言。"""

    def _tmp(self):
        return tempfile.TemporaryDirectory()

    def test_shipped_config_is_notes_only(self):
        """随代码发布的 config/dance.json 必须是纯说明：不许偷偷改设计值。"""
        t = load_tuning("dance", DANCE_DEFAULTS)
        self.assertTrue(t.source_exists)
        self.assertEqual(t.overridden, ())
        self.assertEqual(t.warnings, ())

    def test_file_overrides_unknown_speech(self):
        with self._tmp() as tmp:
            Path(tmp, "dance.json").write_text(
                json.dumps({"unknown_speech": "再说一遍好吗"}), encoding="utf-8"
            )
            with mock.patch.dict(os.environ, {"ATRI_TUNING_DIR": tmp}):
                tts = SpyTTS()
                result = DanceSkill().run(_ctx(_speech(keyword="起飞"), tts=tts))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(tts.spoken, ["再说一遍好吗"])
        self.assertEqual(result["tuning_source"], "dance.json")

    def test_task_card_beats_file(self):
        with self._tmp() as tmp:
            Path(tmp, "dance.json").write_text(
                json.dumps({"unknown_speech": "文件里的"}), encoding="utf-8"
            )
            with mock.patch.dict(os.environ, {"ATRI_TUNING_DIR": tmp}):
                tts = SpyTTS()
                result = DanceSkill().run(
                    _ctx(_speech(keyword="起飞"), params={"unknown_speech": "卡里的"}, tts=tts)
                )
        self.assertEqual(tts.spoken, ["卡里的"])
        # 文件里的键被任务卡盖住 ⇒ 不许把它算作"来自文件"
        self.assertEqual(result["tuning_source"], "code-defaults")
        self.assertEqual(result["tuning_overridden"], [])

    def test_file_tightens_whitelist(self):
        with self._tmp() as tmp:
            Path(tmp, "dance.json").write_text(
                json.dumps({"keywords": "跳舞"}), encoding="utf-8"
            )
            with mock.patch.dict(os.environ, {"ATRI_TUNING_DIR": tmp}):
                result = DanceSkill().run(_ctx(_speech(keyword="跳个舞")))
        self.assertEqual(result["status"], "failed")
        self.assertIn("白名单", result["reason"])

    def test_file_adds_variant(self):
        with self._tmp() as tmp:
            Path(tmp, "dance.json").write_text(
                json.dumps({"keywords": "跳舞、跳个舞、来段舞蹈"}), encoding="utf-8"
            )
            with mock.patch.dict(os.environ, {"ATRI_TUNING_DIR": tmp}):
                result = DanceSkill().run(_ctx(_speech(keyword="来段舞蹈")))
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["keyword"], "来段舞蹈")

    def test_bars_max_can_only_tighten(self):
        """配置只能收紧小节上限：放宽请求必须被硬上限 MAX_BARS 截住。"""
        with self._tmp() as tmp:
            Path(tmp, "dance.json").write_text(json.dumps({"bars_max": 2}), encoding="utf-8")
            with mock.patch.dict(os.environ, {"ATRI_TUNING_DIR": tmp}):
                over = DanceSkill().run(_ctx(_speech(keyword="跳舞"), params={"bars": 5}))
                ok = DanceSkill().run(_ctx(_speech(keyword="跳舞"), params={"bars": 2}))
        self.assertEqual(over["status"], "failed")
        self.assertIn("bars", over["reason"])
        self.assertEqual(ok["status"], "ok")
        self.assertEqual(ok["bars"], 2)

    def test_invalid_values_fall_back_and_warn_loudly(self):
        with self._tmp() as tmp:
            Path(tmp, "dance.json").write_text(
                json.dumps({"bars": "很多", "audio_enabled": "yes", "没这个键": 1}),
                encoding="utf-8",
            )
            with mock.patch.dict(os.environ, {"ATRI_TUNING_DIR": tmp}):
                captured = io.StringIO()
                with contextlib.redirect_stdout(captured):
                    result = DanceSkill().run(_ctx(_speech(keyword="跳舞")))
        self.assertEqual(result["status"], "ok")
        out = captured.getvalue()
        self.assertIn("未知键", out)          # 拼错的键要看得见
        self.assertIn("[tuning:dance]", out)  # 非法值也要看得见（走同一套告警出口）
        self.assertTrue(result["tuning_warnings"])
        self.assertEqual(result["tuning_source"], "code-defaults")

    def test_broken_json_does_not_raise(self):
        with self._tmp() as tmp:
            Path(tmp, "dance.json").write_text("{不是 JSON", encoding="utf-8")
            with mock.patch.dict(os.environ, {"ATRI_TUNING_DIR": tmp}):
                result = DanceSkill().run(_ctx(_speech(keyword="跳舞")))
        self.assertEqual(result["status"], "ok")
        self.assertTrue(any("读取失败" in w for w in result["tuning_warnings"]))

    def test_audio_can_be_disabled(self):
        with self._tmp() as tmp:
            Path(tmp, "dance.json").write_text(json.dumps({"audio_enabled": False}), encoding="utf-8")
            with mock.patch.dict(os.environ, {"ATRI_TUNING_DIR": tmp}):
                result = DanceSkill().run(
                    _ctx(_speech(keyword="跳舞"), params={"audio": "/tmp/不存在的伴奏.wav"})
                )
        self.assertEqual(result["audio"], "disabled")


class TestDanceSpeechGate(unittest.TestCase):
    """门闩：白名单外不跳、听不清必须失败并播提示语。"""

    def test_whitelist_hit_dances(self):
        cere = SpyCerebellum()
        ctx = _ctx(_speech(keyword="跳舞"))
        ctx.cerebellum = cere
        result = DanceSkill().run(ctx)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(cere.count("dance"), 1)

    def test_out_of_whitelist_does_not_dance(self):
        cere = SpyCerebellum()
        tts = SpyTTS()
        ctx = _ctx(_speech(keyword="起飞"), tts=tts)
        ctx.cerebellum = cere
        result = DanceSkill().run(ctx)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(cere.count("dance"), 0)
        self.assertEqual(tts.spoken, ["我没听清"])

    def test_empty_keyword_with_channel_fails(self):
        """通道接入了却没听清 → 失败 + 提示语（不能默认跳一段）。"""
        for keyword in ("", None):
            with self.subTest(keyword=keyword):
                cere = SpyCerebellum()
                tts = SpyTTS()
                ctx = _ctx({"speech": {"found": True, "keyword": keyword}}, tts=tts)
                ctx.cerebellum = cere
                result = DanceSkill().run(ctx)
                self.assertEqual(result["status"], "failed")
                self.assertEqual(cere.count("dance"), 0)
                self.assertEqual(tts.spoken, ["我没听清"])

    def test_perception_error_fails(self):
        class Broken:
            def detect_speech(self, audio=None):
                raise AssertionError("不该走到这里")  # pragma: no cover

            name = "broken"

        ctx = _ctx({"speech": {"found": False, "error": "麦克风掉线"}}, perception=Broken())
        result = DanceSkill().run(ctx)
        self.assertEqual(result["status"], "failed")
        self.assertIn("麦克风掉线", result["reason"])

    def test_no_channel_falls_back_to_task_card(self):
        """没有语音通道（纯演示）时走任务卡兜底，且**必须**在结果里标明不是识别。"""
        result = DanceSkill().run(_ctx({}, params={"keyword": "跳舞"}))
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["source"], "params")
        self.assertEqual(result["asr_engine"], "none")
        self.assertFalse(result["asr_real"])


class TestAsrAccounting(unittest.TestCase):
    """``asr_engine`` / ``asr_real``：Mock 一律不许标成真识别。"""

    def test_mock_observation_is_not_real(self):
        result = DanceSkill().run(_ctx(_speech(keyword="跳舞")))
        self.assertEqual(result["asr_engine"], "mock")
        self.assertFalse(result["asr_real"])

    def test_self_declared_engine_is_honoured(self):
        result = DanceSkill().run(
            _ctx(_speech(keyword="跳舞", asr_engine="vosk", asr_real=True))
        )
        self.assertEqual(result["asr_engine"], "vosk")
        self.assertTrue(result["asr_real"])

    def test_self_declared_false_is_honoured(self):
        """观测自己说"不是真识别"，就按不是记账（不许替它拔高）。"""
        result = DanceSkill().run(
            _ctx(_speech(keyword="跳舞", asr_engine="vosk", asr_real=False))
        )
        self.assertFalse(result["asr_real"])

    def test_params_fallback_is_never_real(self):
        result = DanceSkill().run(_ctx({}, params={"keyword": "跳舞"}))
        self.assertEqual(result["asr_engine"], "none")
        self.assertFalse(result["asr_real"])

    def test_failure_keeps_tuning_fields(self):
        """失败路径也要带参数出处与告警，否则现场"改了没生效"查不出来。"""
        result = DanceSkill().run(_ctx(_speech(keyword="起飞")))
        self.assertEqual(result["status"], "failed")
        self.assertIn("tuning_source", result)
        self.assertIn("tuning_warnings", result)


class TestKeywordMatching(unittest.TestCase):
    """白名单判定：连续文本要能匹配，最长词优先（自由解码会在字间吐空格）。"""

    def test_spaced_transcript_matches(self):
        from atri.voice.vosk import match_keyword

        keywords = ("跳舞", "跳个舞", "来段舞蹈")
        self.assertEqual(match_keyword("跳 个 舞", keywords), "跳个舞")
        self.assertEqual(match_keyword("来 段 舞蹈", keywords), "来段舞蹈")
        self.assertEqual(match_keyword("跳舞", keywords), "跳舞")

    def test_out_of_whitelist_is_empty(self):
        from atri.voice.vosk import match_keyword

        self.assertEqual(match_keyword("起飞", ("跳舞",)), "")

    def test_longest_hit_wins(self):
        from atri.voice.vosk import match_keyword

        self.assertEqual(match_keyword("来段舞蹈", ("跳舞", "来段舞蹈")), "来段舞蹈")


if __name__ == "__main__":
    unittest.main()
