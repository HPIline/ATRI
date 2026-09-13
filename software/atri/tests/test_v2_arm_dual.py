"""Mechanical checks for the passive-side arm support candidate."""
import unittest

from atri.optional_cadquery import HAS_CADQUERY, skip_without_cadquery

if HAS_CADQUERY:
    from v2.arm_dual_cad import build_arm_dual_items
    from v2.assembly3d import kinematic_tree, fk
    from test_v2_arm_cad import collisions


@skip_without_cadquery
class ArmDualTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parts=build_arm_dual_items()

    def test_each_arm_stage_has_driven_and_passive_cheeks(self):
        parts={p['name']:p for p in self.parts}
        for side in ('left','right'):
            for segment in ('shoulder','upper','fore'):
                a=parts[f'arm-{side}-{segment}-angle']
                b=parts[f'arm-{side}-{segment}-rear-angle']
                self.assertEqual(a['link'],b['link'])
                self.assertTrue(b['wp'].val().isValid())
                self.assertEqual(len(b['wp'].solids().vals()),1)

    def test_zero_assembly_has_no_positive_volume_collision(self):
        self.assertEqual(collisions(self.parts,fk(kinematic_tree())),[])

    def test_rear_disc_thread_stack(self):
        from v2.profile import ARM_DUAL as p, SERVO
        engagement=p['rear_horn_bolt_mm']-p['rear_head_washer_mm']-p['rear_plate_t_mm']-sum(p['rear_disc_spacer_stack_mm'])
        self.assertAlmostEqual(engagement,p['rear_horn_thread_engagement_mm'])
        self.assertGreaterEqual(engagement,2.)
        self.assertLessEqual(engagement,SERVO['rear_disc_flange_t_mm'])

    def test_folded_arm_corners(self):
        tree=kinematic_tree()
        for side,roll in [('left',90.),('right',-90.)]:
            local=[p for p in self.parts if side in p['name']]
            for pitch in (-90.,0.,90.):
                for grip in (0.,60.):
                    angles=[0.]*len(tree['joints'])
                    for suffix,value in [('shoulder_pitch',pitch),('shoulder_roll',roll),('elbow_pitch',-120.),('gripper',grip)]:
                        k=next(i for i,j in enumerate(tree['joints']) if j['name']==side+'_'+suffix)
                        angles[k]=value
                    with self.subTest(side=side,pitch=pitch,grip=grip):
                        self.assertEqual(collisions(local,fk(tree,angles),moving_only=True),[])
