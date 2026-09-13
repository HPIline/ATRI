"""T-04 踢球：控制参数外部化（tuning）与闭环不回归的专项测试。

这一组测试盯的是**改造后不许变坏的那几条**：

1. 优先级：任务卡 params > ``config/kick.json`` > 代码默认值（``KICK_DEFAULTS``）；
2. 配置写错（类型不符、非有限数、负值、JSON 坏、顶层不是对象）→ 回落默认值 + 告警，**不抛异常**；
3. 球距判据的边界（含端点、可覆盖）与"判失败绝不下发动作"；
4. ``iterations`` / ``converged`` 语义不回归（收敛时在预算内进死区；静态观测在上限处停下仍尽力踢）；
5. **缺测距绝不当成 0 米踢出去**。

为什么用 ``ATRI_TUNING_DIR`` 指到临时目录：tuning 层约定"每次调用重新读文件"，
所以改环境变量就能在测试里造各种 `config/kick.json`，不动仓库里那份真文件。

最后还有一组 ``TestKickEvalTool``：`tools/kick_eval.py` 本身也是交付物，
解析出来的边界表是报告里的数字来源，它坏了得有人叫。
"""
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from atri.cerebellum import Cerebellum, MockServoBus
from atri.perception import ServoMockPerception
from atri.skills.base import SkillContext
from atri.skills.kick import KICK_DEFAULTS, KickSkill
from atri.tuning import load_tuning, tuning_path
from atri.voice import MockTTS

SOFTWARE_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = SOFTWARE_ROOT / "tools"

# 一维几何 Mock 的默认相机增益（假设值）。测试里显式写出来，避免"默认值改了测试跟着变"。
SERVO_GAIN_CM_PER_DEG = 1.5


class SpyCerebellum(Cerebellum):
    """记录底层动作调用次数：判失败时一次都不许调用（与 test_brain 同一套做法）。"""

    def __init__(self, bus=None):
        super().__init__(servo_bus=bus or MockServoBus(), sleeper=lambda dt: None)
        self.calls = {}

    def _tick(self, name):
        self.calls[name] = self.calls.get(name, 0) + 1

    def kick(self, *args, **kwargs):
        self._tick("kick")
        return super().kick(*args, **kwargs)

    def set_pose(self, *args, **kwargs):
        self._tick("set_pose")
        return super().set_pose(*args, **kwargs)


def _ctx(params=None, observation=None, perception=None, cerebellum=None):
    return SkillContext(
        task_id="T-04",
        task_name="体育运动-踢球",
        params=dict(params or {}),
        cerebellum=cerebellum or SpyCerebellum(),
        observation=observation,
        perception=perception,
        tts_engine=MockTTS(),
        gait={},
    )


def _run(params=None, observation=None, perception=None, cerebellum=None):
    """跑一次踢球技能，返回 (结果, 小脑间谍)。"""
    cere = cerebellum or SpyCerebellum()
    ctx = _ctx(params=params, observation=observation, perception=perception, cerebellum=cere)
    return KickSkill().run(ctx), cere


def _static_ball(x_cm=5.0, distance_cm=12.0):
    """静态观测：每轮都读到同一个横向偏差（不进死区就必然撞迭代上限）。"""
    return {"ball": {"x_cm": x_cm, "distance_cm": distance_cm}}


def _servo_perception(bus, ball_x_true=3.0):
    return ServoMockPerception(bus=bus, ball_x_true=ball_x_true, gain_cm_per_deg=SERVO_GAIN_CM_PER_DEG)


