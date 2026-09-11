import contextlib
import io
import threading
import unittest
from pathlib import Path
from unittest import mock

from atri.action_library import ActionLibraryError, load_action, validate_action
from atri.cerebellum import Cerebellum, MockServoBus, ServoBus
from atri.config import JOINTS, MAX_BARS, MAX_STEPS

EXAMPLES_DIR = Path(__file__).resolve().parents[1] / "action_library" / "examples"


class RecordingBus(ServoBus):
    """只记录 _write_angle 的最小总线，用于验证基类模板方法。"""

    def __init__(self):
        self.writes = []

    def _write_angle(self, joint_id, deg):
        self.writes.append((joint_id, deg))

    def read_angle(self, joint_id):
        return 0.0


class TestServoBusBase(unittest.TestCase):
    def test_set_angle_clamps_before_write(self):
        bus = RecordingBus()
        bus.set_angle(JOINTS["left_hip_pitch"]["id"], 999.0)
        self.assertEqual(bus.writes, [(6, 60.0)])

    def test_unknown_id_raises_value_error(self):
        with self.assertRaises(ValueError) as ctx:
            RecordingBus().set_angle(99, 0.0)
        self.assertIn("99", str(ctx.exception))

    def test_non_finite_rejected(self):
        with self.assertRaises(ValueError):
            RecordingBus().set_angle(6, float("nan"))

    def test_mock_bus_uses_base_template(self):
        self.assertNotIn("set_angle", MockServoBus.__dict__)
        self.assertIs(MockServoBus.set_angle, ServoBus.set_angle)


