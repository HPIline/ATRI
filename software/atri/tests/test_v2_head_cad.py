"""Physical head interfaces; run with the repository CadQuery environment."""
import unittest

from atri.optional_cadquery import HAS_CADQUERY, skip_without_cadquery

if HAS_CADQUERY:
    from v2.cad_parts import sts3215_components
    from v2.head_cad import build_head_items
    from v2.electronics_cad import build_electronics
    from v2.pelvis_cad import cyl


@skip_without_cadquery
class HeadAssemblyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parts = build_head_items() + [p for p in build_electronics() if p['link'] == 'head']
        cls.body = sts3215_components()['body'].union(
            cyl(3, 4.1, 'y', (0, -18.5, 0))).val()

    def test_head_pitch_full_range_clears_case(self):
        for angle in range(-45, 46, 5):
            for part in self.parts:
                with self.subTest(angle=angle, part=part['name']):
                    moved = part['wp'].rotate((0, 0, 0), (0, 1, 0), angle).val()
                    self.assertLess(moved.intersect(self.body).Volume(), 1e-6)

    def test_printed_halves_are_individual_valid_solids(self):
        shells = [p for p in self.parts if p['kind'] == 'petg']
        self.assertEqual(len(shells), 2)
        for shell in shells:
            with self.subTest(part=shell['name']):
                self.assertEqual(len(shell['wp'].solids().vals()), 1)
                self.assertTrue(shell['wp'].val().isValid())
        self.assertLess(shells[0]['wp'].val().intersect(shells[1]['wp'].val()).Volume(), 1e-6)

    def test_closure_inserts_have_axial_retention(self):
        rear = next(p['wp'].val() for p in self.parts if p['name'] == 'cover-head-b')
        for part in self.parts:
            if part['name'].startswith('head-closure-pillar-'):
                with self.subTest(part=part['name']):
                    pulled = part['wp'].translate((.4, 0, 0)).val()
                    self.assertGreater(pulled.intersect(rear).Volume(), .1)

    def test_local_assembly_has_no_unintended_intersections(self):
        for index, part in enumerate(self.parts):
            for other in self.parts[index + 1:]:
                # Male/female nominal threads deliberately overlap; actual
                # helix geometry is not present in the purchased envelopes.
                if part['kind'] in ('fastener', 'standoff') and other['kind'] in ('fastener', 'standoff'):
                    continue
                with self.subTest(a=part['name'], b=other['name']):
                    volume = part['wp'].val().intersect(other['wp'].val()).Volume()
                    self.assertLess(volume, 1e-6)


if __name__ == '__main__':
    unittest.main()
