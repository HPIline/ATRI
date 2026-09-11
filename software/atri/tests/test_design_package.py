"""设计数据包与仿真链路测试。

覆盖：
  - robot_model.json 自洽性与官方约束
  - URDF 生成正确性与关节同源
  - 舵机非理想特性确实被建模
  - 感知噪声与丢帧确实生效
  - 视觉伺服闭环收敛/振荡/不收敛
  - 域随机化采样范围

运行：
    cd software/atri && python3 -m unittest tests.test_design_package -v
"""
from __future__ import annotations

import json
import math
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
DESIGN = REPO / "design"
sys.path.insert(0, str(DESIGN))
sys.path.insert(0, str(REPO / "software" / "atri"))

from atri.config import JOINTS, GROUP_DOF  # noqa: E402
from atri.cerebellum import ServoBus  # noqa: E402
from realistic_sim import (  # noqa: E402
    NoisyPerception,
    RealisticServoBus,
    load_package,
    sample_randomization,
)
from run_sim import servo_loop  # noqa: E402
import gen_urdf  # noqa: E402


class TestRobotModel(unittest.TestCase):
    def setUp(self) -> None:
        self.model = gen_urdf.load_model()

    def test_has_22_joints(self):
        self.assertEqual(len(self.model["joints"]), 22)

    def test_joint_names_match_software(self):
        model_names = {j["name"] for j in self.model["joints"]}
        self.assertEqual(model_names, set(JOINTS))

    def test_joint_limits_match_software(self):
        for j in self.model["joints"]:
            self.assertEqual(
                list(j["limit_deg"]),
                list(JOINTS[j["name"]]["limit_deg"]),
                f"{j['name']} 限位与软件配置不一致",
            )

    def test_joint_ids_match_software(self):
        for j in self.model["joints"]:
            self.assertEqual(j["id"], JOINTS[j["name"]]["id"])

    def test_validation_passes(self):
        problems = gen_urdf.check(self.model)
        self.assertEqual(problems, [], f"模型校验失败: {problems}")

    def test_mass_sums_to_declared(self):
        total = sum(l["mass_kg"] for l in self.model["links"])
        self.assertAlmostEqual(total, self.model["overall"]["mass_kg"], places=2)

    def test_servo_torque_uses_dual_criteria(self):
        """D-1：扭矩必须双口径——官方额定 0.98（主判据）+ 峰值 1.47（堵转 × 50%）。"""
        sd = self.model["servo_defaults"]
        rated = float(sd.get("rated_torque_nm")
                      or sd.get("continuous_rated_torque_nm"))
        peak = float(sd.get("rated_torque_nm_half_stall_deprecated")
                     or sd.get("peak_torque_nm"))
        self.assertAlmostEqual(rated, 0.98, places=3)
        self.assertAlmostEqual(peak, 1.47, places=3)
        self.assertAlmostEqual(sd["stall_torque_nm"], 2.94, places=3)
        self.assertGreater(peak, rated)
        self.assertTrue(
            "rated_torque_basis" in sd
            or "continuous_rated_torque_basis" in sd)

    def test_components_match_model_servo(self):
        """components.json 的舵机口径必须与 robot_model.json 同源，防止两套判据。"""
        comps = json.loads((DESIGN / "components.json").read_text(encoding="utf-8"))
        servo = next(c for c in comps["components"] if c["role"] == "servo_s")
        sd = self.model["servo_defaults"]
        self.assertEqual(servo["size_mm"], sd["size_mm"])
        self.assertAlmostEqual(servo["mass_g"], sd["mass_g"], places=1)
        spec = servo["spec"]
        rated = float(sd.get("rated_torque_nm")
                      or sd.get("continuous_rated_torque_nm"))
        spec_rated = float(spec.get("rated_torque_nm")
                           or spec.get("continuous_rated_torque_nm"))
        self.assertAlmostEqual(spec_rated, rated, places=3)
        self.assertAlmostEqual(spec["stall_torque_nm"],
                               sd["stall_torque_nm"], places=3)

    def test_structure_mass_matches_cad_measurement(self):
        """D-4：结构件质量与件数以 CAD 实算（81 件 / 1490 g）为事实源。"""
        cad = json.loads(
            (DESIGN / "reference" / "cad_assembly_measurements.json")
            .read_text(encoding="utf-8"))
        self.assertEqual(cad["part_count"], 81)
        self.assertAlmostEqual(self.model["mass_budget"]["structure_g"],
                               cad["structure_total_g"], delta=1.0)
        comps = json.loads((DESIGN / "components.json").read_text(encoding="utf-8"))
        self.assertAlmostEqual(comps["structure_mass_estimate_g"],
                               cad["structure_total_g"], delta=1.0)
        self.assertAlmostEqual(self.model["overall"]["mass_kg"] * 1000.0,
                               cad["total_mass_g"], delta=5.0)

    def test_within_competition_bounds(self):
        o, c = self.model["overall"], self.model["design_constraints"]
        self.assertLessEqual(o["height_mm"], c["competition_max_height_mm"])
        self.assertLessEqual(o["width_mm"], c["competition_max_width_mm"])
        self.assertLessEqual(o["depth_mm"], c["competition_max_depth_mm"])

    def test_dof_requirements(self):
        c = self.model["design_constraints"]
        self.assertGreaterEqual(len(JOINTS), c["competition_min_dof"])
        self.assertGreaterEqual(GROUP_DOF["leg_l"], c["competition_min_leg_dof_per_side"])
        upper = GROUP_DOF["arm_l"] + GROUP_DOF["arm_r"] + GROUP_DOF["trunk"]
        self.assertGreaterEqual(upper, c["competition_min_upper_dof"])

    def test_height_is_geometry_consistent(self):
        """总高必须由关节链几何累加得出，不能是拍脑袋数字。"""
        m = self.model
        by_child = {j["child"]: j for j in m["joints"]}
        links = {l["name"]: l for l in m["links"]}

        def z_path(leaf: str) -> float:
            z, cur = 0.0, leaf
            while cur in by_child:
                j = by_child[cur]
                z += j["origin_xyz_mm"][2]
                cur = j["parent"]
            return z

        top = z_path("head") + links["head"]["geometry"]["size_mm"][2] / 2.0
        bottom = z_path("left_foot") - links["left_foot"]["geometry"]["size_mm"][2] / 2.0
        self.assertAlmostEqual(top - bottom, m["overall"]["height_mm"], delta=1.0)

    def test_base_pose_puts_feet_on_ground(self):
        m = self.model
        by_child = {j["child"]: j for j in m["joints"]}
        links = {l["name"]: l for l in m["links"]}

        def z_path(leaf: str) -> float:
            z, cur = 0.0, leaf
            while cur in by_child:
                j = by_child[cur]
                z += j["origin_xyz_mm"][2]
                cur = j["parent"]
            return z

        bottom = z_path("left_foot") - links["left_foot"]["geometry"]["size_mm"][2] / 2.0
        self.assertAlmostEqual(m["base_pose_mm"][2] + bottom, 0.0, delta=0.5)


