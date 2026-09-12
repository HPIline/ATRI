"""二维码技能的多段执行测试。

锁四条执行语义：
1. 段按顺序执行，一次不落；
2. **任一段失败就停**，并说清是第几段（不能跳过继续走）；
3. 段与段之间检查中止信号（否则一条 6 段路径会跑成 6 倍超时）；
4. 旧格式单条指令的行为保持兼容。
"""
from __future__ import annotations

import unittest

from atri.skills.base import SkillContext
from atri.skills.qr import QRCodeSkill
from atri.voice import MockTTS


class RecordingCerebellum:
    """记录调用顺序的假小脑；可设定某段抛错、或模拟中止信号。"""

    def __init__(self, fail_on=None, abort_after=None):
        self.calls = []
        self.fail_on = fail_on
        self.abort_after = abort_after
        self._aborted = False

    def _record(self, name, payload):
        self.calls.append((name, payload))
        if self.fail_on is not None and len(self.calls) == self.fail_on:
            raise ValueError("模拟小脑层报错")
        if self.abort_after is not None and len(self.calls) >= self.abort_after:
            self._aborted = True

    def walk(self, steps=6, **kwargs):
        self._record("walk", {"steps": steps, **kwargs})
        return {"frames": steps * 40}

    def set_pose(self, targets):
        self._record("set_pose", targets)
        return targets

    def turn(self, deg, **kwargs):
        self._record("turn", {"deg": deg, **kwargs})
        return {"action": "turn", "deg": deg, "frames": 120}

    def dance(self, bars=2):
        self._record("dance", {"bars": bars})
        return {"action": "dance", "bars": bars}

    def execute_motion(self, instruction, observation=None):
        self._record("execute_motion", {"instruction": instruction})
        return {"action": instruction}

    def aborted(self):
        return self._aborted


def make_ctx(cerebellum, payload, params=None):
    return SkillContext(
        task_id="T-02",
        task_name="二维码循迹",
        params=params or {},
        cerebellum=cerebellum,
        observation={"qr": {"found": True, "payload": payload}},
        tts_engine=MockTTS(),
        gait={},
    )


class TestPathExecution(unittest.TestCase):
    def test_segments_execute_in_order(self):
        cere = RecordingCerebellum()
        payload = {
            "schema": "atri.path.v1",
            "path": [
                {"action": "walk", "steps": 3},
                {"action": "turn", "deg": 90},
                {"action": "walk", "steps": 2},
            ],
        }
        result = QRCodeSkill().run(make_ctx(cere, payload))
        self.assertEqual(result["status"], "ok")
        self.assertEqual([c[0] for c in cere.calls], ["walk", "turn", "walk"])
        self.assertEqual(cere.calls[0][1]["steps"], 3)
        self.assertEqual(cere.calls[2][1]["steps"], 2)
        self.assertEqual(len(result["segments"]), 3)
        self.assertTrue(all(s["status"] == "ok" for s in result["segments"]))

    def test_stops_at_failing_segment_and_reports_index(self):
        """第 2 段失败就不能再跑第 3 段。"""
        cere = RecordingCerebellum(fail_on=2)
        payload = {
            "path": [
                {"action": "walk", "steps": 1},
                {"action": "walk", "steps": 1},
                {"action": "walk", "steps": 1},
            ]
        }
        result = QRCodeSkill().run(make_ctx(cere, payload))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(len(cere.calls), 2)  # 第 3 段没跑
        self.assertIn("第 2/3 段", result["reason"])
        self.assertEqual(result["segments"][1]["status"], "failed")

    def test_abort_between_segments(self):
        cere = RecordingCerebellum(abort_after=1)
        payload = {"path": [{"action": "walk", "steps": 1}, {"action": "walk", "steps": 1}]}
        result = QRCodeSkill().run(make_ctx(cere, payload))
        self.assertEqual(result["status"], "aborted")
        self.assertEqual(len(cere.calls), 1)
        self.assertIn("中止", result["reason"])

    def test_invalid_path_is_rejected_before_any_motion(self):
        """能静态判定的非法路径 → 一步都不走（错误仍精确到 path[i]）。"""
        cere = RecordingCerebellum()
        result = QRCodeSkill().run(make_ctx(cere, {"path": [{"action": "turn", "deg": 999}]}))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(cere.calls, [])
        self.assertIn("路径非法", result["reason"])

    def test_unknown_schema_rejected(self):
        cere = RecordingCerebellum()
        result = QRCodeSkill().run(
            make_ctx(cere, {"schema": "atri.path.v9", "path": [{"action": "walk", "steps": 1}]})
        )
        self.assertEqual(result["status"], "failed")
        self.assertEqual(cere.calls, [])

    def test_result_carries_nominal_trace_marked_uncalibrated(self):
        cere = RecordingCerebellum()
        result = QRCodeSkill().run(
            make_ctx(cere, {"path": [{"action": "walk", "steps": 5}]})
        )
        self.assertIn("trace", result)
        self.assertEqual(result["trace"]["status"], "nominal-uncalibrated")
        self.assertFalse(result["trace"]["calibrated"])

    def test_gait_params_are_passed_through(self):
        cere = RecordingCerebellum()
        ctx = make_ctx(cere, {"path": [{"action": "walk", "steps": 2}]})
        ctx.gait = {"step_length_cm": 1.5}
        QRCodeSkill().run(ctx)
        self.assertEqual(cere.calls[0][1]["step_length_cm"], 1.5)


class TestLegacyBehaviour(unittest.TestCase):
    def test_legacy_single_action_still_works(self):
        cere = RecordingCerebellum()
        result = QRCodeSkill().run(make_ctx(cere, {"action": "walk", "steps": 2}))
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["action"], "walk")  # 单段时仍报具体动作
        self.assertIn("detail", result)  # 兼容字段仍在
        self.assertEqual(len(cere.calls), 1)

    def test_turn_uses_stepping_turn_not_static_hip_pose(self):
        """转向必须走 cerebellum.turn（踩步转体）。

        实测对比：旧的 set_pose(hip_yaw=deg/3) 只发 2 条**静态**指令、没有任何轨迹，
        机器人只是僵在一个拧住的角度上；turn() 会发出整段步态轨迹。
        """
        cere = RecordingCerebellum()
        result = QRCodeSkill().run(make_ctx(cere, {"action": "turn", "deg": 90}))
        self.assertEqual(cere.calls[0][0], "turn")
        self.assertEqual(cere.calls[0][1]["deg"], 90.0)
        self.assertGreaterEqual(result["detail"]["frames"], 2)

    def test_default_payload_used_when_no_qr_channel(self):
        """Mock 场景（无二维码通道）才允许用任务卡兜底指令。"""
        cere = RecordingCerebellum()
        ctx = SkillContext(
            task_id="T-02",
            task_name="二维码循迹",
            params={"default_payload": {"action": "walk", "steps": 3}},
            cerebellum=cere,
            observation=None,
            tts_engine=MockTTS(),
            gait={},
        )
        result = QRCodeSkill().run(ctx)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(cere.calls[0][1]["steps"], 3)

    def test_missing_payload_with_channel_fails(self):
        cere = RecordingCerebellum()
        ctx = make_ctx(cere, {"found": True})
        result = QRCodeSkill().run(ctx)
        self.assertEqual(result["status"], "failed")
        self.assertIn("payload", result["reason"])


if __name__ == "__main__":
    unittest.main()
