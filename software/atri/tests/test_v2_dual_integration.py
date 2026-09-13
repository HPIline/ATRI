"""Integrated passive-bearing ownership; not a load certification."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "design"))
from v2.assembly3d import has_passive_support, kinematic_tree  # noqa: E402


class DualIntegrationTests(unittest.TestCase):
    def test_engineered_rear_supports_enabled(self):
        joints = {j['name']: j for j in kinematic_tree()['joints']}
        for name in ('left_hip_roll', 'right_hip_roll', 'trunk_roll'):
            self.assertTrue(has_passive_support(joints[name]))
        for side in ('left', 'right'):
            for suffix in ('shoulder_pitch', 'shoulder_roll', 'elbow_pitch'):
                self.assertFalse(has_passive_support(joints[side+'_'+suffix]))
            self.assertFalse(has_passive_support(joints[side+'_gripper']))
        self.assertFalse(has_passive_support(joints['head_yaw']))