class TuningDirMixin:
    """把 ATRI_TUNING_DIR 指到临时目录，并按需写入一份 kick.json。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tuning_dir = self._tmp.name
        env = mock.patch.dict(os.environ, {"ATRI_TUNING_DIR": self.tuning_dir})
        env.start()
        self.addCleanup(env.stop)

    def write_kick_json(self, text):
        tuning_path("kick").write_text(text, encoding="utf-8")

    def write_kick_values(self, values):
        self.write_kick_json(json.dumps(values, ensure_ascii=False))


class TestKickTuningPriority(TuningDirMixin, unittest.TestCase):
    """优先级：任务卡 params > config/kick.json > 代码默认值。"""

    def test_code_defaults_when_no_file(self):
        """文件不存在 = 还没标定：用代码默认值，并且如实标 code-defaults。"""
        result, _ = _run(observation=_static_ball())
        self.assertEqual(result["tuning_source"], "code-defaults")
        self.assertEqual(result["tuning_source"], "code-defaults")

    def test_notes_only_file_is_not_a_calibration(self):
        """只有 `_` 说明键的文件 = 没覆盖任何键：不许被当成\"已标定\"。"""
        self.write_kick_values({"_note": "只写说明，不写值"})
        result, _ = _run(observation=_static_ball())
        self.assertEqual(result["tuning_source"], "code-defaults")
        self.assertEqual(result["tuning_source"], "code-defaults")
        self.assertEqual(result["tuning_overridden"], [])

    def test_file_overrides_code_default(self):
        """kick.json 里的值真的生效，并如实标出来源文件名。"""
        self.write_kick_values({"deadband_cm": 6.0})
        result, _ = _run(observation=_static_ball(x_cm=5.0))
        # 死区放到 6 cm 后，5 cm 的偏差已在死区内：0 轮迭代即收敛
        self.assertTrue(result["converged"])
        self.assertEqual(result["iterations"], 0)
        self.assertEqual(result["tuning_source"], "kick.json")

    def test_task_card_beats_file(self):
        """任务卡 params 优先级最高：现场改任务卡能盖过已标定的值。"""
        self.write_kick_values({"deadband_cm": 6.0})
        result, _ = _run(params={"deadband_cm": 1.0}, observation=_static_ball(x_cm=5.0))
        self.assertFalse(result["converged"])
        self.assertEqual(result["iterations"], 5)
        self.assertEqual(result["tuning_source"], "code-defaults")  # 文件没被采纳

    def test_file_overrides_max_iters(self):
        self.write_kick_values({"max_iters": 2})
        result, _ = _run(observation=_static_ball(x_cm=5.0))
        self.assertEqual(result["iterations"], 2)
        self.assertFalse(result["converged"])

    def test_task_card_overrides_max_iters_beats_file(self):
        self.write_kick_values({"max_iters": 2})
        result, _ = _run(params={"max_iters": 4}, observation=_static_ball(x_cm=5.0))
        self.assertEqual(result["iterations"], 4)

    def test_step_gain_and_clamp_come_from_file(self):
        """步长增益/钳位也走同一套优先级：只转 2° 就够把 3 cm 偏差的结论改掉。"""
        bus = MockServoBus()
        self.write_kick_values({"step_gain": 10.0, "step_clamp_deg": 2.0})
        perception = _servo_perception(bus, ball_x_true=3.0)
        result, _ = _run(perception=perception, cerebellum=SpyCerebellum(bus=bus))
        self.assertEqual(result["iterations"], 1)
        # 第一轮钳到 2°：3 cm - 2° × 1.5 cm/° = 0 cm，直接进死区
        self.assertTrue(result["converged"])
        self.assertEqual(result["ball_x_cm"], 0.0)

    def test_task_card_step_params_apply(self):
        """任务卡里的 step 参数同样生效（改造前这两个键根本不被技能读取）。"""
        bus = MockServoBus()
        perception = _servo_perception(bus, ball_x_true=3.0)
        result, _ = _run(
            params={"step_gain": 10.0, "step_clamp_deg": 1.0},
            perception=perception,
            cerebellum=SpyCerebellum(bus=bus),
        )
        self.assertEqual(result["iterations"], 2)  # 1° → 1.5 cm，再 1° → 0 cm
        self.assertTrue(result["converged"])