class TestCerebellum(unittest.TestCase):
    def setUp(self):
        self.bus = MockServoBus()
        self.cere = Cerebellum(servo_bus=self.bus, sleeper=lambda dt: None)

    def test_home(self):
        pose = self.cere.home()
        self.assertEqual(len(pose), 22)
        self.assertEqual(pose["head_yaw"], 0.0)

    def test_set_pose_limits(self):
        applied = self.cere.set_pose({"head_yaw": 200.0, "left_knee_pitch": -5.0})
        self.assertEqual(applied["head_yaw"], 90.0)
        self.assertEqual(applied["left_knee_pitch"], 0.0)

    def test_set_pose_unknown_joint_raises(self):
        with self.assertRaises(ValueError) as ctx:
            self.cere.set_pose({"head_graw": 5.0})
        self.assertIn("head_graw", str(ctx.exception))
        self.assertEqual(self.bus.command_log, [])

    def test_gait_frames(self):
        frames = self.cere.generate_gait(steps=4, period_s=0.4)
        self.assertGreater(len(frames), 0)
        for frame in frames:
            for name in frame:
                lo, hi = JOINTS[name]["limit_deg"]
                self.assertGreaterEqual(frame[name], lo)
                self.assertLessEqual(frame[name], hi)

    def test_generate_gait_step_bounds(self):
        for bad in (0, -1, MAX_STEPS + 1, 1000, 10 ** 9, 3.5, float("nan"), float("inf")):
            with self.assertRaises(ValueError) as ctx:
                self.cere.generate_gait(steps=bad)
            self.assertIn(f"1..{MAX_STEPS}", str(ctx.exception))
        frames = self.cere.generate_gait(steps=MAX_STEPS, period_s=0.02)
        self.assertEqual(len(frames), MAX_STEPS * 10)

    def test_walk_step_bounds(self):
        with self.assertRaises(ValueError):
            self.cere.walk(steps=MAX_STEPS + 1)
        result = self.cere.walk(steps=2, period_s=0.02)
        self.assertGreater(result["frames"], 0)

    def test_dance_bar_bounds(self):
        for bad in (0, MAX_BARS + 1, 100):
            with self.assertRaises(ValueError):
                self.cere.dance(bars=bad)
        self.assertIn("action", self.cere.dance(bars=MAX_BARS))

    def test_kick_commands_are_not_clamped_away(self):
        self.cere.kick("right")
        knee = JOINTS["right_knee_pitch"]
        cmds = [entry["deg"] for entry in self.bus.command_log if entry["id"] == knee["id"]]
        self.assertEqual({value for value in cmds if value != 0.0}, {8.0, 18.0, 5.0})
        for value in cmds:
            self.assertGreaterEqual(value, knee["limit_deg"][0])
            self.assertLessEqual(value, knee["limit_deg"][1])

    def test_kick_example_json_not_clamped(self):
        action = load_action(EXAMPLES_DIR / "kick.json")
        self.assertEqual(validate_action(action), [])
        self.cere.play_action(action)
        knee = JOINTS["right_knee_pitch"]
        cmds = [entry["deg"] for entry in self.bus.command_log if entry["id"] == knee["id"]]
        self.assertEqual({value for value in cmds if value != 0.0}, {8.0, 18.0, 5.0})

    def test_clamping_is_reported(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.cere.execute_trajectory([{"head_yaw": 200.0}], dt_s=0.01)
        out = buf.getvalue()
        self.assertIn("head_yaw", out)
        self.assertIn("200.0", out)
        self.assertIn("90.0", out)

    def test_no_clamp_notice_within_limits(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.cere.execute_trajectory([{"head_yaw": 45.0}], dt_s=0.01)
        self.assertEqual(buf.getvalue(), "")

    def test_kick_and_dance(self):
        self.assertIn("action", self.cere.kick("right"))
        self.assertIn("action", self.cere.dance(bars=1))

    def test_execute_motion(self):
        result = self.cere.execute_motion("align", {})
        self.assertIsInstance(result, dict)
        self.assertIn("left_hip_pitch", result)
        self.assertIn("action", self.cere.execute_motion("kick", {}))

    def test_execute_motion_release(self):
        result = self.cere.execute_motion("release", {})
        self.assertEqual(result["action"], "release")
        gripper_id = JOINTS["right_gripper"]["id"]
        self.assertTrue(any(entry["id"] == gripper_id for entry in self.bus.command_log))

    def test_execute_motion_unknown_raises(self):
        with self.assertRaises(ValueError) as ctx:
            self.cere.execute_motion("后空翻", {})
        self.assertIn("后空翻", str(ctx.exception))

    def test_play_action_executes_frames(self):
        action = {
            "schema_version": "1.0",
            "action_id": "walk",
            "name": "前进",
            "frames": [
                {"duration_s": 0.01, "joints": {"left_hip_pitch": 8.0}},
                {"duration_s": 0.01, "joints": {"right_hip_pitch": -8.0}},
            ],
        }
        result = self.cere.play_action(action)
        self.assertEqual(result["frames"], 2)
        self.assertEqual(self.bus.read_angle(6), 8.0)  # left_hip_pitch id 6
        self.assertEqual(self.bus.read_angle(11), -8.0)  # right_hip_pitch id 11

    def test_play_action_wraps_conversion_errors(self):
        action = {
            "schema_version": "1.0",
            "action_id": "bad",
            "frames": [{"duration_s": "abc", "joints": {"left_hip_pitch": 0.0}}],
        }
        with mock.patch("atri.action_library.validate_action", return_value=[]):
            with self.assertRaises(ActionLibraryError):
                self.cere.play_action(action)

    def test_play_action_rejects_out_of_limit_frame(self):
        action = {
            "schema_version": "1.0",
            "action_id": "bad",
            "frames": [{"duration_s": 0.01, "joints": {"left_knee_pitch": -10.0}}],
        }
        with self.assertRaises(ActionLibraryError):
            self.cere.play_action(action)

    def test_execute_trajectory_aborts_at_frame_boundary(self):
        """置位 abort event 后，自有轨迹应在帧边界提前结束。"""
        bus = MockServoBus()
        event = threading.Event()
        cere = Cerebellum(servo_bus=bus, sleeper=lambda dt: event.set())
        cere.set_abort_event(event)
        frames = cere.generate_gait(steps=MAX_STEPS, period_s=0.8)
        result = cere.execute_trajectory(frames)
        self.assertLess(result["frames"], len(frames))
        self.assertTrue(result["aborted"])

    def test_execute_trajectory_without_abort_runs_all_frames(self):
        cere = Cerebellum(servo_bus=MockServoBus(), sleeper=lambda dt: None)
        frames = [{"head_yaw": 0.0}, {"head_yaw": 5.0}]
        result = cere.execute_trajectory(frames)
        self.assertEqual(result["frames"], 2)
        self.assertNotIn("aborted", result)


if __name__ == "__main__":
    unittest.main()
