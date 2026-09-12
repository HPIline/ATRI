import threading
import time
import unittest

from atri.brain import Brain
from atri.cerebellum import Cerebellum, MockServoBus
from atri.config import JOINTS, MAX_STEPS, VALID_ACTIONS
from atri.perception import PerceptionError
from atri.skills import Skill
from atri.task_card import TaskCard


class SpyCerebellum(Cerebellum):
    """记录底层动作调用次数，用于验证技能不会重复或越权执行实体动作。"""

    def __init__(self, sleeper=None, bus=None):
        super().__init__(servo_bus=bus or MockServoBus(),
                         sleeper=sleeper or (lambda dt: None))
        self.calls = {}
        self.call_threads = {}
        self.trajectories = []

    def _tick(self, name):
        self.calls[name] = self.calls.get(name, 0) + 1
        self.call_threads.setdefault(name, []).append(threading.current_thread().name)

    def execute_trajectory(self, frames, dt_s=0.02):
        result = super().execute_trajectory(frames, dt_s)
        self.trajectories.append(result)
        return result

    def set_pose(self, targets):
        self._tick("set_pose")
        return super().set_pose(targets)

    def turn(self, *args, **kwargs):
        self._tick("turn")
        return super().turn(*args, **kwargs)

    def home(self):
        self._tick("home")
        return super().home()

    def kick(self, *args, **kwargs):
        self._tick("kick")
        return super().kick(*args, **kwargs)

    def dance(self, *args, **kwargs):
        self._tick("dance")
        return super().dance(*args, **kwargs)

    def walk(self, *args, **kwargs):
        self._tick("walk")
        return super().walk(*args, **kwargs)

    def grasp(self, *args, **kwargs):
        self._tick("grasp")
        return super().grasp(*args, **kwargs)

    def release(self, *args, **kwargs):
        self._tick("release")
        return super().release(*args, **kwargs)

    def execute_motion(self, *args, **kwargs):
        self._tick("execute_motion")
        return super().execute_motion(*args, **kwargs)


class SlowSkill(Skill):
    name = "slow"

    def run(self, ctx):
        time.sleep(0.25)
        return {"skill": self.name, "status": "ok"}


class ThreadRecordingBus(MockServoBus):
    """记录每次总线写发生在哪个线程，用于验证只有主线程写总线。"""

    def __init__(self):
        super().__init__()
        self.write_threads = []

    def _write_angle(self, joint_id, deg):
        self.write_threads.append(threading.current_thread().name)
        super()._write_angle(joint_id, deg)


def _card(skills, **kwargs):
    return TaskCard.from_dict({"task_id": "U-01", "name": "unit", "skills": skills, **kwargs})


class TestBrain(unittest.TestCase):
    def setUp(self):
        self.cere = Cerebellum(servo_bus=MockServoBus(), sleeper=lambda dt: None)
        self.brain = Brain(self.cere)

    def _run(self, skills, obs=None):
        return self.brain.execute_task(_card(skills), observation=obs or {})

    def test_face(self):
        result = self._run(["face"], {"face": {"name": "测试员B", "confidence": 0.9}})
        self.assertTrue(result["ok"])
        self.assertEqual(result["result"]["results"][0]["name"], "测试员B")

    def test_qr(self):
        result = self._run(["qr"], {"qr": {"payload": {"action": "walk", "steps": 2}}})
        self.assertTrue(result["ok"])

    def test_carry(self):
        # 观测必须给 x_cm：**缺横向偏移不再当成"居中"**（2026-09-13 改，
        # 与放置区那一侧的 fail-safe 对齐；独立复核问题 4）。
        result = self._run(
            ["carry"], {"object": {"target": "蓝块", "x_cm": 0.5, "distance_cm": 4.0}}
        )
        self.assertTrue(result["ok"])

    def test_carry_without_lateral_offset_fails(self):
        """缺 x_cm 时不许盲抓：判失败。

        这里只判"整张卡不 ok + 原因"，"一个动作都不下发"由
        ``tests/test_carry_tuning.py::test_missing_or_invalid_x_cm_is_fail_safe``
        用假小脑严格断言（本类的 cere 是真实 Cerebellum，不记录调用）。
        """
        result = self._run(["carry"], {"object": {"target": "蓝块", "distance_cm": 4.0}})
        self.assertFalse(result["ok"])
        self.assertIn("横向偏移", result["error"])

    def test_kick(self):
        result = self._run(["kick"], {"ball": {"x_cm": -2.0, "distance_cm": 10.0}})
        self.assertTrue(result["ok"])

    def test_dance(self):
        result = self._run(["dance"], {"speech": {"keyword": "跳舞"}})
        self.assertTrue(result["ok"])

    def test_face_uses_perception_when_no_observation(self):
        from atri.perception import MockPerception
        from atri.voice import MockTTS
        tts = MockTTS()
        brain = Brain(self.cere, perception=MockPerception(face={"name": "感知A"}), tts=tts)
        card = _card(["face"], task_id="P-01")
        result = brain.execute_task(card, observation=None)
        self.assertTrue(result["ok"])
        self.assertEqual(result["result"]["results"][0]["name"], "感知A")
        self.assertIn("感知A", tts.spoken[0])


