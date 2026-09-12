"""真机接口契约与 bring-up 流程的回归测试。

守住的四件事：
  1. 角度 ↔ 脉冲换算与限位口径（上位机与固件共用的那一套公式）
  2. 关节表完整性（22 个、ID 0..21、分支齐全）
  3. ServoBus 的批量写/安全/遥测语义（Mock 也要满足，否则真机实现会漏项）
  4. 标定文件的写出与回读（装配后必须能回填 sign / zero_pulse）
"""
import json
import tempfile
import unittest
from pathlib import Path

from atri import bringup
from atri.cerebellum import Cerebellum, MockServoBus
from atri.config import (JOINTS, MID_PULSE, PULSE_PER_DEG, deg_to_pulse,
                         joint_table, load_calibration, pulse_limits,
                         pulse_to_deg)


class TestAnglePulseContract(unittest.TestCase):
    """角度 ↔ 脉冲：这是上下位机唯一的换算口径，错了就是"两条腿反着走"。"""

    def test_middle_is_2048(self):
        for name in JOINTS:
            self.assertEqual(deg_to_pulse(name, 0.0), MID_PULSE)

    def test_round_trip(self):
        for name in JOINTS:
            for deg in (0.0, 30.0, -30.0, 45.0):
                pulse = deg_to_pulse(name, deg)
                back = pulse_to_deg(name, pulse)
                self.assertAlmostEqual(back, deg, delta=360.0 / 4096.0)

    def test_quarter_turn(self):
        # 90° 应恰好是 1/4 行程（4096/4 = 1024 个脉冲）
        self.assertEqual(abs(deg_to_pulse("head_yaw", 90.0) - MID_PULSE),
                         int(round(90.0 * PULSE_PER_DEG)))

    def test_sign_flips_direction(self):
        name = "head_yaw"
        old = JOINTS[name]["sign"]
        try:
            JOINTS[name]["sign"] = -1
            self.assertLess(deg_to_pulse(name, 30.0), MID_PULSE)
            self.assertGreater(deg_to_pulse(name, -30.0), MID_PULSE)
        finally:
            JOINTS[name]["sign"] = old

    def test_pulse_limits_inside_register_range(self):
        for name in JOINTS:
            lo, hi = pulse_limits(name)
            self.assertGreaterEqual(lo, 0)
            self.assertLessEqual(hi, 4095)
            self.assertLess(lo, hi)
            # 限位寄存器必须比软件限位**更宽**（否则软件抖一下就被舵机截断），
            # 但仍落在 0–4095 之内。
            slo, shi = JOINTS[name]["limit_deg"]
            self.assertLessEqual(lo, deg_to_pulse(name, slo))
            self.assertGreaterEqual(hi, deg_to_pulse(name, shi))


class TestJointTable(unittest.TestCase):

    def test_ids_contiguous(self):
        table = joint_table()
        self.assertEqual(len(table), 22)
        self.assertEqual(sorted(r["id"] for r in table.values()), list(range(22)))

    def test_every_joint_has_branch(self):
        for name, row in joint_table().items():
            self.assertTrue(row["branch"], f"{name} 缺分支标识（线束需要）")
            self.assertIn(row["sign"], (-1, 1))


class TestServoBusSemantics(unittest.TestCase):
    """真机实现必须满足这些语义；Mock 先替它把关。"""

    def setUp(self):
        self.bus = MockServoBus()

    def test_sync_write_batches(self):
        self.bus.sync_write({0: 5.0, 1: -5.0})
        self.assertEqual(self.bus.read_angle(0), 5.0)
        self.assertEqual(self.bus.read_angle(1), -5.0)

    def test_cerebellum_uses_sync_write(self):
        cere = Cerebellum(servo_bus=self.bus, sleeper=lambda _dt: None)
        applied = cere.set_pose({"head_yaw": 12.0, "left_knee_pitch": 30.0})
        self.assertEqual(applied["head_yaw"], 12.0)
        self.assertEqual(self.bus.read_angle(JOINTS["head_yaw"]["id"]), 12.0)

    def test_relax_turns_torque_off(self):
        cere = Cerebellum(servo_bus=self.bus, sleeper=lambda _dt: None)
        cere.relax()
        self.assertFalse(self.bus.torque_on)

    def test_scan_finds_all(self):
        self.assertEqual(len(self.bus.scan()), 22)

    def test_telemetry_shape(self):
        tele = self.bus.read_telemetry(0)
        for key in ("pos_deg", "load_pct", "voltage_v", "temp_c", "current_a",
                    "moving"):
            self.assertIn(key, tele)


class TestBringupFlow(unittest.TestCase):

    def setUp(self):
        self.bus = MockServoBus()

    def test_scan_matches_table(self):
        rep = bringup.scan_and_check(self.bus)
        self.assertEqual(rep["missing"], [])
        self.assertEqual(rep["extra"], [])

    def test_limits_written_for_all(self):
        written = bringup.write_all_limits(self.bus)
        self.assertEqual(len(written), 22)
        self.assertEqual(len(self.bus.limits), 22)

    def test_jog_records_samples(self):
        rep = bringup.jog_test(self.bus, "head_yaw", sleeper=lambda _dt: None)
        self.assertEqual(len(rep["samples"]), len(bringup.JOG_SEQUENCE_DEG))
        self.assertEqual(self.bus.read_angle(0), 0.0)   # 结束后回中位

    def test_calibration_round_trip(self):
        name = "left_knee_pitch"
        old = (JOINTS[name]["sign"], JOINTS[name]["zero_pulse"])
        try:
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "calibration.json"
                bringup.write_calibration({name: {"sign": -1, "zero_pulse": 2010}}, path)
                self.assertTrue(path.exists())
                data = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(data["joints"][name]["zero_pulse"], 2010)
                # 回读必须真的改到 JOINTS 上（否则标定等于没做）
                applied = load_calibration(path)
                self.assertEqual(applied[name]["sign"], -1)
                self.assertEqual(JOINTS[name]["zero_pulse"], 2010)
                self.assertEqual(deg_to_pulse(name, 0.0), 2010)
        finally:
            JOINTS[name]["sign"], JOINTS[name]["zero_pulse"] = old

    def test_missing_calibration_is_not_an_error(self):
        self.assertEqual(load_calibration(Path("/nonexistent/cal.json")), {})


if __name__ == "__main__":
    unittest.main()
