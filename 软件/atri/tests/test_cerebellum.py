import unittest

from atri.cerebellum import Cerebellum, MockServoBus
from atri.config import JOINTS


class TestCerebellum(unittest.TestCase):
    def setUp(self):
        self.bus = MockServoBus()
        self.cere = Cerebellum(servo_bus=self.bus)

    def test_home(self):
        pose = self.cere.home()
        self.assertEqual(len(pose), 22)
        self.assertEqual(pose["head_yaw"], 0.0)

    def test_set_pose_limits(self):
        applied = self.cere.set_pose({"head_yaw": 200.0, "left_knee_pitch": -5.0})
        self.assertEqual(applied["head_yaw"], 90.0)
        self.assertEqual(applied["left_knee_pitch"], 0.0)

    def test_gait_frames(self):
        frames = self.cere.generate_gait(steps=4, period_s=0.4)
        self.assertGreater(len(frames), 0)
        for frame in frames:
            for name in frame:
                lo, hi = JOINTS[name]["limit_deg"]
                self.assertGreaterEqual(frame[name], lo)
                self.assertLessEqual(frame[name], hi)

    def test_kick_and_dance(self):
        self.assertIn("action", self.cere.kick("right"))
        self.assertIn("action", self.cere.dance(bars=1))

    def test_execute_motion(self):
        result = self.cere.execute_motion("align", {})
        self.assertIsInstance(result, dict)
        self.assertIn("left_hip_pitch", result)
        self.assertIn("action", self.cere.execute_motion("kick", {}))


if __name__ == "__main__":
    unittest.main()
