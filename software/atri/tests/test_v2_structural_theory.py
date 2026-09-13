import unittest
from v2.structural_theory import rectangular_beam, friction_grip

class TheoryTests(unittest.TestCase):
    def test_reference_cantilever(self):
        r=rectangular_beam(force_n=10,length_mm=100,width_mm=10,thickness_mm=2,e_mpa=70000)
        self.assertAlmostEqual(r['stress_mpa'],150.)
        self.assertAlmostEqual(r['deflection_mm'],50/7)
    def test_thickness_scaling(self):
        a=rectangular_beam(10,100,10,2,70000)
        b=rectangular_beam(10,100,10,4,70000)
        self.assertAlmostEqual(a['stress_mpa']/b['stress_mpa'],4)
        self.assertAlmostEqual(a['deflection_mm']/b['deflection_mm'],8)
    def test_grip_requires_two_contacts_and_friction(self):
        r=friction_grip(.1,.3,2,38)
        self.assertAlmostEqual(r['normal_per_jaw_n'],3.27)
        self.assertAlmostEqual(r['torque_nm'],.12426)
    def test_zero_dimensions_rejected(self):
        with self.assertRaises(ValueError):rectangular_beam(1,1,0,1,70000)

class GravityMomentTests(unittest.TestCase):
    def test_known_lever_and_units(self):
        from v2.arm_load_audit import point_gravity_moment
        self.assertAlmostEqual(point_gravity_moment((0,0,0),(0,1,0),(100,0,0),100),.0981)
        self.assertAlmostEqual(point_gravity_moment((0,0,0),(1,0,0),(0,100,0),100),-.0981)
    def test_yaw_does_not_resist_vertical_gravity(self):
        from v2.arm_load_audit import point_gravity_moment
        self.assertEqual(point_gravity_moment((10,20,30),(0,0,1),(100,100,100),500),0.)
