"""T-04 踢球评测：无 numpy/cv2 时跳过图像段；几何闭环零依赖可跑。

至少锁：
- 无球失败、不下发踢
- 死区内 0 次迭代
- 仓库 ``config/kick.json`` 纯说明、不覆盖代码默认值
- 默认行为：死区 1 cm、最多 5 轮、不收敛也踢、4–40 cm 门闩
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

from atri.skills.base import SkillContext
from atri.skills.kick import KICK_DEFAULTS, KickSkill
from atri.tuning import load_tuning

SOFTWARE_ROOT = Path(__file__).resolve().parents[1]


def _load_kick_eval():
    path = SOFTWARE_ROOT / "tools" / "kick_eval.py"
    spec = importlib.util.spec_from_file_location("kick_eval_under_test", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class CountingKickBus:
    def __init__(self) -> None:
        self.calls = []
        self.yaw = 0.0

    def set_pose(self, targets):
        for key in ("left_hip_yaw", "right_hip_yaw"):
            if key in targets:
                self.yaw = float(targets[key])
        self.calls.append(("set_pose", dict(targets)))
        return dict(targets)

    def kick(self, foot="right"):
        self.calls.append(("kick", {"foot": foot}))
        return {"action": "kick", "foot": foot}

    def count(self, name: str) -> int:
        return sum(1 for call, _ in self.calls if call == name)


def _ctx(cerebellum, perception=None, observation=None, params=None):
    return SkillContext(
        task_id="T-04",
        task_name="体育运动-踢球",
        params=dict(params or {}),
        cerebellum=cerebellum,
        perception=perception,
        observation=observation,
        tts_engine=None,
    )


class TestKickTuningFile(unittest.TestCase):
    def test_real_kick_config_is_notes_only(self):
        t = load_tuning("kick", KICK_DEFAULTS)
        self.assertEqual(t.values, KICK_DEFAULTS)
        self.assertEqual(t.overridden, ())
        self.assertTrue(t.source_exists)

    def test_defaults_keep_documented_behavior(self):
        self.assertEqual(KICK_DEFAULTS["deadband_cm"], 1.0)
        self.assertEqual(KICK_DEFAULTS["max_iters"], 5)
        self.assertEqual(KICK_DEFAULTS["step_gain"], 0.5)
        self.assertEqual(KICK_DEFAULTS["step_clamp_deg"], 10.0)
        self.assertEqual(KICK_DEFAULTS["min_distance_cm"], 4.0)
        self.assertEqual(KICK_DEFAULTS["max_distance_cm"], 40.0)


class TestKickSkillLocks(unittest.TestCase):
    def test_no_ball_fails_without_kicking(self):
        bus = CountingKickBus()
        ctx = _ctx(bus, observation={"ball": {"found": False}})
        result = KickSkill().run(ctx)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(bus.count("kick"), 0)

    def test_empty_observation_fails_without_kicking(self):
        bus = CountingKickBus()
        ctx = _ctx(bus, observation={})
        result = KickSkill().run(ctx)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(bus.count("kick"), 0)

    def test_deadband_zero_iterations_still_kicks(self):
        bus = CountingKickBus()
        ctx = _ctx(
            bus,
            observation={"ball": {"x_cm": 0.4, "distance_cm": 12.0}},
        )
        result = KickSkill().run(ctx)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["iterations"], 0)
        self.assertTrue(result["converged"])
        self.assertEqual(bus.count("kick"), 1)
        self.assertEqual(bus.count("set_pose"), 0)

    def test_unconverged_still_kicks(self):
        bus = CountingKickBus()
        ctx = _ctx(
            bus,
            observation={"ball": {"x_cm": 5.0, "distance_cm": 12.0}},
        )
        result = KickSkill().run(ctx)
        self.assertEqual(result["status"], "ok")
        self.assertFalse(result["converged"])
        self.assertEqual(result["iterations"], 5)
        self.assertEqual(bus.count("kick"), 1)

    def test_out_of_range_does_not_kick(self):
        bus = CountingKickBus()
        far = KickSkill().run(
            _ctx(bus, observation={"ball": {"x_cm": 0.0, "distance_cm": 80.0}})
        )
        self.assertEqual(far["status"], "failed")
        near = KickSkill().run(
            _ctx(bus, observation={"ball": {"x_cm": 0.0, "distance_cm": 1.0}})
        )
        self.assertEqual(near["status"], "failed")
        self.assertEqual(bus.count("kick"), 0)


class TestKickEvalTool(unittest.TestCase):
    def setUp(self):
        try:
            self.tool = _load_kick_eval()
        except SystemExit as exc:
            self.skipTest(f"评测工具加载失败：{exc}")

    def test_simulate_servo_deadband_zero_iters(self):
        x, iters, ok = self.tool.simulate_servo(0.4, 0.26, 1.0, 5, 0.5, 10.0)
        self.assertEqual(iters, 0)
        self.assertTrue(ok)
        self.assertAlmostEqual(x, 0.4)

    def test_no_ball_perception_does_not_kick(self):
        cere = self.tool.CountingCerebellum()
        ctx = SkillContext(
            task_id="T-04",
            task_name="踢球",
            params={},
            cerebellum=cere,
            perception=self.tool.EmptyBallPerception(),
            tts_engine=None,
        )
        outcome = KickSkill().run(ctx)
        self.assertEqual(outcome["status"], "failed")
        self.assertEqual(cere.kick_calls, 0)

    def test_geometry_loop_inside_deadband(self):
        row = self.tool.run_kick_loop(0.5, 15.0, use_image=False)
        self.assertTrue(row.ok)
        self.assertEqual(row.iterations, 0)
        self.assertEqual(row.kick_calls, 1)
        self.assertEqual(row.mode, "geometry")

    def test_image_scan_skips_without_cv2(self):
        if self.tool.HAS_NUMPY and self.tool.HAS_CV2:
            rows, summary = self.tool.detector_scan()
            self.assertFalse(summary.get("skipped"))
            self.assertTrue(rows)
            empty = [r for r in rows if r.group == "无球"]
            self.assertTrue(empty)
            self.assertFalse(empty[0].found)
            return
        rows, summary = self.tool.detector_scan()
        self.assertTrue(summary.get("skipped"))
        self.assertEqual(rows, [])

    def test_boundary_table_uses_kick_defaults(self):
        bounds = self.tool.boundary_table()
        self.assertEqual(bounds["assumptions"]["deadband_cm"], 1.0)
        self.assertEqual(bounds["assumptions"]["max_iters"], 5)
        self.assertIn("未标定", bounds["assumptions"]["gain_model"])


if __name__ == "__main__":
    unittest.main()
