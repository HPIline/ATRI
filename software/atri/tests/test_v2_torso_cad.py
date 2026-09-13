import unittest

from atri.optional_cadquery import HAS_CADQUERY, skip_without_cadquery

if HAS_CADQUERY:
    from v2.cad_parts import sts3215_components
    from v2.profile import CAD_INTERFACE


@skip_without_cadquery
class TorsoTests(unittest.TestCase):
    def test_torso_solids_clear_trunk_pitch_housing(self):
        from v2.torso_cad import build_torso_items
        body=sts3215_components()['body'].rotate((0,0,0),(0,1,0),CAD_INTERFACE['housing_clock_deg']['trunk_pitch']).val()
        for p in build_torso_items():
            if p['kind']=='fastener':continue
            with self.subTest(part=p['name']):
                self.assertTrue(p['wp'].val().isValid())
                self.assertLess(p['wp'].val().intersect(body).Volume(),1e-6)