class TestKickTuningInvalidValues(TuningDirMixin, unittest.TestCase):
    """配置写错只告警不抛异常，并回落到默认值。"""

    def test_bad_values_fall_back_without_raising(self):
        self.write_kick_values({
            "deadband_cm": -1.0,        # 该正不正
            "max_iters": "abc",         # 类型不符
            "step_gain": 0.0,           # 必须是正数
            "step_clamp_deg": None,     # 不是数值
            "unknown_key": 3,           # 不在可调项里
        })
        result, cere = _run(observation=_static_ball(x_cm=5.0))
        # 全部回落到代码默认值：死区 1 cm、上限 5 轮
        self.assertEqual(result["iterations"], 5)
        self.assertFalse(result["converged"])
        self.assertEqual(result["tuning_source"], "code-defaults")
        self.assertEqual(cere.calls.get("kick"), 1)
        self.assertTrue(result["tuning_warnings"], "写错的键必须带回告警，不许静默")

    def test_broken_json_falls_back_without_raising(self):
        self.write_kick_json('{"deadband_cm": 3.0,}')  # 尾逗号：坏 JSON
        result, _ = _run(observation=_static_ball(x_cm=5.0))
        self.assertEqual(result["iterations"], 5)
        self.assertEqual(result["tuning_source"], "code-defaults")

    def test_non_object_top_level_falls_back(self):
        self.write_kick_json("[1, 2, 3]")
        result, _ = _run(observation=_static_ball(x_cm=5.0))
        self.assertEqual(result["iterations"], 5)
        self.assertTrue(result["tuning_warnings"])

    def test_non_finite_numbers_are_rejected(self):
        """NaN/Inf 绝不进闭环：写进配置也只算无效值。"""
        self.write_kick_values({"deadband_cm": float("nan"), "max_iters": float("inf")})
        result, _ = _run(observation=_static_ball(x_cm=5.0))
        self.assertEqual(result["iterations"], 5)
        self.assertFalse(result["converged"])

    def test_bad_task_card_params_fall_back_without_raising(self):
        """任务卡里的笔误同样不许把整张卡炸掉（既有语义，改造后必须保持）。"""
        result, cere = _run(
            params={"deadband_cm": "abc", "max_iters": 0, "step_clamp_deg": float("nan"),
                    "step_gain": -2.0},
            observation=_static_ball(x_cm=5.0),
        )
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["iterations"], 5)
        self.assertEqual(cere.calls.get("kick"), 1)

    def test_task_card_max_iters_out_of_range_falls_back(self):
        result, _ = _run(params={"max_iters": 999}, observation=_static_ball(x_cm=5.0))
        self.assertEqual(result["iterations"], KICK_DEFAULTS["max_iters"])

    def test_shipped_kick_json_is_clean(self):
        """仓库里那份 config/kick.json 不许有拼错的键（它越干净，回填时越不容易写错）。"""
        real_dir = os.environ.pop("ATRI_TUNING_DIR", None)
        try:
            path = tuning_path("kick")
            self.assertTrue(path.exists(), f"缺少 {path}")
            data = json.loads(path.read_text(encoding="utf-8"))
            unknown = [k for k in data if not k.startswith("_") and k not in KICK_DEFAULTS]
            self.assertEqual(unknown, [], f"kick.json 里有不在可调项里的键: {unknown}")
            self.assertEqual(load_tuning("kick", KICK_DEFAULTS).warnings, ())
        finally:
            if real_dir is not None:
                os.environ["ATRI_TUNING_DIR"] = real_dir

    def test_known_tunable_keys_are_stable(self):
        """可调项就是这六个：以后要加，得先改这条测试（故意让它挡一下）。"""
        self.assertEqual(
            sorted(KICK_DEFAULTS),
            ["deadband_cm", "max_distance_cm", "max_iters", "min_distance_cm",
             "step_clamp_deg", "step_gain"],
        )


