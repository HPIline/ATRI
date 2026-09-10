import unittest

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


if __name__ == "__main__":
    unittest.main()