class TestSkillOutcome(unittest.TestCase):
    """B-1/B-2：技能要返回真实成败，感知失败不得执行实体动作，且不重复执行。"""

    def _brain(self):
        cere = SpyCerebellum()
        return Brain(cere), cere

    def test_kick_with_found_false_does_not_kick(self):
        brain, cere = self._brain()
        result = brain.execute_task(_card(["kick"]), observation={"ball": {"found": False}})
        self.assertFalse(result["ok"])
        self.assertIn("ball", result["error"])
        self.assertEqual(cere.calls.get("kick", 0), 0)

    def test_kick_found_falsy_values_all_fail(self):
        """found 键存在但为假（False/0/None/""）都算感知未命中，不得下发动作。"""
        for value in (False, 0, None, ""):
            with self.subTest(found=value):
                brain, cere = self._brain()
                result = brain.execute_task(
                    _card(["kick"]),
                    observation={"ball": {"found": value, "x_cm": 1.0, "distance_cm": 12.0}},
                )
                self.assertFalse(result["ok"])
                self.assertEqual(cere.calls.get("kick", 0), 0)

    def test_kick_without_distance_measurement_fails(self):
        """found=True 但没有测距：不得用硬编码 12cm 兜底后照样踢。

        OpenCV 路径在焦距未标定时把 distance_cm 置 None（显式"测不出"），
        观测里整条缺键与之等价，都应判失败，而不是把缺测当成 12cm。
        """
        for ball in ({"found": True, "x_cm": 1.0},
                     {"found": True, "x_cm": 1.0, "distance_cm": None}):
            with self.subTest(ball=ball):
                brain, cere = self._brain()
                result = brain.execute_task(_card(["kick"]), observation={"ball": ball})
                self.assertFalse(result["ok"])
                self.assertEqual(cere.calls.get("kick", 0), 0)

    def test_kick_distance_can_come_from_task_card(self):
        """任务卡显式给出的兜底距离是合法来源（与 carry 技能同一约定）。"""
        brain, cere = self._brain()
        result = brain.execute_task(
            _card(["kick"], params={"distance_cm": 15.0, "x_cm": 2.0}),
            observation={"ball": {"found": True}},
        )
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(cere.calls.get("kick"), 1)
        self.assertEqual(result["result"]["results"][0]["distance_cm"], 15.0)

    def test_kick_without_found_key_keeps_legacy_semantics(self):
        brain, cere = self._brain()
        result = brain.execute_task(
            _card(["kick"]), observation={"ball": {"x_cm": 1.0, "distance_cm": 12.0}}
        )
        self.assertTrue(result["ok"])
        self.assertEqual(cere.calls.get("kick"), 1)

    def test_huge_int_observation_is_skill_failure_not_error(self):
        """超大整数观测转技能失败，OverflowError 不得冒到 FSM。"""
        from atri.skills.base import as_finite_float
        self.assertIsNone(as_finite_float(10 ** 400))
        brain, cere = self._brain()
        result = brain.execute_task(
            _card(["kick"]),
            observation={"ball": {"x_cm": 10 ** 400, "distance_cm": 12.0}},
        )
        self.assertFalse(result["ok"])
        self.assertNotIn("OverflowError", result["error"])
        self.assertEqual(cere.calls.get("kick", 0), 0)

    def test_kick_with_empty_observation_does_not_kick(self):
        brain, cere = self._brain()
        result = brain.execute_task(_card(["kick"]), observation={})
        self.assertFalse(result["ok"])
        self.assertEqual(cere.calls.get("kick", 0), 0)

    def test_kick_triggers_underlying_action_once(self):
        brain, cere = self._brain()
        result = brain.execute_task(
            _card(["kick"]), observation={"ball": {"x_cm": 1.0, "distance_cm": 12.0}}
        )
        self.assertTrue(result["ok"])
        self.assertEqual(cere.calls.get("kick"), 1)
        self.assertNotIn("execute_motion", cere.calls)

    def test_dance_triggers_underlying_action_once(self):
        brain, cere = self._brain()
        result = brain.execute_task(
            _card(["dance"], params={"bars": 2}), observation={"speech": {"keyword": "跳舞"}}
        )
        self.assertTrue(result["ok"])
        self.assertEqual(cere.calls.get("dance"), 1)
        self.assertNotIn("execute_motion", cere.calls)

    def test_skill_failure_stops_remaining_skills(self):
        brain, cere = self._brain()
        result = brain.execute_task(
            _card(["kick", "dance"]), observation={"ball": {"found": False}}
        )
        self.assertFalse(result["ok"])
        self.assertIn("kick", result["error"])
        self.assertEqual(cere.calls.get("dance", 0), 0)
        self.assertEqual(result["history"][-1], "DONE")

    def test_perception_error_becomes_skill_failure(self):
        class BrokenPerception:
            def detect_ball(self):
                raise PerceptionError("摄像头掉线")

        cere = SpyCerebellum()
        brain = Brain(cere, perception=BrokenPerception())
        result = brain.execute_task(_card(["kick"]), observation=None)
        self.assertFalse(result["ok"])
        self.assertIn("摄像头掉线", result["error"])
        self.assertEqual(result["history"][-1], "DONE")
        self.assertEqual(cere.calls.get("kick", 0), 0)


