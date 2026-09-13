import unittest

from atri.optional_cadquery import HAS_CADQUERY, skip_without_cadquery

if HAS_CADQUERY:
    from v2.cad_parts import sts3215_components
    from v2.profile import PELVIS


@skip_without_cadquery
class NeckTests(unittest.TestCase):
    def test_neck_mount_is_valid_and_clears_fixed_pitch_case(self):
        from v2.neck_cad import build_neck_items
        body=sts3215_components()['body'].translate((0,0,PELVIS['head_pitch_z_mm'])).val()
        for part in build_neck_items():
            with self.subTest(part=part['name']):
                self.assertTrue(part['wp'].val().isValid())
                self.assertEqual(len(part['wp'].val().Solids()),1)
                self.assertLess(part['wp'].val().intersect(body).Volume(),1e-6)