class TestUrdf(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.model = gen_urdf.load_model()
        cls.xml = gen_urdf.build_urdf(cls.model)

    def test_is_valid_xml(self):
        root = ET.fromstring(self.xml)
        self.assertEqual(root.tag, "robot")
        self.assertEqual(root.get("name"), "ATRI")

    def test_link_and_joint_counts(self):
        root = ET.fromstring(self.xml)
        self.assertEqual(len(root.findall("link")), len(self.model["links"]))
        self.assertEqual(len(root.findall("joint")), 22)

    def test_every_link_has_inertial(self):
        root = ET.fromstring(self.xml)
        for link in root.findall("link"):
            self.assertIsNotNone(
                link.find("inertial"), f"{link.get('name')} 缺少 inertial"
            )

    def test_limits_converted_to_radians(self):
        root = ET.fromstring(self.xml)
        for joint in root.findall("joint"):
            name = joint.get("name")
            limit = joint.find("limit")
            lo = math.degrees(float(limit.get("lower")))
            hi = math.degrees(float(limit.get("upper")))
            exp_lo, exp_hi = JOINTS[name]["limit_deg"]
            self.assertAlmostEqual(lo, exp_lo, places=3)
            self.assertAlmostEqual(hi, exp_hi, places=3)

    def test_origins_converted_to_metres(self):
        """每段位移应在合理米级范围（不是把 mm 当 m）。"""
        root = ET.fromstring(self.xml)
        for joint in root.findall("joint"):
            xyz = joint.find("origin").get("xyz").split()
            for v in xyz:
                self.assertLess(abs(float(v)), 0.5, "位移量级异常，单位换算可能有误")


class TestRealisticServoBus(unittest.TestCase):
    def test_deadband_rejects_redundant_commands(self):
        bus = RealisticServoBus(seed=1, enable_imperfections=True)
        jid = JOINTS["left_hip_pitch"]["id"]
        for _ in range(20):
            bus.set_angle(jid, 30.0)
            bus.step()
        self.assertGreater(bus.rejected_by_deadband, 0)

    def test_ideal_mode_has_no_deadband(self):
        bus = RealisticServoBus(seed=1, enable_imperfections=False)
        jid = JOINTS["left_hip_pitch"]["id"]
        for _ in range(20):
            bus.set_angle(jid, 30.0)
            bus.step()
        self.assertEqual(bus.rejected_by_deadband, 0)

    def test_slew_rate_limits_motion(self):
        """一步之内不可能瞬间到达大角度目标。"""
        bus = RealisticServoBus(seed=1)
        jid = JOINTS["left_hip_pitch"]["id"]
        bus.set_angle(jid, 60.0)
        bus.step()
        moved = abs(bus.read_angle(jid))
        max_possible = bus.speed_dps * bus.dt_s
        self.assertLessEqual(moved, max_possible + 1e-6)
        self.assertGreater(moved, 0.0)

    def test_control_latency_queues_command(self):
        bus = RealisticServoBus(seed=1)
        jid = JOINTS["left_hip_pitch"]["id"]
        bus.set_angle(jid, 30.0)
        self.assertGreater(len(bus._pending), 0)

    def test_limits_still_enforced(self):
        bus = RealisticServoBus(seed=1)
        jid = JOINTS["head_yaw"]["id"]
        bus.set_angle(jid, 999.0)
        for _ in range(200):
            bus.step()
        self.assertLessEqual(bus.read_angle(jid), 90.0 + 1e-6)

    def test_uses_base_template_method(self):
        """不再覆写 set_angle：限位必须由 ServoBus 模板方法统一钳制。"""
        self.assertNotIn("set_angle", RealisticServoBus.__dict__)
        self.assertIs(RealisticServoBus.set_angle, ServoBus.set_angle)


class TestNoisyPerception(unittest.TestCase):
    def test_nominal_has_noise(self):
        p = NoisyPerception(profile="nominal", seed=1)
        readings = []
        for _ in range(30):
            p.set_ball_position(x_cm=10.0, distance_cm=12.0)
            d = p.detect_ball().data
            if d.get("found", True):
                readings.append(d["x_cm"])
        self.assertGreater(len(readings), 0)
        spread = max(readings) - min(readings)
        self.assertGreater(spread, 0.0, "nominal 档应存在测量噪声")

    def test_ideal_has_low_noise(self):
        p = NoisyPerception(profile="ideal", seed=1)
        readings = []
        for _ in range(30):
            p.set_ball_position(x_cm=10.0, distance_cm=12.0)
            d = p.detect_ball().data
            if d.get("found", True):
                readings.append(d["x_cm"])
        spread = max(readings) - min(readings)
        self.assertLess(spread, 0.5, "ideal 档噪声应极小")

    def test_adversarial_drops_more_than_nominal(self):
        def drops(profile: str) -> int:
            p = NoisyPerception(profile=profile, seed=7)
            for _ in range(300):
                p.set_ball_position(x_cm=5.0, distance_cm=12.0)
                p.detect_ball()
            return p.dropouts

        self.assertGreater(drops("adversarial"), drops("nominal"))

    def test_dropout_reports_not_found(self):
        p = NoisyPerception(profile="adversarial", seed=3)
        p.dropout_rate = 1.0
        p.rng.random = lambda: 0.0  # 强制丢帧
        self.assertFalse(p.detect_ball().data.get("found", True))


class TestServoLoop(unittest.TestCase):
    def test_converges_on_large_offset(self):
        p = NoisyPerception(profile="nominal", seed=20260910)
        r = servo_loop(p, target_x_cm=12.0, seed=20260910)
        self.assertTrue(r["converged"], f"未收敛: {r}")
        self.assertIsNotNone(r["final_error_cm"])
        self.assertLess(abs(r["final_error_cm"]), 1.0)

    def test_error_decreases_over_iterations(self):
        p = NoisyPerception(profile="ideal", seed=5)
        r = servo_loop(p, target_x_cm=20.0, seed=5)
        vals = [v for v in r["history"] if not math.isnan(v)]
        self.assertGreater(len(vals), 2)
        self.assertLess(abs(vals[-1]), abs(vals[0]))

    def test_small_offset_converges_fast(self):
        p = NoisyPerception(profile="ideal", seed=5)
        r = servo_loop(p, target_x_cm=0.5, seed=5)
        self.assertTrue(r["converged"])
        self.assertEqual(r["iterations"], 1)

    def test_reports_not_converged_without_hanging(self):
        """迭代上限必须安全退出并给出原因，不能卡死。"""
        p = NoisyPerception(profile="ideal", seed=5)
        r = servo_loop(p, target_x_cm=100.0, max_iter=3, tol_cm=0.001, seed=5)
        self.assertFalse(r["converged"])
        self.assertEqual(r["reason"], "max_iterations")
        self.assertEqual(r["iterations"], 3)

    def test_handles_target_loss(self):
        p = NoisyPerception(profile="adversarial", seed=11)
        p.dropout_rate = 1.0
        p.rng.random = lambda: 0.0
        r = servo_loop(p, target_x_cm=5.0, seed=11)
        self.assertFalse(r["converged"])
        self.assertEqual(r["reason"], "target_lost")
        self.assertGreater(r["lost_recoveries"], 0)


class TestDomainRandomization(unittest.TestCase):
    def setUp(self) -> None:
        self.spec = load_package("domain_random")

    def test_samples_within_declared_ranges(self):
        import random
        rng = random.Random(1)
        for _ in range(50):
            s = sample_randomization(self.spec, rng)
            for key, item in self.spec["randomization"].items():
                if key not in s:
                    continue
                rng_range = item.get("range")
                if isinstance(rng_range, list) and len(rng_range) == 2:
                    self.assertGreaterEqual(s[key], rng_range[0] - 1e-9)
                    self.assertLessEqual(s[key], rng_range[1] + 1e-9)

    def test_is_reproducible_with_same_seed(self):
        import random
        a = sample_randomization(self.spec, random.Random(42))
        b = sample_randomization(self.spec, random.Random(42))
        self.assertEqual(a, b)

    def test_differs_across_seeds(self):
        import random
        a = sample_randomization(self.spec, random.Random(1))
        b = sample_randomization(self.spec, random.Random(2))
        self.assertNotEqual(a, b)


class TestPackages(unittest.TestCase):
    def test_all_packages_load(self):
        for name in ("servo_spec", "domain_random", "perception_sim",
                     "scenario_set"):
            with self.subTest(package=name):
                data = load_package(name)
                self.assertIn("schema_version", data)

    def test_scenario_set_covers_five_tasks(self):
        sc = load_package("scenario_set")["scenarios"]
        self.assertEqual(len(sc), 5)
        skills = {s["skill"] for s in sc}
        self.assertEqual(skills, {"face", "qr", "carry", "kick", "dance"})

    def test_servo_spec_has_required_fields(self):
        spec = load_package("servo_spec")
        for key in ("deadband_deg", "backlash_deg", "no_load_speed_dps",
                    "control_latency_ms"):
            self.assertIn(key, spec)

    def test_servo_spec_is_marked_provisional(self):
        """参数必须是临时/典型值标注，不能伪装成实测。"""
        spec = load_package("servo_spec")
        self.assertIn("provisional", json.dumps(spec, ensure_ascii=False).lower())


if __name__ == "__main__":
    unittest.main()
