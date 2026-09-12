"""标称位移模型测试。

这些用例锁的是**模型的计算规则**，不是机器人的真实行为——模型本身标注为
``nominal-uncalibrated``，任何"走多远"的结论都必须带着这个前提读。
"""
from __future__ import annotations

import json
import math
import tempfile
import unittest
from pathlib import Path

from atri.odometry import (
    STATUS_CALIBRATED,
    STATUS_NOMINAL,
    NominalOdometry,
    Pose,
    endpoint_error_cm,
    path_length_cm,
)
from atri.path_plan import PathError, build_path


class TestNominalOdometry(unittest.TestCase):
    def test_straight_walk_moves_along_x(self):
        odo = NominalOdometry(step_length_cm=2.0)
        trace = odo.simulate(build_path([{"action": "walk", "steps": 3}]))
        self.assertAlmostEqual(trace.end.x_cm, 6.0, places=6)
        self.assertAlmostEqual(trace.end.y_cm, 0.0, places=6)
        self.assertAlmostEqual(trace.end.heading_deg, 0.0, places=6)

    def test_turn_changes_heading_only(self):
        odo = NominalOdometry()
        trace = odo.simulate(build_path([{"action": "turn", "deg": 90}]))
        self.assertAlmostEqual(trace.end.x_cm, 0.0, places=6)
        self.assertAlmostEqual(trace.end.heading_deg, 90.0, places=6)

    def test_walk_after_turn_goes_along_y(self):
        odo = NominalOdometry(step_length_cm=2.0)
        trace = odo.simulate(
            build_path([{"action": "turn", "deg": 90}, {"action": "walk", "steps": 5}])
        )
        self.assertAlmostEqual(trace.end.x_cm, 0.0, places=6)
        self.assertAlmostEqual(trace.end.y_cm, 10.0, places=6)

    def test_closed_square_returns_to_start(self):
        """走一个正方形应回到原点——这是模型自洽性的最小检验。"""
        odo = NominalOdometry(step_length_cm=1.0)
        segments = []
        for _ in range(4):
            segments.append({"action": "walk", "steps": 10})
            segments.append({"action": "turn", "deg": 90})
        trace = odo.simulate(build_path(segments))
        self.assertAlmostEqual(trace.end.x_cm, 0.0, places=6)
        self.assertAlmostEqual(trace.end.y_cm, 0.0, places=6)
        self.assertAlmostEqual(trace.end.heading_deg, 0.0, places=6)

    def test_turn_efficiency_scales_heading(self):
        odo = NominalOdometry(turn_efficiency=0.5)
        trace = odo.simulate(build_path([{"action": "turn", "deg": 90}]))
        self.assertAlmostEqual(trace.end.heading_deg, 45.0, places=6)

    def test_non_movement_action_has_no_displacement_but_is_recorded(self):
        odo = NominalOdometry()
        trace = odo.simulate(build_path([{"action": "dance", "bars": 1}]))
        self.assertEqual(len(trace.segments), 1)
        self.assertAlmostEqual(trace.total_distance_cm, 0.0, places=6)
        self.assertIn("不产生平面位移", trace.segments[0].note)

    def test_status_marks_it_uncalibrated(self):
        """未标定时必须在结果里写明——这些数字不是实测。"""
        trace = NominalOdometry().simulate(build_path([{"action": "walk", "steps": 1}]))
        self.assertEqual(trace.status, STATUS_NOMINAL)
        self.assertFalse(trace.is_calibrated)
        payload = trace.to_dict()
        self.assertFalse(payload["calibrated"])
        self.assertIn("未经实物标定", payload["caveat"])

    def test_path_length_sums_segments(self):
        trace = NominalOdometry(step_length_cm=2.0).simulate(
            build_path([{"action": "walk", "steps": 3}, {"action": "walk", "steps": 2}])
        )
        self.assertAlmostEqual(path_length_cm(trace), 10.0, places=6)

    def test_custom_start_pose(self):
        trace = NominalOdometry(step_length_cm=1.0).simulate(
            build_path([{"action": "walk", "steps": 5}]), start=Pose(x_cm=10.0, y_cm=10.0, heading_deg=180.0)
        )
        self.assertAlmostEqual(trace.end.x_cm, 5.0, places=6)
        self.assertAlmostEqual(trace.end.y_cm, 10.0, places=6)

    def test_rejects_bad_parameters(self):
        for bad in (0.0, -1.0, float("nan")):
            with self.subTest(bad=bad):
                with self.assertRaises(PathError):
                    NominalOdometry(step_length_cm=bad)
        with self.assertRaises(PathError):
            NominalOdometry(turn_efficiency=0.0)


class TestOdometryCalibration(unittest.TestCase):
    def test_missing_calibration_file_falls_back_to_nominal(self):
        odo = NominalOdometry.from_config("/nonexistent/odometry.json")
        self.assertEqual(odo.status, STATUS_NOMINAL)

    def test_calibration_file_switches_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "odometry.json"
            path.write_text(
                json.dumps({"step_length_cm": 1.8, "turn_efficiency": 0.94}), encoding="utf-8"
            )
            odo = NominalOdometry.from_config(path)
        self.assertEqual(odo.status, STATUS_CALIBRATED)
        self.assertAlmostEqual(odo.step_length_cm, 1.8)
        trace = odo.simulate(build_path([{"action": "walk", "steps": 10}]))
        self.assertTrue(trace.is_calibrated)
        self.assertAlmostEqual(trace.end.x_cm, 18.0, places=6)

    def test_corrupt_calibration_file_falls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "odometry.json"
            path.write_text("{not json", encoding="utf-8")
            odo = NominalOdometry.from_config(path)
        self.assertEqual(odo.status, STATUS_NOMINAL)


class TestPoseHelpers(unittest.TestCase):
    def test_endpoint_error(self):
        self.assertAlmostEqual(
            endpoint_error_cm(Pose(0, 0, 0), Pose(3, 4, 0)), 5.0, places=6
        )

    def test_pose_dict_is_rounded(self):
        data = Pose(1.23456, 2.34567, 3.45678).to_dict()
        self.assertEqual(data["x_cm"], 1.235)

    def test_segment_trace_records_heading_change(self):
        trace = NominalOdometry().simulate(
            build_path([{"action": "turn", "deg": 90}, {"action": "turn", "deg": -30}])
        )
        self.assertAlmostEqual(trace.segments[0].heading_change_deg, 90.0, places=6)
        self.assertAlmostEqual(trace.segments[1].heading_change_deg, -30.0, places=6)


if __name__ == "__main__":
    unittest.main()
