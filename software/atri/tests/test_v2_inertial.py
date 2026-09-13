"""连杆惯量：舵机 + 电子件点质量 + 脚底板，不是称重、也不是 44 mm 实心脚。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "design"))

from v2 import inertial as I  # noqa: E402
from v2 import profile as P  # noqa: E402
from v2.urdf import _link_box_m  # noqa: E402
from v2.assembly3d import kinematic_tree  # noqa: E402


class InertialCompositeTests(unittest.TestCase):
    def setUp(self):
        tree = kinematic_tree()
        boxes = {lk["name"]: _link_box_m(lk["name"]) for lk in tree["links"]}
        self.props = I.robot_inertials(boxes, tree)

    def test_twenty_servos_are_on_joint_links(self):
        servo_g = sum(p["breakdown_g"]["servos"] for p in self.props.values())
        self.assertAlmostEqual(servo_g, 20 * P.SERVO["mass_g"], places=3)

    def test_battery_and_pi_sit_on_torso(self):
        torso = self.props["torso"]
        self.assertGreater(torso["breakdown_g"]["electronics"], 200.0)
        cx, cy, cz = torso["com_m"]
        self.assertGreater(abs(cx) + abs(cy) + abs(cz), 0.01)

    def test_pelvis_has_no_servo(self):
        self.assertEqual(self.props["pelvis"]["breakdown_g"]["servos"], 0.0)

    def test_inertia_principals_positive(self):
        for name, p in self.props.items():
            self.assertTrue(I.principal_positive(p["inertia"]), name)
            self.assertGreater(p["inertia"][2], 1e-8, name)

    def test_total_mass_is_purchased_plus_structure_budget(self):
        total = sum(p["mass_kg"] for p in self.props.values())
        expect = (
            I.remaining_structure_g()
            + 2 * I.foot_plate_g()
            + 2 * I.foot_tpu_g()
            + 20 * P.SERVO["mass_g"]
            + P.ELECTRONICS["battery"]["mass_g"]
            + P.ELECTRONICS["sbc"]["mass_g"]
        ) / 1000.0
        self.assertAlmostEqual(total, expect, places=4)
        self.assertGreater(total, 2.2)
        self.assertLess(total, 2.6)

    def test_foot_com_is_below_ankle_not_in_the_44mm_box_center(self):
        """TPU + 2 mm 铝板在鞋底，质心必须低于踝。"""
        for name in ("left_foot", "right_foot"):
            cz = self.props[name]["com_m"][2]
            self.assertLess(cz, -0.02, name)
            self.assertGreater(cz, -P.K["foot_to_ankle_z"] / 1000.0, name)
            self.assertAlmostEqual(
                self.props[name]["breakdown_g"]["foot"],
                I.foot_plate_g() + I.foot_tpu_g(),
                places=2,
            )

    def test_thigh_structure_com_is_halfway_to_knee(self):
        cz = self.props["left_thigh"]["com_m"][2]
        self.assertLess(cz, -0.01)
        self.assertGreater(cz, -P.K["thigh"] / 1000.0)

    def test_urdf_writes_inertial_origin(self):
        from v2.urdf import build_urdf

        xml = build_urdf()
        self.assertIn("<inertial>", xml)
        self.assertNotIn('origin xyz="0 0 0" rpy="0 0 0"/>\n      <mass', xml.split("<link name=\"torso\">", 1)[1][:800])
        torso = xml.split('<link name="torso">', 1)[1].split("</link>", 1)[0]
        self.assertIn("<inertial>", torso)
        self.assertNotIn('<origin xyz="0 0 0"', torso[torso.find("<inertial>"):])