class TestQRSkillLimits(unittest.TestCase):
    """B-3：二维码指令越界、NaN、类型错误一律判失败，不裸冒异常，也不下发动作。"""

    def _run_qr(self, payload=None, observation=None, params=None):
        cere = SpyCerebellum()
        brain = Brain(cere)
        card = _card(["qr"], params=params or {})
        obs = observation if observation is not None else {"qr": {"payload": payload}}
        return brain.execute_task(card, observation=obs), cere

    def test_huge_steps_rejected(self):
        result, cere = self._run_qr({"action": "walk", "steps": 10 ** 9})
        self.assertFalse(result["ok"])
        self.assertIn("steps", result["error"])
        self.assertEqual(cere.calls.get("walk", 0), 0)

    def test_steps_zero_and_negative_rejected(self):
        for steps in (0, -3):
            result, cere = self._run_qr({"action": "walk", "steps": steps})
            self.assertFalse(result["ok"])
            self.assertEqual(cere.calls.get("walk", 0), 0)

    def test_nan_steps_rejected_without_value_error(self):
        result, _ = self._run_qr({"action": "walk", "steps": float("nan")})
        self.assertFalse(result["ok"])
        self.assertIn("steps", result["error"])
        self.assertNotIn("cannot convert", result["error"])

    def test_string_steps_rejected(self):
        result, cere = self._run_qr({"action": "walk", "steps": "3"})
        self.assertFalse(result["ok"])
        self.assertEqual(cere.calls.get("walk", 0), 0)

    def test_unknown_action_rejected(self):
        result, cere = self._run_qr({"action": "fly", "steps": 3})
        self.assertFalse(result["ok"])
        self.assertIn("fly", result["error"])
        self.assertNotIn("execute_motion", cere.calls)

    def test_list_payload_rejected(self):
        result, _ = self._run_qr(observation={"qr": {"payload": ["walk", 3]}})
        self.assertFalse(result["ok"])
        self.assertIn("payload", result["error"])

    def test_turn_deg_out_of_range_rejected(self):
        result, _ = self._run_qr({"action": "turn", "deg": 99999})
        self.assertFalse(result["ok"])
        self.assertIn("deg", result["error"])

    def test_turn_nan_deg_rejected(self):
        result, _ = self._run_qr({"action": "turn", "deg": float("nan")})
        self.assertFalse(result["ok"])
        self.assertIn("deg", result["error"])

    def test_dance_bars_out_of_range_rejected(self):
        result, cere = self._run_qr({"action": "dance", "bars": 999})
        self.assertFalse(result["ok"])
        self.assertIn("bars", result["error"])
        self.assertEqual(cere.calls.get("dance", 0), 0)

    def test_default_payload_used_only_without_qr_channel(self):
        result, cere = self._run_qr(observation={}, params={"default_payload": {"action": "walk", "steps": 3}})
        self.assertTrue(result["ok"])
        self.assertEqual(cere.calls.get("walk"), 1)

    def test_found_false_rejected_even_with_default_payload(self):
        result, cere = self._run_qr(
            observation={"qr": {"found": False}},
            params={"default_payload": {"action": "walk", "steps": 3}},
        )
        self.assertFalse(result["ok"])
        self.assertEqual(cere.calls.get("walk", 0), 0)

    def test_missing_payload_rejected_when_channel_ready(self):
        result, cere = self._run_qr(observation={"qr": {"found": True}})
        self.assertFalse(result["ok"])
        self.assertEqual(cere.calls.get("walk", 0), 0)

    def test_kick_carry_grasp_release_route_through_execute_motion(self):
        """B-3：非 walk/turn/dance 的合法动作必须经 execute_motion 下发且恰好一次。"""
        for action in ("kick", "carry", "grasp", "release"):
            with self.subTest(action=action):
                result, cere = self._run_qr({"action": action})
                self.assertTrue(result["ok"], result.get("error"))
                self.assertEqual(cere.calls.get("execute_motion"), 1)
                self.assertEqual(cere.calls.get("walk", 0), 0)
                self.assertEqual(cere.calls.get("dance", 0), 0)

    def test_valid_actions_match_qr_skill_routing(self):
        """VALID_ACTIONS 必须与 qr 技能实际可路由的动作集合同源，防止配置单方面扩容。"""
        routed = set()
        for action in sorted(VALID_ACTIONS):
            result, _ = self._run_qr({"action": action})
            self.assertTrue(result["ok"], f"{action} 未被技能成功下发: {result.get('error')}")
            routed.add(result["result"]["results"][0]["action"])
        self.assertEqual(routed, set(VALID_ACTIONS))


