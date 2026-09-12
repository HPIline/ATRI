import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from atri.brain import Brain
from atri.cerebellum import Cerebellum, MockServoBus
from atri.perception import MockPerception
from atri.sim import build_robot, load_task_cards, main, run_task_cards
from atri.task_card import TaskCard


def _no_sleep(dt):
    return None


def _walk_card():
    return TaskCard.from_dict(
        {
            "task_id": "W-01",
            "name": "走两步",
            "skills": ["qr"],
            "params": {"default_payload": {"action": "walk", "steps": 2}},
        }
    )


class SpyCerebellum(Cerebellum):
    def __init__(self):
        super().__init__(servo_bus=MockServoBus(), sleeper=_no_sleep)
        self.walks = []

    def walk(self, steps=6, **kwargs):
        self.walks.append({"steps": steps, **kwargs})
        return super().walk(steps=steps, **kwargs)


class TestSimFast(unittest.TestCase):
    def test_fast_demo_passes(self):
        self.assertEqual(main(["--fast"]), 0)

    def test_bad_card_does_not_abort_demo(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            good = {"task_id": "A-GOOD", "name": "好卡", "skills": ["face"]}
            (directory / "a_good.json").write_text(
                json.dumps(good, ensure_ascii=False), encoding="utf-8"
            )
            (directory / "b_bad.json").write_text(
                json.dumps({"task_id": "B-BAD"}), encoding="utf-8"
            )
            robot = build_robot({}, sleeper=_no_sleep)
            results, passed, total = run_task_cards(
                robot["brain"],
                task_card_dir=directory,
                observation={"face": {"name": "测试员A"}},
                verbose=False,
            )
            self.assertEqual(total, 2)
            self.assertEqual(passed, 1)
            failures = [item for item in results if not item["ok"]]
            self.assertEqual(len(failures), 1)
            self.assertIn("TaskCardError", failures[0]["error"])
            self.assertEqual(failures[0]["task_id"], "b_bad")

            buf = io.StringIO()
            with redirect_stdout(buf):
                cards = load_task_cards(directory)
            self.assertEqual([card.task_id for card in cards], ["A-GOOD"])
            self.assertIn("b_bad", buf.getvalue())

    def test_build_robot_applies_gait_config(self):
        observation = {"qr": {"payload": {"action": "walk", "steps": 2}}}
        default_gait = build_robot({}, sleeper=_no_sleep)["brain"].execute_task(
            _walk_card(), observation=observation
        )
        self_checked = default_gait["result"]["results"][0]["detail"]["frames"]

        config = {
            "motion": {
                "backend": "scripted",
                "gait": {"step_length_cm": 2.0, "step_height_cm": 1.2, "period_s": 0.4},
            }
        }
        robot = build_robot(config, sleeper=_no_sleep)
        result = robot["brain"].execute_task(_walk_card(), observation=observation)
        self.assertTrue(result["ok"])
        frames = result["result"]["results"][0]["detail"]["frames"]
        self.assertEqual(frames, 40)
        self.assertLess(frames, self_checked)

    def test_build_robot_applies_fsm_verbosity(self):
        card = TaskCard.from_dict(
            {"task_id": "V-01", "name": "静默", "skills": ["face"], "params": {"expect_names": ["测试员A"]}}
        )
        robot = build_robot({"brain": {"fsm_verbosity": 0}}, sleeper=_no_sleep)
        quiet = io.StringIO()
        with redirect_stdout(quiet):
            robot["brain"].execute_task(card, observation={"face": {"name": "测试员A"}})
        self.assertNotIn("[FSM:", quiet.getvalue())

        noisy = build_robot({"brain": {"fsm_verbosity": 1}}, sleeper=_no_sleep)
        loud = io.StringIO()
        with redirect_stdout(loud):
            noisy["brain"].execute_task(card, observation={"face": {"name": "测试员A"}})
        self.assertIn("[FSM:", loud.getvalue())

    def test_build_robot_default_perception_is_mock(self):
        robot = build_robot({}, sleeper=_no_sleep)
        self.assertIsInstance(robot["perception"], MockPerception)

    def test_build_robot_servo_backend(self):
        from atri.perception import ServoMockPerception
        robot = build_robot({"perception": {"backend": "servo"}}, sleeper=_no_sleep)
        self.assertIsInstance(robot["perception"], ServoMockPerception)

    def test_build_robot_uses_opencv_when_available(self):
        with mock.patch("atri.sim.OpenCVPerception") as fake:
            fake.return_value.available.return_value = True
            robot = build_robot({"perception": {"backend": "opencv"}}, sleeper=_no_sleep)
            self.assertIs(robot["perception"], fake.return_value)

    def test_build_robot_warns_when_backend_unavailable(self):
        with mock.patch("atri.sim.OpenCVPerception") as fake:
            fake.return_value.available.return_value = False
            buf = io.StringIO()
            with redirect_stdout(buf):
                robot = build_robot({"perception": {"backend": "opencv"}}, sleeper=_no_sleep)
            self.assertIsInstance(robot["perception"], MockPerception)
            self.assertIn("降级", buf.getvalue())

    def test_build_robot_warns_on_unknown_backend(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            robot = build_robot({"perception": {"backend": "nonsense"}}, sleeper=_no_sleep)
        self.assertIsInstance(robot["perception"], MockPerception)
        self.assertIn("nonsense", buf.getvalue())

    def test_build_robot_warns_on_unused_control_period(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            build_robot({"cerebellum": {"control_period_ms": 10}}, sleeper=_no_sleep)
        self.assertIn("control_period_ms", buf.getvalue())

        quiet = io.StringIO()
        with redirect_stdout(quiet):
            build_robot({"cerebellum": {"control_period_ms": 20}}, sleeper=_no_sleep)
        self.assertNotIn("control_period_ms", quiet.getvalue())


class TestSimScheduling(unittest.TestCase):
    def test_skill_context_gait_reaches_walk(self):
        cere = SpyCerebellum()
        brain = Brain(cere, gait={"period_s": 0.4})
        result = brain.execute_task(
            _walk_card(), observation={"qr": {"payload": {"action": "walk", "steps": 2}}}
        )
        self.assertTrue(result["ok"])
        self.assertEqual(cere.walks[0]["period_s"], 0.4)


if __name__ == "__main__":
    unittest.main()