class TestKickDistanceBounds(TuningDirMixin, unittest.TestCase):
    """球距判据：边界、可覆盖、判失败不下发动作。"""

    def test_default_bounds_include_endpoints(self):
        for distance, expect_ok in ((3.9, False), (4.0, True), (40.0, True), (40.1, False)):
            with self.subTest(distance=distance):
                result, cere = _run(observation=_static_ball(distance_cm=distance))
                self.assertEqual(result["status"], "ok" if expect_ok else "failed", result)
                self.assertEqual(cere.calls.get("kick", 0), 1 if expect_ok else 0)

    def test_bounds_come_from_file(self):
        """球距上下限也外部化了：标定出真实够得着的范围后写进 kick.json 即可。"""
        self.write_kick_values({"min_distance_cm": 6.0, "max_distance_cm": 20.0})
        self.assertEqual(_run(observation=_static_ball(distance_cm=5.0))[0]["status"], "failed")
        self.assertEqual(_run(observation=_static_ball(distance_cm=6.0))[0]["status"], "ok")
        self.assertEqual(_run(observation=_static_ball(distance_cm=20.0))[0]["status"], "ok")
        self.assertEqual(_run(observation=_static_ball(distance_cm=21.0))[0]["status"], "failed")

    def test_bounds_from_task_card_beat_file(self):
        self.write_kick_values({"max_distance_cm": 20.0})
        result, _ = _run(params={"max_distance_cm": 30.0}, observation=_static_ball(distance_cm=25.0))
        self.assertEqual(result["status"], "ok")

    def test_distance_failure_does_not_move_the_robot(self):
        """球距越界时一次 set_pose 都不许发（不许先转头再判不可能）。"""
        for distance in (3.0, 41.0):
            with self.subTest(distance=distance):
                result, cere = _run(observation=_static_ball(distance_cm=distance))
                self.assertEqual(result["status"], "failed")
                self.assertEqual(cere.calls.get("set_pose", 0), 0)
                self.assertEqual(cere.calls.get("kick", 0), 0)

    def test_missing_perception_channel_fails(self):
        result, cere = _run(observation={"ball": {"found": False}})
        self.assertEqual(result["status"], "failed")
        self.assertEqual(cere.calls.get("kick", 0), 0)


class TestKickMissingDistance(unittest.TestCase):
    """缺测距绝不当作 0 米踢出去（这条是硬要求）。"""

    def _assert_failed_without_action(self, result, cere):
        self.assertEqual(result["status"], "failed", result)
        self.assertIn("缺测距", result["reason"])
        self.assertEqual(cere.calls.get("kick", 0), 0)
        self.assertEqual(cere.calls.get("set_pose", 0), 0)

    def test_distance_none_fails(self):
        result, cere = _run(observation={"ball": {"x_cm": 1.0, "distance_cm": None}})
        self._assert_failed_without_action(result, cere)

    def test_distance_key_absent_fails(self):
        result, cere = _run(observation={"ball": {"x_cm": 1.0}})
        self._assert_failed_without_action(result, cere)

    def test_zero_and_negative_distance_fail(self):
        for distance in (0, 0.0, -5.0):
            with self.subTest(distance=distance):
                result, cere = _run(observation={"ball": {"x_cm": 1.0, "distance_cm": distance}})
                self._assert_failed_without_action(result, cere)

    def test_non_numeric_and_bool_distance_fail(self):
        for distance in ("十五", "", True, [15.0]):
            with self.subTest(distance=distance):
                result, cere = _run(observation={"ball": {"x_cm": 1.0, "distance_cm": distance}})
                self._assert_failed_without_action(result, cere)

    def test_numeric_string_distance_is_accepted(self):
        """数字字符串按既有口径是合法值（as_finite_float 会转），这里只是把口径钉住。"""
        result, cere = _run(observation={"ball": {"x_cm": 1.0, "distance_cm": "15"}})
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["distance_cm"], 15.0)
        self.assertEqual(cere.calls.get("kick"), 1)

    def test_task_card_distance_fallback_still_works(self):
        """任务卡给了测距时仍可按任务卡兜底（既有行为：只有\"观测里没有这个键\"才走它）。"""
        result, cere = _run(params={"distance_cm": 12.0}, observation={"ball": {"x_cm": 1.0}})
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["distance_cm"], 12.0)
        self.assertEqual(cere.calls.get("kick"), 1)

    def test_task_card_fallback_not_used_when_observation_says_none(self):
        """观测**明确**给出 None 时不许被任务卡兜底救回来——那是在替机器人猜。"""
        result, cere = _run(
            params={"distance_cm": 12.0}, observation={"ball": {"x_cm": 1.0, "distance_cm": None}}
        )
        self._assert_failed_without_action(result, cere)

    def test_invalid_lateral_offset_fails(self):
        result, cere = _run(observation={"ball": {"x_cm": "左边", "distance_cm": 12.0}})
        self.assertEqual(result["status"], "failed")
        self.assertEqual(cere.calls.get("kick", 0), 0)


