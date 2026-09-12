"""人脸技能行为测试。

分两块，对应技能里的两条通路：

**真识别通路**（本仓库新增）：检测 → 特征 → 库比对 → 播报 / 拒识。
锁两件事：① 认不出时**绝不编造姓名**；② 结果必须标明 ``source``。

**退化通路**（原有实现，未改动）：走感知接口，行为与上游一致，
其中 ``expect_names[0]`` 兜底属于**待团队确认的口径**，这里只如实记录现状，不当作期望行为断言。
差异见 ``design/handoff/T-01-口径差异清单.md``。
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace

from atri.skills.base import SkillContext
from atri.skills.face import DEFAULT_EXPECT_NAMES, FaceSkill
from atri.voice import MockTTS


class FakeBox:
    def __init__(self, bbox=(0, 0, 100, 100)):
        self.bbox = bbox

    def to_dict(self):
        return {"bbox": list(self.bbox), "score": 0.99, "landmarks": []}


class FakeRecognizer:
    """假识别器：直接返回预设结果，用来测技能层的行为分支。"""

    def __init__(self, name=None, found=True, similarity=0.7, margin=0.3):
        self._name = name
        self._found = found
        self._similarity = similarity
        self._margin = margin

    def recognize(self, frame):
        faces = [FakeBox()] if self._found else []
        best = None
        if self._name:
            best = SimpleNamespace(name=self._name, similarity=self._similarity, margin=self._margin)
        return SimpleNamespace(
            faces=faces,
            found=self._found,
            recognized_name=self._name,
            best=best,
        )


class FakeFrameSource:
    def __init__(self, frame="FRAME"):
        self._frame = frame
        self.calls = 0

    def grab(self):
        self.calls += 1
        return self._frame


def make_ctx(**kwargs):
    params = kwargs.pop("params", {"expect_names": ["测试员A", "测试员B"]})
    return SkillContext(
        task_id="T-01",
        task_name="人脸识别",
        params=params,
        cerebellum=None,
        **kwargs,
    )


class TestFaceSkillRecognitionPath(unittest.TestCase):
    """真识别通路。"""

    def test_recognized_face_speaks_name(self):
        tts = MockTTS()
        ctx = make_ctx(
            face_recognizer=FakeRecognizer(name="测试员A", similarity=0.71, margin=0.3),
            frame_source=FakeFrameSource(),
            tts_engine=tts,
        )
        result = FaceSkill().run(ctx)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["source"], "recognition")
        self.assertEqual(result["name"], "测试员A")
        self.assertEqual(result["similarity"], 0.71)
        self.assertEqual(tts.spoken[0], "你好，测试员A")

    def test_confidence_is_measured_similarity_not_a_made_up_number(self):
        ctx = make_ctx(
            face_recognizer=FakeRecognizer(name="测试员A", similarity=0.6342),
            frame_source=FakeFrameSource(),
        )
        result = FaceSkill().run(ctx)
        self.assertEqual(result["confidence"], 0.6342)

    def test_unknown_face_is_rejected_not_guessed(self):
        """看到脸但不确定是谁 → 拒识。绝不能拿 expect_names 顶上。"""
        tts = MockTTS()
        ctx = make_ctx(
            face_recognizer=FakeRecognizer(name=None, found=True),
            frame_source=FakeFrameSource(),
            tts_engine=tts,
        )
        result = FaceSkill().run(ctx)
        self.assertEqual(result["status"], "rejected")
        self.assertIsNone(result["name"])
        self.assertIn("不认识", tts.spoken[0])
        self.assertNotIn("测试员A", tts.spoken[0])

    def test_no_face_detected(self):
        tts = MockTTS()
        ctx = make_ctx(
            face_recognizer=FakeRecognizer(name=None, found=False),
            frame_source=FakeFrameSource(),
            tts_engine=tts,
        )
        result = FaceSkill().run(ctx)
        self.assertEqual(result["status"], "no_face")
        self.assertIsNone(result["name"])
        self.assertEqual(result["face_count"], 0)

    def test_recognized_but_not_in_expected_list_fails(self):
        ctx = make_ctx(
            face_recognizer=FakeRecognizer(name="路人甲"),
            frame_source=FakeFrameSource(),
        )
        result = FaceSkill().run(ctx)
        self.assertNotEqual(result["status"], "ok")
        self.assertIn("不在预期名单", result["reason"])

    def test_empty_frame_fails_loudly(self):
        ctx = make_ctx(
            face_recognizer=FakeRecognizer(name="测试员A"),
            frame_source=FakeFrameSource(frame=None),
        )
        result = FaceSkill().run(ctx)
        self.assertEqual(result["status"], "failed")
        self.assertIn("空帧", result["reason"])

    def test_frame_source_is_actually_used(self):
        src = FakeFrameSource()
        ctx = make_ctx(face_recognizer=FakeRecognizer(name="测试员A"), frame_source=src)
        FaceSkill().run(ctx)
        self.assertEqual(src.calls, 1)

    def test_real_path_requires_both_recognizer_and_source(self):
        """只给识别器不给取帧来源 → 不能装作在真识别（会退回退化通路）。"""
        ctx = make_ctx(face_recognizer=FakeRecognizer(name="测试员A"))
        result = FaceSkill().run(ctx)
        self.assertNotEqual(result["source"], "recognition")


class TestFaceSkillLegacyPath(unittest.TestCase):
    """退化通路（原有实现）。这些断言锁定的是**当前行为**，不是团队已定口径。"""

    def test_observation_name_is_used(self):
        tts = MockTTS()
        # 不配 expect_names：配了的话名单外的姓名会被判失败（上游语义，见口径差异清单）
        ctx = make_ctx(observation={"face": {"name": "王五"}}, tts_engine=tts, params={})
        result = FaceSkill().run(ctx)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["name"], "王五")
        self.assertEqual(tts.spoken[0], "你好，王五")

    def test_name_outside_expect_list_fails(self):
        """上游语义：配了 expect_names 时，名单外的姓名判失败（赛题"识别指定人脸"）。"""
        ctx = make_ctx(observation={"face": {"name": "王五"}})
        result = FaceSkill().run(ctx)
        self.assertEqual(result["status"], "failed")
        self.assertIn("不在预期名单", result["reason"])

    def test_mock_perception_name_is_used(self):
        from atri.perception import MockPerception

        tts = MockTTS()
        ctx = make_ctx(perception=MockPerception(face={"name": "感知A"}), tts_engine=tts, params={})
        result = FaceSkill().run(ctx)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["name"], "感知A")

    def test_found_false_fails(self):
        ctx = make_ctx(observation={"face": {"found": False}})
        result = FaceSkill().run(ctx)
        self.assertEqual(result["status"], "failed")

    def test_current_behaviour_when_no_channel_at_all(self):
        """现状记录：没有任何感知通道时，退化通路会取 ``expect_names[0]`` 当作姓名播报。

        ⚠ 这是**待团队确认**的口径（真识别通路不会这样做：认不出就拒识）。
        本用例只锁定现状，等口径定稿后按结论改写。
        """
        tts = MockTTS()
        ctx = make_ctx(tts_engine=tts, params={"expect_names": ["测试员A"]})
        result = FaceSkill().run(ctx)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["source"], "params")
        self.assertEqual(result["name"], "测试员A")
        self.assertEqual(result["name"], DEFAULT_EXPECT_NAMES[0])


if __name__ == "__main__":
    unittest.main()