class TestCarryAndDanceLimits(unittest.TestCase):
    """B-3：搬运距离与舞蹈小节数同样要落在合法区间。"""

    def test_carry_distance_upper_bound(self):
        cere = SpyCerebellum()
        brain = Brain(cere)
        result = brain.execute_task(
            _card(["carry"]), observation={"object": {"target": "红块", "distance_cm": 1e18}}
        )
        self.assertFalse(result["ok"])
        self.assertIn("距离", result["error"])
        self.assertEqual(cere.calls.get("walk", 0), 0)
        self.assertEqual(cere.calls.get("grasp", 0), 0)

    def test_carry_distance_param_upper_bound(self):
        cere = SpyCerebellum()
        brain = Brain(cere)
        result = brain.execute_task(_card(["carry"], params={"distance_cm": 1000.0}), observation={})
        self.assertFalse(result["ok"])
        self.assertEqual(cere.calls.get("walk", 0), 0)

    def test_carry_unmeasurable_distance_fails(self):
        cere = SpyCerebellum()
        brain = Brain(cere)
        result = brain.execute_task(
            _card(["carry"]),
            observation={"object": {"target": "红块", "distance_cm": None}},
        )
        self.assertFalse(result["ok"])
        self.assertEqual(cere.calls.get("walk", 0), 0)

    def test_carry_found_false_fails(self):
        cere = SpyCerebellum()
        brain = Brain(cere)
        result = brain.execute_task(
            _card(["carry"], params={"distance_cm": 8.0}),
            observation={"object": {"found": False}},
        )
        self.assertFalse(result["ok"])
        self.assertEqual(cere.calls.get("grasp", 0), 0)

    def test_carry_params_fallback_without_channel(self):
        """无 object 通道不得靠任务卡参数兜底抓取（T-03 fail-fast）。"""
        cere = SpyCerebellum()
        brain = Brain(cere)
        result = brain.execute_task(_card(["carry"], params={"distance_cm": 8.0}), observation={})
        self.assertFalse(result["ok"])
        self.assertEqual(cere.calls.get("grasp", 0), 0)
        self.assertEqual(cere.calls.get("walk", 0), 0)
        self.assertEqual(cere.calls.get("release", 0), 0)

    def test_carry_misaligned_does_not_grasp(self):
        """看见目标但横向偏差过大：对齐后仍偏，不下发抓取。"""
        cere = SpyCerebellum()
        brain = Brain(cere)
        result = brain.execute_task(
            _card(["carry"]),
            observation={"object": {"found": True, "target": "红块",
                                    "x_cm": 12.0, "distance_cm": 8.0}},
        )
        self.assertFalse(result["ok"])
        self.assertEqual(cere.calls.get("grasp", 0), 0)
        self.assertEqual(cere.calls.get("walk", 0), 0)
        self.assertEqual(cere.calls.get("release", 0), 0)
        self.assertGreaterEqual(cere.calls.get("set_pose", 0), 1)

    def test_dance_bars_param_out_of_range(self):
        cere = SpyCerebellum()
        brain = Brain(cere)
        result = brain.execute_task(_card(["dance"], params={"bars": 99}), observation={})
        self.assertFalse(result["ok"])
        self.assertIn("bars", result["error"])
        self.assertEqual(cere.calls.get("dance", 0), 0)

    def test_dance_nan_bars_rejected(self):
        cere = SpyCerebellum()
        brain = Brain(cere)
        result = brain.execute_task(
            _card(["dance"], params={"bars": float("nan")}), observation={}
        )
        self.assertFalse(result["ok"])
        self.assertEqual(cere.calls.get("dance", 0), 0)


