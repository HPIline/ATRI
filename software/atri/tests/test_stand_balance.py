"""自主站立：纯函数测例（不依赖 Webots）。"""
from __future__ import annotations

import math
import unittest

from atri.config import clamp_angle
from atri.stand_balance import (
    STAND_AVAILABLE_TORQUE_NM,
    STAND_CONTROL_D,
    STAND_CONTROL_I,
    STAND_CONTROL_P,
    STAND_KP_PITCH,
    STAND_KP_ROLL,
    balance_offsets,
    com_hold_offsets,
    evaluate_stand,
    flat_sole_ankles,
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

    def test_stand_pose_leans_back(self):
        pose = stand_base_pose()
        self.assertGreater(pose["trunk_pitch"], 0.0)

    def test_stand_torque_is_sts3215_stall_not_sim_cheat(self):
        self.assertAlmostEqual(STAND_AVAILABLE_TORQUE_NM, 2.94, places=2)
        self.assertLess(STAND_AVAILABLE_TORQUE_NM, 10.0)

    def test_stand_imu_pd_stays_off(self):
        """roll PD 拧翻；pitch PD=0.25 把倾角从 10° 推到 15°。开环才站得住。"""
        self.assertEqual(STAND_KP_ROLL, 0.0)
        self.assertEqual(STAND_KP_PITCH, 0.0)

    def test_stand_motor_pid_holds_against_gravity(self):
        """P=50 在 settle 就摔倒；保持 400/0/20，不加 I。"""
        self.assertAlmostEqual(STAND_CONTROL_P, 400.0)
        self.assertEqual(STAND_CONTROL_I, 0.0)
        self.assertAlmostEqual(STAND_CONTROL_D, 20.0)

    def test_stand_pose_keeps_soles_flat(self):
        """无 ankle_roll：髋外展会把 TPU 底翘成棱，库仑摩擦使不上鞋底面。"""
        pose = stand_base_pose()
        self.assertEqual(pose["left_hip_roll"], 0.0)
        self.assertEqual(pose["right_hip_roll"], 0.0)
        for side in ("left", "right"):
            residual = (
                pose[f"{side}_hip_pitch"]
                + pose[f"{side}_knee_pitch"]
                + pose[f"{side}_ankle_pitch"]
            )
            self.assertAlmostEqual(residual, 0.0, places=6)

    def test_flat_sole_ankles_corrects_gravity_sag(self):
        """Webots 实测髋/膝到不了指令角；踝必须跟实测走，否则脚底剩约 -6°。"""
        measured = stand_base_pose()
        measured["left_hip_pitch"] = -14.5
        measured["left_knee_pitch"] = 22.6
        measured["right_hip_pitch"] = -15.4
        measured["right_knee_pitch"] = 23.8
        fixed = flat_sole_ankles(measured)
        for side in ("left", "right"):
            residual = (
                measured[f"{side}_hip_pitch"]
                + measured[f"{side}_knee_pitch"]
                + fixed[f"{side}_ankle_pitch"]
            )
            self.assertAlmostEqual(residual, 0.0, places=6)


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


class ComHoldOffsetTests(unittest.TestCase):
    """质心相对脚心，不用 IMU。仿真里 IMU 后仰、质心却在脚前。"""

    def test_centered_com_adds_no_offset(self):
        off = com_hold_offsets([0.03, 0.0, 0.24], [[0.03, 0.04, 0.0], [0.03, -0.04, 0.0]])
        self.assertEqual(off["left_ankle_pitch"], 0.0)
        self.assertEqual(off["right_ankle_pitch"], 0.0)
        self.assertEqual(off["left_hip_roll"], 0.0)
        self.assertEqual(off["right_hip_roll"], 0.0)

    def test_com_ahead_of_feet_plantarflexes_both_ankles(self):
        """质心在脚前 → 踝负向（脚尖压下）把质心往回拉。"""
        off = com_hold_offsets(
            [0.05, 0.0, 0.24],
            [[0.03, 0.04, 0.0], [0.03, -0.04, 0.0]],
        )
        self.assertLess(off["left_ankle_pitch"], 0.0)
        self.assertEqual(off["left_ankle_pitch"], off["right_ankle_pitch"])

    def test_com_to_plus_y_does_not_abduct_hips(self):
        """髋 roll 会把 TPU 底翘成棱。默认 kp_y=0。"""
        off = com_hold_offsets(
            [0.03, 0.03, 0.24],
            [[0.03, 0.04, 0.0], [0.03, -0.04, 0.0]],
        )
        self.assertEqual(off.get("left_hip_roll", 0.0), 0.0)
        self.assertEqual(off.get("right_hip_roll", 0.0), 0.0)

    def test_missing_contacts_are_noop(self):
        off = com_hold_offsets([0.1, 0.0, 0.24], [])
        self.assertEqual(off, {})


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

    def test_xy_slide_fails(self):
        zs = [0.20] * 12
        zeros = [0.0] * 12
        xy = [[0.0, 0.0], *[ [0.04 * i, 0.0] for i in range(1, 12) ]]
        result = evaluate_stand(zs, zeros, zeros, xy_m=xy, min_samples=10, xy_max_m=0.05)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "xy_drift")

    def test_xy_hold_passes(self):
        zs = [0.20] * 12
        zeros = [0.0] * 12
        xy = [[0.001 * i, 0.0] for i in range(12)]
        result = evaluate_stand(zs, zeros, zeros, xy_m=xy, min_samples=10, xy_max_m=0.05)
        self.assertTrue(result["ok"])
