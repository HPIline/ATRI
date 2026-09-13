"""T-03 搬运：可调参数层（``atri.tuning``）与技能行为的回归测试。

分三块：
1. ``TestTuning``：参数文件的优先级、非法值回落、告警不抛异常——这是"实物到手后
   只改 JSON 就能标定"这条承诺的守门测试。
2. ``TestCarrySkill``：对准/夹取容差/放置区三步的行为，尤其是**没看见就不许动**。
3. ``TestBoundaryModelMatchesSkill``：``tools/carry_eval.py`` 的边界表数学模型必须与
   ``skills/base.py::lateral_servo`` 的真实现同解（否则报告里的边界表就是另一套东西）。
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from atri.perception import PerceptionResult
from atri.skills.base import SkillContext
from atri.skills.carry import CARRY_DEFAULTS, CarrySkill
from atri.tuning import Tuning, load_tuning, load_tuning_values, param_or, tuning_dir, tuning_path

SOFTWARE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SOFTWARE_ROOT.parents[1]


class TestTuning(unittest.TestCase):
    """参数层：缺文件=设计值；坏文件=告警+设计值；好文件=按类型覆盖。"""

    DEFAULTS = {"deadband_cm": 2.0, "max_iters": 5, "enabled": True, "label": "红块"}

    def _dir(self) -> tempfile.TemporaryDirectory:
        return tempfile.TemporaryDirectory()

    def test_missing_file_falls_back_to_defaults(self):
        with self._dir() as tmp:
            t = load_tuning("nope", self.DEFAULTS, path=tmp)
            self.assertEqual(t.values, self.DEFAULTS)
            self.assertFalse(t.source_exists)
            self.assertEqual(t.overridden, ())
            self.assertIn("设计值", t.provenance())

    def test_notes_only_file_does_not_count_as_override(self):
        """``_`` 开头的键是本仓库约定的注释；只有注释的文件 = 没覆盖任何键。"""
        with self._dir() as tmp:
            Path(tmp, "carry.json").write_text(
                json.dumps({"_note": "标定回填点", "_how": "只写要改的键"}, ensure_ascii=False),
                encoding="utf-8",
            )
            t = load_tuning("carry", self.DEFAULTS, path=tmp)
            self.assertEqual(t.values, self.DEFAULTS)
            self.assertEqual(t.overridden, ())
            self.assertTrue(t.source_exists)

    def test_valid_override_applied(self):
        with self._dir() as tmp:
            Path(tmp, "carry.json").write_text(
                json.dumps({"deadband_cm": 1.5, "max_iters": 9}), encoding="utf-8"
            )
            t = load_tuning("carry", self.DEFAULTS, path=tmp)
            self.assertEqual(t.values["deadband_cm"], 1.5)
            self.assertEqual(t.values["max_iters"], 9)
            self.assertTrue(t.is_overridden("deadband_cm"))
            self.assertIn("carry.json", t.provenance())

    def test_invalid_values_rejected_with_warning(self):
        """非有限数、该正不正、类型不符一律回落默认值，并留下告警（不静默、不抛异常）。"""
        bad = {
            "deadband_cm": -1.0,          # 默认值为正 → 必须 > 0
            "max_iters": "5",             # 类型不符
            "enabled": "yes",             # bool 位给字符串
            "label": 3,                   # str 位给数字
        }
        with self._dir() as tmp:
            Path(tmp, "carry.json").write_text(json.dumps(bad), encoding="utf-8")
            t = load_tuning("carry", self.DEFAULTS, path=tmp)
            self.assertEqual(t.values, self.DEFAULTS)
            self.assertEqual(len(t.warnings), 4)

    def test_nan_and_inf_rejected(self):
        with self._dir() as tmp:
            Path(tmp, "carry.json").write_text(
                '{"deadband_cm": NaN, "max_iters": Infinity}', encoding="utf-8"
            )
            t = load_tuning("carry", self.DEFAULTS, path=tmp)
            self.assertEqual(t.values, self.DEFAULTS)
            self.assertTrue(t.warnings)

    def test_broken_json_falls_back(self):
        with self._dir() as tmp:
            Path(tmp, "carry.json").write_text("{这不是 JSON", encoding="utf-8")
            t = load_tuning("carry", self.DEFAULTS, path=tmp)
            self.assertEqual(t.values, self.DEFAULTS)
            self.assertTrue(any("读取失败" in w for w in t.warnings))

    def test_non_object_top_level_falls_back(self):
        with self._dir() as tmp:
            Path(tmp, "carry.json").write_text("[1, 2]", encoding="utf-8")
            t = load_tuning("carry", self.DEFAULTS, path=tmp)
            self.assertEqual(t.values, self.DEFAULTS)
            self.assertTrue(any("顶层必须是对象" in w for w in t.warnings))

    def test_unknown_key_warns_and_is_ignored(self):
        with self._dir() as tmp:
            Path(tmp, "carry.json").write_text(
                json.dumps({"deadband_cm": 1.5, "deadband": 1.5}), encoding="utf-8"
            )
            t = load_tuning("carry", self.DEFAULTS, path=tmp)
            self.assertNotIn("deadband", t.values)
            self.assertEqual(t.overridden, ("deadband_cm",))
            self.assertTrue(any("未知键" in w for w in t.warnings))

    def test_negative_allowed_when_default_negative(self):
        with self._dir() as tmp:
            defaults = {"offset_cm": -1.0}
            Path(tmp, "x.json").write_text(json.dumps({"offset_cm": -3.5}), encoding="utf-8")
            t = load_tuning("x", defaults, path=tmp)
            self.assertEqual(t.values["offset_cm"], -3.5)

    def test_env_var_selects_directory(self):
        with self._dir() as tmp:
            Path(tmp, "carry.json").write_text(json.dumps({"deadband_cm": 3.0}), encoding="utf-8")
            with mock.patch.dict(os.environ, {"ATRI_TUNING_DIR": tmp}):
                self.assertEqual(tuning_dir(), Path(tmp))
                self.assertEqual(tuning_path("carry"), Path(tmp) / "carry.json")
                self.assertEqual(load_tuning_values("carry", self.DEFAULTS)["deadband_cm"], 3.0)

    def test_default_dir_is_package_config(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ATRI_TUNING_DIR", None)
            self.assertEqual(tuning_dir(), SOFTWARE_ROOT / "config")

    def test_param_or_priority(self):
        """任务卡 params > tuning 文件 > 代码默认值。"""
        tuning = {"deadband_cm": 1.5}
        self.assertEqual(param_or({"deadband_cm": 0.8}, tuning, "deadband_cm", 2.0), 0.8)
        self.assertEqual(param_or({}, tuning, "deadband_cm", 2.0), 1.5)
        self.assertEqual(param_or({}, {}, "deadband_cm", 2.0), 2.0)
        # 显式 None 视为"没写"，继续往下找
        self.assertEqual(param_or({"deadband_cm": None}, tuning, "deadband_cm", 2.0), 1.5)

    def test_real_carry_config_is_notes_only(self):
        """仓库里随代码发布的 ``config/carry.json`` 必须是纯说明：不能偷偷改设计值。"""
        t = load_tuning("carry", CARRY_DEFAULTS)
        self.assertEqual(t.values, CARRY_DEFAULTS)
        self.assertEqual(t.overridden, ())


class YawGeometryCerebellum:
    """记录下发动作，并把髋偏航角记下来——供"身体转角→观测"的几何感知读。"""

    def __init__(self) -> None:
        self.calls = []
        self.yaw = 0.0

    def set_pose(self, targets):
        if "left_hip_roll" in targets:
            self.yaw = float(targets["left_hip_roll"])
        elif "right_hip_roll" in targets:
            self.yaw = -float(targets["right_hip_roll"])
        self.calls.append(("set_pose", dict(targets)))
        return dict(targets)

    def grasp(self, *a, **k):
        self.calls.append(("grasp", {}))
        return {"action": "grasp"}

    def walk(self, steps=0, **k):
        self.calls.append(("walk", {"steps": steps}))
        return {"frames": steps}

    def release(self, *a, **k):
        self.calls.append(("release", {}))
        return {"action": "release"}

    def count(self, name: str) -> int:
        return sum(1 for call, _ in self.calls if call == name)


class GeometricPerception:
    """一维几何感知：``x_obs = x_true − gain × 身体偏航``（与工具里同一模型）。"""

    name = "geometric"

    def __init__(self, bus: YawGeometryCerebellum, object_x: float = 3.0,
                 place_x: float = 0.0, gain: float = 1.5) -> None:
        self.bus = bus
        self.object_x = object_x
        self.place_x = place_x
        self.gain = gain

    def _x(self, base: float) -> float:
        return round(base - self.gain * self.bus.yaw, 3)

    def detect_object(self, frame=None):
        return PerceptionResult(kind="object", data={
            "found": True, "target": "红块", "x_cm": self._x(self.object_x),
            "distance_cm": 8.0, "distance_source": "test-geometry",
        })

    def detect_place(self, frame=None):
        return PerceptionResult(kind="place", data={
            "found": True, "x_cm": self._x(self.place_x), "distance_source": "test-geometry",
        })


class ObjectOnlyPerception:
    """只有 ``detect_object`` 的后端 = 实机没有地标方案时的样子。

    注意不能用"把 ``detect_place`` 置 None"来模拟：``hasattr`` 仍然为真，
    技能会认为通道接入了。**没有这个属性**才是真的没有这个通道。
    """

    name = "geometric-object-only"

    def __init__(self, inner: "GeometricPerception") -> None:
        self._inner = inner

    def detect_object(self, frame=None):
        return self._inner.detect_object(frame)


def _ctx(cerebellum, perception, params=None):
    return SkillContext(
        task_id="T-03",
        task_name="物品搬运",
        params=dict(params or {}),
        cerebellum=cerebellum,
        perception=perception,
        tts_engine=None,
    )


class TestCarrySkill(unittest.TestCase):
    """三步行为：对准 → 夹取（容差）→ 放置（没看见不释放）。"""

    def test_aligned_object_is_grasped(self):
        bus = YawGeometryCerebellum()
        ctx = _ctx(bus, GeometricPerception(bus, object_x=3.0, place_x=0.0))
        result = CarrySkill().run(ctx)
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["aligned"])
        self.assertEqual(bus.count("grasp"), 1)
        self.assertEqual(bus.count("release"), 1)
        self.assertEqual(result["place"]["status"], "aligned")

    def test_misaligned_beyond_tolerance_never_grasps(self):
        bus = YawGeometryCerebellum()
        # gain 极小 ⇒ 转很多也纠不动，最终必然超容差
        ctx = _ctx(bus, GeometricPerception(bus, object_x=20.0, gain=0.01))
        result = CarrySkill().run(ctx)
        self.assertEqual(result["status"], "failed")
        self.assertIn("夹取容差", result["reason"])
        self.assertEqual(bus.count("grasp"), 0)
        self.assertEqual(bus.count("release"), 0)
        # 失败也要带过程量，供调参复盘
        self.assertEqual(result["iterations"], CARRY_DEFAULTS["max_iters"])
        self.assertIsNotNone(result["align_x_cm"])

    def test_unconverged_but_within_tolerance_grasps_and_says_so(self):
        """没进死区但在容差内：允许夹，但必须如实回报 aligned=False。"""
        bus = YawGeometryCerebellum()
        ctx = _ctx(
            bus,
            GeometricPerception(bus, object_x=4.0, gain=1.5),
            params={"deadband_cm": 0.2, "grasp_tolerance_cm": 6.0, "max_iters": 2},
        )
        result = CarrySkill().run(ctx)
        self.assertEqual(result["status"], "ok")
        self.assertFalse(result["aligned"])
        self.assertTrue(result["grasp_within_tolerance"])
        self.assertEqual(bus.count("grasp"), 1)

    def test_no_object_channel_fails_without_acting(self):
        bus = YawGeometryCerebellum()
        ctx = SkillContext(task_id="T-03", task_name="搬运", params={"distance_cm": 8.0},
                           cerebellum=bus, observation={}, perception=None)
        result = CarrySkill().run(ctx)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(bus.calls, [])

    def test_place_channel_missing_releases_with_honest_marker(self):
        bus = YawGeometryCerebellum()
        perception = ObjectOnlyPerception(GeometricPerception(bus, object_x=2.0))
        ctx = _ctx(bus, perception)
        result = CarrySkill().run(ctx)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["place"]["status"], "channel-unavailable")
        self.assertEqual(bus.count("release"), 1)

    def test_place_misaligned_does_not_release(self):
        """放着东西却对不准放置区：停住不动，**绝不**盲放。"""
        bus = YawGeometryCerebellum()
        ctx = _ctx(
            bus,
            GeometricPerception(bus, object_x=2.0, place_x=9.0, gain=0.05),
            params={"place_max_iters": 2, "place_give_up_cm": 1.0},
        )
        result = CarrySkill().run(ctx)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["place"]["status"], "failed")
        self.assertEqual(bus.count("grasp"), 1)     # 已经夹起来了
        self.assertEqual(bus.count("release"), 0)   # 但不放
        self.assertIn("未释放", result["place"]["reason"])

    def test_place_align_can_be_disabled(self):
        bus = YawGeometryCerebellum()
        ctx = _ctx(
            bus,
            GeometricPerception(bus, object_x=2.0, place_x=9.0),
            params={"place_align": False},
        )
        result = CarrySkill().run(ctx)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["place"]["status"], "disabled")
        self.assertEqual(bus.count("release"), 1)

    def test_place_channel_ready_but_not_found_fails(self):
        """地标方案有、但这一帧没看见 → 失败且不释放（不把"没看见"当成"放好了"）。"""
        bus = YawGeometryCerebellum()
        perception = GeometricPerception(bus, object_x=2.0)
        perception.detect_place = lambda frame=None: PerceptionResult(
            kind="place", data={"found": False}
        )
        ctx = _ctx(bus, perception)
        result = CarrySkill().run(ctx)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["place"]["status"], "failed")
        self.assertEqual(bus.count("release"), 0)

    def test_tuning_file_overrides_defaults(self):
        """第二层：tuning 文件压过代码默认值（用可观测的迭代数判，不看 tuning_source）。"""
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "carry.json").write_text(
                json.dumps({"deadband_cm": 0.5}), encoding="utf-8"
            )
            with mock.patch.dict(os.environ, {"ATRI_TUNING_DIR": tmp}):
                bus = YawGeometryCerebellum()
                from_file = CarrySkill().run(
                    _ctx(bus, GeometricPerception(bus, object_x=3.0))
                )
                self.assertEqual(from_file["tuning_source"], "carry.json")
                self.assertIn("deadband_cm", from_file["tuning_overridden"])

                bus2 = YawGeometryCerebellum()   # 无 tuning 文件时用代码默认（死区 2.0）
                with tempfile.TemporaryDirectory() as empty:
                    with mock.patch.dict(os.environ, {"ATRI_TUNING_DIR": empty}):
                        default = CarrySkill().run(
                            _ctx(bus2, GeometricPerception(bus2, object_x=3.0))
                        )
                self.assertEqual(default["tuning_source"], "code-defaults")
                # 死区 0.5 逼着闭环多纠几轮；死区 2.0 一轮就够——这就是"文件生效"的可观测证据。
                self.assertGreater(from_file["iterations"], default["iterations"])

    def test_task_card_params_beat_tuning_file(self):
        """第一层：任务卡 params 压过 tuning 文件。

        断言必须落在**行为量**上：上一版只断言 ``tuning_source == "carry.json"``，
        而该字段只由"文件是否覆盖"决定、与 params 无关——把优先级改反了它照样绿
        （独立复核用内存变异证明过）。这里用 step_gain 直接改变迭代次数来判断。
        """
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "carry.json").write_text(
                json.dumps({"step_gain": 0.25, "deadband_cm": 0.5}), encoding="utf-8"
            )
            with mock.patch.dict(os.environ, {"ATRI_TUNING_DIR": tmp}):
                bus = YawGeometryCerebellum()
                from_file = CarrySkill().run(
                    _ctx(bus, GeometricPerception(bus, object_x=6.0))
                )
                bus2 = YawGeometryCerebellum()
                from_card = CarrySkill().run(
                    _ctx(bus2, GeometricPerception(bus2, object_x=6.0),
                         params={"step_gain": 1.0})
                )
        # step_gain 0.25 每轮只挪一点 → 轮数明显多于 1.0；若"文件压过卡"，两者会相等。
        self.assertGreater(from_file["iterations"], from_card["iterations"])
        self.assertGreaterEqual(from_card["iterations"], 1)

    def test_missing_or_invalid_x_cm_is_fail_safe(self):
        """缺横向偏移 / NaN / 非数值：**判失败且不下发任何动作**。

        不能把"没量到"当成居中 0——那等于闭着眼睛对正中间下手；
        放置区那一侧本来就是 fail-safe，两侧口径必须一致（独立复核提出的问题 4）。
        """
        for bad in (None, float("nan"), "很远", [1.0]):
            with self.subTest(x_cm=bad):
                bus = YawGeometryCerebellum()
                perception = GeometricPerception(bus, object_x=1.0)
                perception.detect_object = lambda frame=None, bad=bad: PerceptionResult(
                    kind="object",
                    data={"found": True, "target": "红块", "x_cm": bad, "distance_cm": 8.0},
                )
                result = CarrySkill().run(_ctx(bus, perception))
                self.assertEqual(result["status"], "failed")
                self.assertIn("横向偏移", result["reason"])
                self.assertEqual(bus.calls, [])

    def test_tuning_warnings_are_attached_and_visible(self):
        """配置写错时：告警既要打出来（warn=print），也要挂在结果里（含失败分支）。"""
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "carry.json").write_text(
                json.dumps({"give_up_cm": 1.0, "deadband_cm": -1.0}), encoding="utf-8"
            )
            with mock.patch.dict(os.environ, {"ATRI_TUNING_DIR": tmp}):
                import io
                import contextlib

                captured = io.StringIO()
                bus = YawGeometryCerebellum()
                with contextlib.redirect_stdout(captured):
                    result = CarrySkill().run(
                        _ctx(bus, GeometricPerception(bus, object_x=1.0))
                    )
                self.assertEqual(result["status"], "ok")
                self.assertTrue(result["tuning_warnings"])
                self.assertIn("未知键", captured.getvalue())        # 不存在的键要看得见
                self.assertIn("必须 > 0", captured.getvalue())       # 非法值也要看得见

                # 失败分支同样要带告警（否则"改了没生效"现场查不出来）
                bus2 = YawGeometryCerebellum()
                bad_perception = GeometricPerception(bus2, object_x=1.0)
                bad_perception.detect_object = lambda frame=None: PerceptionResult(
                    kind="object", data={"found": False}
                )
                failed_result = CarrySkill().run(_ctx(bus2, bad_perception))
                self.assertEqual(failed_result["status"], "failed")
                self.assertIn("tuning_warnings", failed_result)

    def test_max_distance_still_enforced(self):
        bus = YawGeometryCerebellum()
        perception = GeometricPerception(bus, object_x=1.0)
        perception.detect_object = lambda frame=None: PerceptionResult(
            kind="object", data={"found": True, "target": "红块", "x_cm": 1.0,
                                 "distance_cm": 1000.0}
        )
        result = CarrySkill().run(_ctx(bus, perception))
        self.assertEqual(result["status"], "failed")
        self.assertIn("超出上限", result["reason"])
        self.assertEqual(bus.calls, [])


def _load_carry_eval():
    """惰性加载评测工具（它需要 numpy/cv2，零依赖环境里会跳过相关断言）。"""
    path = SOFTWARE_ROOT / "tools" / "carry_eval.py"
    spec = importlib.util.spec_from_file_location("carry_eval_under_test", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestBoundaryModelMatchesSkill(unittest.TestCase):
    """边界表的数学模型必须与技能真实现同解——否则报告里的表是另一套东西。

    对照方式：同一组参数下，一边跑 ``tools/carry_eval.py::simulate_servo``，
    一边跑真 ``lateral_servo``（喂一维几何感知），比对最终偏差与迭代次数。
    """

    def setUp(self):
        try:
            self.tool = _load_carry_eval()
        except (ImportError, SystemExit) as exc:  # 零依赖环境：numpy/cv2 缺失
            self.skipTest(f"评测工具需要 numpy/opencv：{exc}")

    def _run_skill_loop(self, x0, gain, deadband, max_iters, step_gain, clamp):
        bus = YawGeometryCerebellum()
        perception = GeometricPerception(bus, object_x=x0, gain=gain)
        ctx = _ctx(bus, perception, params={
            "deadband_cm": deadband, "max_iters": max_iters,
            "step_gain": step_gain, "step_clamp_deg": clamp,
            "grasp_tolerance_cm": 999.0,   # 只观察闭环本身，不要因为容差提前失败
        })
        result = CarrySkill().run(ctx)
        return result.get("align_x_cm"), result.get("iterations")

    def test_same_trajectory(self):
        from atri.skills.base import lateral_servo  # noqa: F401  (导入即为对照对象)

        cases = [
            (3.0, 1.5, 2.0, 5, 0.5, 10.0),
            (6.0, 0.21, 2.0, 5, 0.5, 10.0),
            (6.0, 0.21, 2.0, 15, 1.0, 10.0),
            (12.0, 0.14, 1.0, 20, 1.0, 20.0),
            (20.0, 0.7, 2.5, 8, 0.8, 45.0),
        ]
        for x0, gain, deadband, max_iters, step_gain, clamp in cases:
            with self.subTest(x0=x0, gain=gain, max_iters=max_iters):
                model_x, model_iters, _ = self.tool.simulate_servo(
                    x0, gain, deadband, max_iters, step_gain, clamp
                )
                skill_x, skill_iters = self._run_skill_loop(
                    x0, gain, deadband, max_iters, step_gain, clamp
                )
                self.assertAlmostEqual(model_x, skill_x, places=2)
                self.assertEqual(model_iters, skill_iters)


if __name__ == "__main__":
    unittest.main()