class TestFaceExpectations(unittest.TestCase):
    """B-6：expect_names 为空不得抛 IndexError，名单不匹配要给出明确失败原因。"""

    def test_empty_expect_names_does_not_raise(self):
        cere = SpyCerebellum()
        brain = Brain(cere)
        result = brain.execute_task(
            _card(["face"], params={"expect_names": []}),
            observation={"face": {"name": "测试员A"}},
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["result"]["results"][0]["name"], "测试员A")

    def test_perceived_name_outside_list_fails(self):
        cere = SpyCerebellum()
        brain = Brain(cere)
        result = brain.execute_task(
            _card(["face"], params={"expect_names": ["测试员A"]}),
            observation={"face": {"name": "路人", "confidence": 0.9}},
        )
        self.assertFalse(result["ok"])
        self.assertIn("路人", result["error"])
        self.assertIn("测试员A", result["error"])

    def test_face_found_false_fails(self):
        cere = SpyCerebellum()
        brain = Brain(cere)
        result = brain.execute_task(
            _card(["face"], params={"expect_names": ["测试员A"]}),
            observation={"face": {"found": False}},
        )
        self.assertFalse(result["ok"])


class TestTaskTimeout(unittest.TestCase):
    """B-3：timeout_s 必须真正中断超预算的任务。"""

    def test_timeout_marks_error_and_homes(self):
        cere = SpyCerebellum()
        brain = Brain(cere)
        brain.register_skill(SlowSkill())
        card = TaskCard(task_id="TO-1", name="超时", skills=["slow"], timeout_s=0.05)
        result = brain.execute_task(card)
        self.assertFalse(result["ok"])
        self.assertIn("TaskTimeoutError", result["error"])
        self.assertEqual(result["history"][-1], "ERROR")
        self.assertGreaterEqual(cere.calls.get("home", 0), 2)

    def test_timeout_skips_remaining_skills(self):
        cere = SpyCerebellum()
        brain = Brain(cere)
        brain.register_skill(SlowSkill())
        card = TaskCard(task_id="TO-2", name="超时", skills=["slow", "dance"], timeout_s=0.05)
        result = brain.execute_task(card, observation={"speech": {"keyword": "跳舞"}})
        self.assertFalse(result["ok"])
        self.assertIn("TaskTimeoutError", result["error"])
        self.assertEqual(cere.calls.get("dance", 0), 0)

    def test_task_within_budget_succeeds(self):
        brain = Brain(SpyCerebellum())
        card = TaskCard(task_id="OK-1", name="正常", skills=["face"], timeout_s=5.0)
        result = brain.execute_task(card, observation={"face": {"name": "测试员A"}})
        self.assertTrue(result["ok"])


