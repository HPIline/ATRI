import subprocess
import sys
import unittest
from pathlib import Path

import atri.config as config_module
from atri.config import DOF_COUNT, GROUP_DOF, JOINTS, clamp_angle, rest_pose


class TestConfig(unittest.TestCase):
    def test_22_dof_topology(self):
        self.assertEqual(len(JOINTS), DOF_COUNT)
        self.assertEqual(sum(GROUP_DOF.values()), DOF_COUNT)
        self.assertEqual([s["id"] for s in JOINTS.values()], list(range(DOF_COUNT)))

    def test_groups(self):
        self.assertEqual(GROUP_DOF["leg_l"], 5)
        self.assertEqual(GROUP_DOF["leg_r"], 5)
        self.assertEqual(GROUP_DOF["arm_l"], 4)
        self.assertEqual(GROUP_DOF["arm_r"], 4)
        self.assertEqual(GROUP_DOF["trunk"], 2)
        self.assertEqual(GROUP_DOF["head"], 2)

    def test_limits(self):
        self.assertEqual(clamp_angle("head_yaw", 999.0), 90.0)
        self.assertEqual(clamp_angle("head_yaw", -999.0), -90.0)
        self.assertEqual(clamp_angle("head_yaw", 12.0), 12.0)

    def test_rest_pose(self):
        pose = rest_pose()
        self.assertEqual(len(pose), 22)

    def test_clamp_angle_rejects_nan(self):
        for joint in ("right_knee_pitch", "head_yaw"):
            with self.assertRaises(ValueError) as ctx:
                clamp_angle(joint, float("nan"))
            self.assertIn(joint, str(ctx.exception))

    def test_clamp_angle_rejects_inf(self):
        for value in (float("inf"), float("-inf")):
            with self.assertRaises(ValueError):
                clamp_angle("head_yaw", value)

    def test_clamp_angle_unknown_joint_raises_value_error(self):
        with self.assertRaises(ValueError) as ctx:
            clamp_angle("head_graw", 5.0)
        self.assertIn("head_graw", str(ctx.exception))

    def test_clamp_angle_rejects_non_number(self):
        for value in (None, "abc", [1.0]):
            with self.assertRaises(ValueError) as ctx:
                clamp_angle("head_yaw", value)
            self.assertIn("head_yaw", str(ctx.exception))

    def test_clamp_angle_rejects_unrepresentable_int(self):
        with self.assertRaises(ValueError) as ctx:
            clamp_angle("head_yaw", 10 ** 400)
        self.assertIn("head_yaw", str(ctx.exception))

    def test_deg_to_pulse_rejects_non_finite(self):
        from atri.config import deg_to_pulse
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.assertRaises(ValueError):
                deg_to_pulse("head_yaw", value)

    def test_motion_limit_constants(self):
        self.assertEqual(config_module.MAX_STEPS, 20)
        self.assertEqual(config_module.MAX_BARS, 8)
        self.assertEqual(config_module.MAX_TURN_DEG, 135.0)
        self.assertEqual(
            config_module.VALID_ACTIONS,
            {"walk", "turn", "kick", "carry", "dance", "grasp", "release"},
        )

    def test_joint_by_id_mapping(self):
        mapping = config_module.JOINT_BY_ID
        self.assertEqual(len(mapping), DOF_COUNT)
        self.assertEqual(mapping[6], "left_hip_pitch")
        self.assertEqual(mapping[12], "right_knee_pitch")

    def test_topology_violation_raises_runtime_error(self):
        saved = dict(JOINTS)
        try:
            JOINTS["extra"] = {"id": 99, "group": "x", "limit_deg": [0, 1], "rest_deg": 0.0}
            with self.assertRaises(RuntimeError):
                config_module._assert_topology()
        finally:
            JOINTS.clear()
            JOINTS.update(saved)

    def test_topology_check_survives_optimize(self):
        script = (
            "import atri.config as c\n"
            "c.JOINTS['extra'] = {'id': 99, 'group': 'x', 'limit_deg': [0, 1], 'rest_deg': 0.0}\n"
            "try:\n"
            "    c._assert_topology()\n"
            "except RuntimeError:\n"
            "    print('RAISED')\n"
        )
        root = Path(__file__).resolve().parents[1]
        proc = subprocess.run(
            [sys.executable, "-O", "-B", "-c", script],
            cwd=str(root),
            capture_output=True,
            text=True,
        )
        self.assertIn("RAISED", proc.stdout, proc.stderr)


if __name__ == "__main__":
    unittest.main()