class TestKickClosedLoopRegression(unittest.TestCase):
    """闭环语义不回归：iterations / converged / 尽力踢。"""

    def test_servo_mock_converges_within_budget(self):
        bus = MockServoBus()
        cere = SpyCerebellum(bus=bus)
        perception = _servo_perception(bus, ball_x_true=3.0)
        result, _ = _run(perception=perception, cerebellum=cere)
        self.assertEqual(result["status"], "ok", result)
        self.assertTrue(result["converged"])
        self.assertGreaterEqual(result["iterations"], 1)
        self.assertLess(result["iterations"], KICK_DEFAULTS["max_iters"])
        self.assertLessEqual(abs(result["ball_x_cm"]), KICK_DEFAULTS["deadband_cm"])
        self.assertEqual(cere.calls.get("kick"), 1)

    def test_static_observation_stops_at_cap_and_still_kicks(self):
        """静态坏观测：必须在上限处停下（不空转），并且仍尽力踢一次。"""
        result, cere = _run(observation=_static_ball(x_cm=5.0))
        self.assertEqual(result["status"], "ok")
        self.assertFalse(result["converged"])
        self.assertEqual(result["iterations"], KICK_DEFAULTS["max_iters"])
        self.assertEqual(cere.calls.get("kick"), 1)

    def test_oscillating_gain_pair_still_reports_not_converged(self):
        """gain·step_gain ≥ 2 时闭环震荡：技能不许假装收敛，但也不能不踢。"""
        bus = MockServoBus()
        cere = SpyCerebellum(bus=bus)
        perception = _servo_perception(bus, ball_x_true=3.0)
        result, _ = _run(
            params={"step_gain": 1.4},  # 1.5 cm/deg × 1.4 deg/cm = 2.1 ≥ 2 → 过冲
            perception=perception,
            cerebellum=cere,
        )
        self.assertEqual(result["status"], "ok")
        self.assertFalse(result["converged"])
        self.assertEqual(result["iterations"], KICK_DEFAULTS["max_iters"])
        self.assertEqual(cere.calls.get("kick"), 1)

    def test_foot_choice_follows_final_lateral_offset(self):
        bus = MockServoBus()
        perception = _servo_perception(bus, ball_x_true=-3.0)
        result, _ = _run(perception=perception, cerebellum=SpyCerebellum(bus=bus))
        self.assertEqual(result["kick"]["foot"], "left")
        self.assertEqual(result["tuning_source"], "code-defaults")

    def test_empty_params_keeps_working(self):
        """向后兼容：任务卡不加任何参数也能跑（T-04 卡现在就是空 params）。"""
        result, _ = _run(params={}, observation=_static_ball(x_cm=1.0))
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["converged"])
        self.assertEqual(result["iterations"], 0)