class TestTimeoutConcurrency(unittest.TestCase):
    """B-4：超时复位只由主线程执行，长轨迹在帧边界协作中止，后续技能不下发。

    用真实 qr 技能的默认 payload 驱动一次 MAX_STEPS 步行走（20×40=800 帧），
    超出 50 ms 预算后应被 abort_event 在帧边界截断。
    """

    LONG_PAYLOAD = {"action": "walk", "steps": MAX_STEPS}

    def _run(self, skills, timeout_s=0.05):
        bus = ThreadRecordingBus()
        cere = SpyCerebellum(bus=bus, sleeper=lambda dt: time.sleep(0.002))
        brain = Brain(cere)
        card = TaskCard.from_dict({
            "task_id": "TO-9",
            "name": "并发超时",
            "skills": skills,
            "params": {"default_payload": self.LONG_PAYLOAD},
            "timeout_s": timeout_s,
        })
        result = brain.execute_task(card, observation={})
        return result, bus, cere

    def _dispatched_frames(self, cere):
        return sum(item["frames"] for item in cere.trajectories)

    def test_all_bus_writes_stay_on_main_thread(self):
        result, bus, cere = self._run(["qr"])
        self.assertFalse(result["ok"])
        self.assertTrue(bus.write_threads, "轨迹应至少下发过一帧")
        self.assertEqual(set(bus.write_threads), {"MainThread"})

    def test_timeout_home_runs_once_on_main_thread(self):
        result, bus, cere = self._run(["qr"])
        # 进入任务回零 1 次 + 超时复位 1 次；定时器线程不得再碰机器人
        self.assertEqual(cere.calls.get("home"), 2)
        self.assertEqual(set(cere.call_threads["home"]), {"MainThread"})

    def test_long_trajectory_is_truncated(self):
        result, bus, cere = self._run(["qr"])
        full_frames = len(cere.generate_gait(steps=MAX_STEPS, period_s=0.8))
        dispatched = self._dispatched_frames(cere)
        self.assertGreater(dispatched, 0)
        self.assertLess(dispatched, full_frames // 2,
                        f"超时后仍下发 {dispatched}/{full_frames} 帧")

    def test_remaining_skills_not_executed(self):
        result, bus, cere = self._run(["qr", "dance"])
        self.assertFalse(result["ok"])
        self.assertEqual(cere.calls.get("dance", 0), 0)


class SlowHomeCerebellum(SpyCerebellum):
    """让 enter() 阶段的首次 home() 变慢，模拟真机串行总线写 22 路的耗时。"""

    def __init__(self, home_delay, **kwargs):
        super().__init__(**kwargs)
        self.home_delay = home_delay
        self._home_calls = 0

    def home(self):
        self._home_calls += 1
        if self._home_calls == 1:
            time.sleep(self.home_delay)
        return super().home()


