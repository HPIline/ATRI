import unittest

from atri.optional_cadquery import skip_without_cadquery


@skip_without_cadquery
class BatteryMountTests(unittest.TestCase):
    def test_supports_and_straps_do_not_penetrate_battery(self):
        from v2.battery_mount import build_battery_mount
        from v2.electronics_cad import build_electronics
        battery=next(i['wp'].val() for i in build_electronics() if i['name']=='battery')
        for item in build_battery_mount():
            with self.subTest(part=item['name']):
                shape=item['wp'].val()
                self.assertTrue(shape.isValid())
                self.assertEqual(len(shape.Solids()),1)
                self.assertLess(shape.intersect(battery).Volume(),1e-6)

    def test_positive_pitch_with_roll_extremes_clears_fixed_clamps(self):
        from v2.battery_mount import build_battery_mount
        from v2.pelvis_cad import build_pelvis_items
        from v2.electronics_cad import build_electronics
        from v2.cad_audit import intersections
        parts=build_pelvis_items()+build_battery_mount()
        parts += [i for i in build_electronics() if i['name']=='battery']
        for roll in (-10,0,10):
            angles=[0]*20;angles[0]=roll;angles[1]=15
            with self.subTest(roll=roll):self.assertEqual(intersections(parts,angles)['intersections'],[])
