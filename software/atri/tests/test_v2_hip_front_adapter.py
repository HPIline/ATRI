"""Hip front adapter fit and manufacturable template regressions."""
import unittest

from atri.optional_cadquery import HAS_CADQUERY, skip_without_cadquery

if HAS_CADQUERY:
    from v2.pelvis_cad import build_pelvis_items, cyl
    from v2.cad_export import _moved
    from v2.assembly3d import kinematic_tree, fk
    from v2.profile import PELVIS as P, CASE_MOUNT as C


@skip_without_cadquery
class HipFrontAdapterTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.items={p['name']:p for p in build_pelvis_items()}
 def test_connected_positive_solids_and_open_hole_templates(self):
  for side in ('left','right'):
   p=self.items['pelvis-output-adapter-'+side]
   for key in ('wp','side_flat','output_flat'):
    s=p[key].val();self.assertTrue(s.isValid());self.assertEqual(len(s.Solids()),1);self.assertGreater(s.Volume(),0)
   for y,z in ((-4.95,-4.95),(-4.95,4.95),(4.95,-4.95),(4.95,4.95)):
    self.assertLess(p['output_flat'].val().intersect(cyl(1.49,3,'z',(y,z,0)).val()).Volume(),1e-6)
 def test_right_adapter_has_one_mm_static_frame_clearance(self):
  W=fk(kinematic_tree())
  a=self.items['pelvis-output-adapter-right'];b=self.items['pelvis-open-frame']
  self.assertGreaterEqual(_moved(a['wp'],W[a['link']]).val().distance(_moved(b['wp'],W[b['link']]).val()),1.)
