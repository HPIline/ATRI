"""The rear hip support must have actual spacer seats and through holes."""
import unittest
try:
    import cadquery
except ImportError:
    cadquery = None

@unittest.skipIf(cadquery is None, 'requires repository .venv-cad')
class HipDualSeatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from v2.hip_dual_cad import build_hip_dual_items
        cls.parts = build_hip_dual_items()

    def test_spacers_seat_without_cutting_through_cheek(self):
        from v2.hip_dual_cad import cyl, D, C, K
        for side in ('left', 'right'):
            angle = next(p['wp'] for p in self.parts if p['name'] == f'hip-dual-{side}-rear-angle')
            self.assertTrue(angle.val().isValid())
            self.assertEqual(len(angle.solids().vals()), 1)
            for k, z in enumerate(C['bolt_z_mm']):
                spacer = next(p['wp'] for p in self.parts if p['name'] == f'hip-dual-{side}-case-spacer-{k}')
                self.assertLess(angle.intersect(spacer).val().Volume(), 1e-6)
                pos = (C['bolt_x_mm'], D['side_outer_y_mm'], -K['hip_stack_z'] + z)
                bearing = cyl(3.5, D['plate_t_mm'], 'y', pos).cut(cyl(1.6, D['plate_t_mm'], 'y', pos))
                self.assertAlmostEqual(angle.intersect(bearing).val().Volume(), bearing.val().Volume(), places=5)

if __name__ == '__main__':
    unittest.main()
