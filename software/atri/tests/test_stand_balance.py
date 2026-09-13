"""自主站立：纯函数测例（不依赖 Webots）。"""
from __future__ import annotations

import math
import unittest

from atri.config import clamp_angle
from atri.stand_balance import (
    balance_offsets,
    evaluate_stand,
    pelvis_spawn_z_m,
    stand_base_pose,
)


class StandBasePoseTests(unittest.TestCase):
    def test_stand_pose_bends_knees(self):
        pose = stand_base_pose()
        self.assertGreater(pose["left_knee_pitch"], 0.0)
        self.assertGreater(pose["right_knee_pitch"], 0.0)
        self.assertLess(pose["left_hip_pitch"], 0.0)
        self.assertLess(pose["left_ankle_pitch"], 0.0)

    def test_stand_pose_abducts_hips_and_leans_back(self):
        pose = stand_base_pose()
        self.assertGreater(pose["left_hip_roll"], 0.0)
        self.assertLess(pose["right_hip_roll"], 0.0)
        self.assertGreater(pose["trunk_pitch"], 0.0)


class PelvisSpawnTests(unittest.TestCase):
    def test_foot_sole_sits_just_above_ground(self):
        # URDF 左腿：hip_pitch z=-0.032, thigh=-0.078, shank=-0.078；脚盒半高 6 mm
        z = pelvis_spawn_z_m(
            chain_z_m=-0.032 - 0.078 - 0.078,
            foot_half_z_m=0.006,
            clearance_m=0.002,
        )
        foot_bottom = z + (-0.188) - 0.006
        self.assertAlmostEqual(foot_bottom, 0.002, places=6)
        self.assertGreater(z, 0.15)
        self.assertLess(z, 0.25)


class BalanceOffsetTests(unittest.TestCase):
    def test_level_imu_adds_no_offset(self):
        off = balance_offsets(0.0, 0.0)
        self.assertEqual(off["left_ankle_pitch"], 0.0)
        self.assertEqual(off["right_ankle_pitch"], 0.0)
        self.assertEqual(off["left_hip_roll"], 0.0)
        self.assertEqual(off["right_hip_roll"], 0.0)

    def test_forward_pitch_moves_both_ankles_same_way(self):
        # 约定：IMU pitch>0（抬头/后仰）时踝负向，把质心往回推。
        off = balance_offsets(0.0, 0.2, kp_pitch=1.0, kp_roll=0.0)
        self.assertLess(off["left_ankle_pitch"], 0.0)
        self.assertEqual(off["left_ankle_pitch"], off["right_ankle_pitch"])

    def test_positive_roll_uses_hip_roll_placeholder_signs(self):
        off = balance_offsets(0.2, 0.0, kp_pitch=0.0, kp_roll=1.0)
        self.assertGreater(off["left_hip_roll"], 0.0)
        self.assertLess(off["right_hip_roll"], 0.0)

    def test_offsets_are_clamped_to_v2_limits(self):
        off = balance_offsets(2.0, 2.0, kp_pitch=50.0, kp_roll=50.0)
        self.assertEqual(off["left_hip_roll"], clamp_angle("left_hip_roll", 999))
        self.assertEqual(off["right_hip_roll"], clamp_angle("right_hip_roll", -999))
        self.assertEqual(off["left_ankle_pitch"], clamp_angle("left_ankle_pitch", -999))


class EvaluateStandTests(unittest.TestCase):
    def test_stable_height_and_tilt_passes(self):
        zs = [0.20] * 20
        rolls = [0.5] * 20
        pitches = [-0.4] * 20
        result = evaluate_stand(zs, rolls, pitches, min_samples=10)
        self.assertTrue(result["ok"])

    def test_fallen_height_fails(self):
        zs = [0.20, 0.18, 0.10, 0.04]
        result = evaluate_stand(zs, [0.0] * 4, [0.0] * 4, min_samples=3)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "pelvis_z")

    def test_large_tilt_fails(self):
        zs = [0.20] * 8
        pitches = [0.0, 5.0, 12.0, 25.0, 30.0, 28.0, 20.0, 18.0]
        result = evaluate_stand(zs, [0.0] * 8, pitches, min_samples=5, tilt_max_deg=15.0)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "tilt")