class TestTimeoutDeadlineBasis(unittest.TestCase):
    """超时预算必须从任务开始算，而不是从 execute() 开始算。

    Brain 的技能循环原先在 execute() 内部才取 deadline，比 FSM 的定时器晚了整个
    enter()（含首次 home() 写 22 路总线）。只要 enter() 耗时超过一个帧周期，
    首个技能的长轨迹被中止后返回 ok，循环就会继续进入下一个技能并下发实体动作。
    """

    LONG_PAYLOAD = {"action": "walk", "steps": MAX_STEPS}

    def _run(self, home_delay):
        cere = SlowHomeCerebellum(home_delay, sleeper=lambda dt: time.sleep(0.002))
        brain = Brain(cere)
        card = TaskCard.from_dict({
            "task_id": "TO-10",
            "name": "慢回零后超时",
            "skills": ["qr", "dance"],
            "params": {"default_payload": self.LONG_PAYLOAD},
            "timeout_s": 0.05,
        })
        return brain.execute_task(card, observation={}), cere

    def test_slow_enter_does_not_let_next_skill_run(self):
        for delay in (0.0, 0.002, 0.01, 0.03):
            with self.subTest(home_delay_ms=delay * 1000):
                result, cere = self._run(delay)
                self.assertFalse(result["ok"])
                self.assertEqual(
                    cere.calls.get("dance", 0), 0,
                    f"enter() 耗时 {delay * 1000:.0f}ms 后超时，dance 仍被下发",
                )

    def test_slow_enter_still_homes_exactly_once_after_timeout(self):
        result, cere = self._run(0.01)
        self.assertFalse(result["ok"])
        # 进入任务回零 1 次 + 超时复位 1 次
        self.assertEqual(cere.calls.get("home"), 2)


class TestServoClosedLoop(unittest.TestCase):
    """闭环：ServoMockPerception 把机器人 body yaw 反馈进观测，踢球/搬运应真正收敛。"""

    def _brain(self, ball_x_true=3.0, object_x_true=3.0):
        from atri.perception import ServoMockPerception
        cere = SpyCerebellum()
        perception = ServoMockPerception(
            bus=cere.bus,
            ball_x_true=ball_x_true,
            object_x_true=object_x_true,
        )
        return Brain(cere, perception=perception), cere

    def test_kick_converges_in_simulation(self):
        brain, cere = self._brain(ball_x_true=3.0)
        result = brain.execute_task(_card(["kick"]), observation=None)
        self.assertTrue(result["ok"], result.get("error"))
        payload = result["result"]["results"][0]
        self.assertTrue(payload["converged"])
        self.assertGreaterEqual(payload["iterations"], 1)
        self.assertLess(payload["iterations"], 5)
        self.assertEqual(cere.calls.get("kick"), 1)

    def test_carry_converges_then_acts_once(self):
        brain, cere = self._brain(object_x_true=3.0)
        result = brain.execute_task(_card(["carry"]), observation=None)
        self.assertTrue(result["ok"], result.get("error"))
        payload = result["result"]["results"][0]
        self.assertTrue(payload["aligned"])
        self.assertEqual(cere.calls.get("grasp"), 1)
        self.assertEqual(cere.calls.get("walk"), 1)
        self.assertEqual(cere.calls.get("release"), 1)

    def test_servo_perception_reflects_yaw(self):
        from atri.perception import ServoMockPerception
        bus = MockServoBus()
        perception = ServoMockPerception(bus=bus, ball_x_true=4.0, gain_cm_per_deg=1.0)
        self.assertEqual(perception.detect_ball().data["x_cm"], 4.0)
        bus.angles[JOINTS["left_hip_yaw"]["id"]] = 2.0
        bus.angles[JOINTS["right_hip_yaw"]["id"]] = 2.0
        self.assertAlmostEqual(perception.detect_ball().data["x_cm"], 2.0)

    def test_static_observation_hits_iteration_cap_and_still_kicks(self):
        """静态观测恒偏离：必须在上限处停下（不空转死循环），并仍尽力踢。"""
        cere = SpyCerebellum()
        brain = Brain(cere)
        result = brain.execute_task(
            _card(["kick"]), observation={"ball": {"x_cm": 5.0, "distance_cm": 12.0}}
        )
        self.assertTrue(result["ok"], result.get("error"))
        payload = result["result"]["results"][0]
        self.assertFalse(payload["converged"])
        self.assertEqual(payload["iterations"], 5)
        self.assertEqual(cere.calls.get("kick"), 1)

    def test_carry_static_misaligned_gives_up_without_acting(self):
        """静态观测恒偏离且超放弃阈值：不下发抓/走/放。"""
        cere = SpyCerebellum()
        brain = Brain(cere)
        result = brain.execute_task(
            _card(["carry"]),
            observation={"object": {"target": "红块", "x_cm": 12.0, "distance_cm": 8.0}},
        )
        self.assertFalse(result["ok"])
        self.assertEqual(cere.calls.get("grasp", 0), 0)
        self.assertEqual(cere.calls.get("walk", 0), 0)
        self.assertEqual(cere.calls.get("release", 0), 0)

    def test_kick_out_of_range_distance_fails(self):
        cere = SpyCerebellum()
        brain = Brain(cere)
        too_far = brain.execute_task(
            _card(["kick"]), observation={"ball": {"x_cm": 0.0, "distance_cm": 80.0}}
        )
        self.assertFalse(too_far["ok"])
        self.assertEqual(cere.calls.get("kick", 0), 0)
        too_near = brain.execute_task(
            _card(["kick"]), observation={"ball": {"x_cm": 0.0, "distance_cm": 1.0}}
        )
        self.assertFalse(too_near["ok"])
        self.assertEqual(cere.calls.get("kick", 0), 0)


