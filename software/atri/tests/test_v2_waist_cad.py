"""Waist stock-angle geometry regressions, not structural certification."""
import unittest

from atri.optional_cadquery import HAS_CADQUERY, skip_without_cadquery

if HAS_CADQUERY:
    from v2.pelvis_cad import build_pelvis_items, cyl
    from v2.profile import PELVIS as P, CASE_MOUNT as C
    from v2.assembly3d import kinematic_tree
    from v2.cad_audit import intersections


@skip_without_cadquery
class WaistCadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.items=build_pelvis_items()
        cls.part=next(i for i in cls.items if i['name']=='pelvis-output-adapter-trunk')

    def test_trunk_is_continuous_and_keeps_stock_heel(self):
        s=self.part['wp'].val()
        self.assertTrue(s.isValid())
        self.assertEqual(len(s.Solids()),1)
        heel=P['front_horn_inner_mm']+P['horn_t_mm']
        self.assertGreaterEqual(s.BoundingBox().xmin,heel-1e-6)
        self.assertTrue(self.part['side_flat'].val().isValid())

    def test_horn_and_clamp_holes_remain_open(self):
        s=self.part['wp'].val();heel=P['front_horn_inner_mm']+P['horn_t_mm']
        for y,z in ((-4.95,-4.95),(-4.95,4.95),(4.95,-4.95),(4.95,4.95)):
            probe=cyl(1.49,P['adapter_t_mm']+2,'x',(heel-1,y,z))
            self.assertLess(s.intersect(probe.val()).Volume(),1e-6)
        for z in C['bolt_z_mm']:
            probe=cyl(1.49,P['adapter_t_mm']+2,'y',(-C['bolt_x_mm'],C['front_face_mm']-1,P['trunk_pitch_offset_mm']+z))
            self.assertLess(s.intersect(probe.val()).Volume(),1e-6)

    def test_pelvis_sweeps_clear_widened_trunk(self):
        tree=kinematic_tree()
        poses=[{}, {'trunk_roll':-10},{'trunk_roll':10},{'left_hip_roll':25},{'right_hip_roll':-25},
               {'trunk_roll':-10,'left_hip_roll':25,'right_hip_roll':-25},
               {'trunk_roll':10,'left_hip_roll':25,'right_hip_roll':-25}]
        for pose in poses:
            with self.subTest(pose=pose):
                report=intersections(self.items,[pose.get(j['name'],0) for j in tree['joints']])
                self.assertEqual(report['intersections'],[])
