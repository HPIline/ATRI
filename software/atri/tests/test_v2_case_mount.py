"""Mechanical regressions require the repository CadQuery environment."""
import unittest
try:
    import cadquery
except ImportError:
    cadquery=None


@unittest.skipUnless(cadquery,'requires .venv-cad')
class CaseMountTests(unittest.TestCase):
    def test_pelvis_fixed_frame_uses_case_clamp_not_passive_disc(self):
        from v2.pelvis_cad import build_pelvis_items
        items=build_pelvis_items()
        fixed=[i for i in items if i['link']=='pelvis']
        self.assertFalse(any(i['name'].startswith('pelvis-mount-screw') for i in fixed))
        self.assertEqual(len([i for i in fixed if i['name'].endswith('jaw-front')]),3)

    def test_clamp_solids_do_not_penetrate_case_or_output_disc(self):
        from v2.case_mount import build_case_clamp
        from v2.cad_parts import sts3215_components,c018_accessories
        obstacles=[sts3215_components()['body'].val()]+[p.val() for p in c018_accessories().values()]
        for item in build_case_clamp('test','pelvis'):
            solid=item['wp'].val()
            self.assertTrue(solid.isValid(),item['name'])
            for obstacle in obstacles:
                self.assertLess(solid.intersect(obstacle).Volume(),1e-6,item['name'])
