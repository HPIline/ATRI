"""Integrated passive-bearing ownership; not a load certification."""
import unittest
from v2.assembly3d import kinematic_tree
from v2.cad_export import has_passive_support


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