class TestQRPathAndTurn(unittest.TestCase):
    def test_path_payload_executes_in_order(self):
        cere = SpyCerebellum()
        brain = Brain(cere)
        payload = {
            "path": [
                {"action": "walk", "steps": 2},
                {"action": "turn", "deg": 90},
                {"action": "walk", "steps": 2},
            ]
        }
        result = brain.execute_task(_card(["qr"]), observation={"qr": {"payload": payload}})
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(cere.calls.get("walk"), 2)
        self.assertEqual(cere.calls.get("turn"), 1)
        payload_out = result["result"]["results"][0]
        self.assertEqual(payload_out["path_len"], 3)

    def test_path_invalid_step_rejected_before_any_motion(self):
        """静态可判定的非法段 → **一步都不走**。

        原先这条断言的是"第一段照走、第二段才失败"（即逐段校验）。合并 T-02 时改成
        整条路径先校验，理由：``{"action":"fly"}`` 是**静态就能判定**的非法，而 qrgen
        生成时用的是同一套严格校验 —— 我们自己造的码不可能带这种段。真出现它，
        说明码是外来的或损坏的，按一条已知损坏的路径走一半比停在原地更糟。
        运行期才暴露的失败（小脑层报错等）仍会逐段停下并报 ``path[i]``。
        """
        cere = SpyCerebellum()
        brain = Brain(cere)
        payload = {"path": [{"action": "walk", "steps": 2}, {"action": "fly"}]}
        result = brain.execute_task(_card(["qr"]), observation={"qr": {"payload": payload}})
        self.assertFalse(result["ok"])
        self.assertEqual(cere.calls.get("walk", 0), 0)
        self.assertIn("path[1]", result["error"])

    def test_turn_uses_stepping_not_hip_pose_only(self):
        cere = SpyCerebellum()
        brain = Brain(cere)
        result = brain.execute_task(
            _card(["qr"]), observation={"qr": {"payload": {"action": "turn", "deg": 90}}}
        )
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(cere.calls.get("turn"), 1)
        detail = result["result"]["results"][0]["detail"]
        self.assertGreaterEqual(detail["frames"], 2)
        self.assertEqual(detail["action"], "turn")


class TestDanceSpeechGate(unittest.TestCase):
    def test_unknown_keyword_fails_when_channel_ready(self):
        cere = SpyCerebellum()
        brain = Brain(cere)
        result = brain.execute_task(
            _card(["dance"]), observation={"speech": {"keyword": "起飞", "found": True}}
        )
        self.assertFalse(result["ok"])
        self.assertEqual(cere.calls.get("dance", 0), 0)

    def test_params_fallback_without_speech_channel(self):
        cere = SpyCerebellum()
        brain = Brain(cere)
        result = brain.execute_task(
            _card(["dance"], params={"keyword": "跳舞", "bars": 1}), observation={}
        )
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["result"]["results"][0]["source"], "params")
        self.assertEqual(cere.calls.get("dance"), 1)

    def test_mock_speech_keyword_is_used(self):
        from atri.perception import MockPerception
        cere = SpyCerebellum()
        brain = Brain(cere, perception=MockPerception(speech={"keyword": "跳舞", "found": True}))
        result = brain.execute_task(_card(["dance"], params={"bars": 1}), observation=None)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertEqual(result["result"]["results"][0]["source"], "perception")


if __name__ == "__main__":
    unittest.main()
