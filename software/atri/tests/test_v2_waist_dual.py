"""Rear support topology and real connection stack checks, not a strength certificate."""
import unittest
try:
 import cadquery as cq
except ImportError:
 cq=None

@unittest.skipIf(cq is None, 'requires repository .venv-cad')
class WaistDualTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  from v2.waist_dual_cad import build_waist_dual_items
  cls.items=build_waist_dual_items();cls.parts={x['name']:x for x in cls.items}
 def test_single_connected_angle_and_correct_moving_link(self):
  for p in self.items:
   self.assertTrue(p['wp'].val().isValid(),p['name'])
   self.assertEqual(len(p['wp'].val().Solids()),1,p['name'])
   self.assertEqual(p['link'],'trunk_roll_link')
  self.assertEqual({p['replaces'] for p in self.items if 'replaces' in p},{'case-trunk-pitch-bolt-0','case-trunk-pitch-nut-0'})
 def test_rear_disc_stack_is_contiguous(self):
  from v2.cad_parts import c018_accessories,orient_y_to_axis
  disc=orient_y_to_axis(c018_accessories()['passive'],(1,0,0)).val()
  angle=self.parts['waist-dual-rear-angle']['wp'].val()
  for y in (-4.95,4.95):
   for z in (-4.95,4.95):
    a=self.parts[f'waist-dual-pcd-spacer-{y}-{z}-0']['wp'].val()
    b=self.parts[f'waist-dual-pcd-spacer-{y}-{z}-1']['wp'].val()
    self.assertLess(angle.distance(a),1e-6)
    self.assertLess(a.distance(b),1e-6)
    self.assertLess(b.distance(disc),1e-6)
 def test_through_bolt_projects_beyond_relocated_nut(self):
  bolt=self.parts['waist-dual-clamp-replacement-bolt']['wp'].val().BoundingBox()
  nut=self.parts['waist-dual-clamp-replacement-nut']['wp'].val().BoundingBox()
  self.assertGreater(nut.ymin-bolt.ymin,.5)
  self.assertLess(nut.ymin-bolt.ymin,2.)
  angle=self.parts['waist-dual-rear-angle']['wp'].val()
  self.assertLess(angle.distance(self.parts['waist-dual-clamp-replacement-nut']['wp'].val()),1e-6)
