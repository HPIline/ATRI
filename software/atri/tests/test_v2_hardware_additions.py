import unittest
from v2.sensor_power_reservation import reservations
class HardwareAdditionTests(unittest.TestCase):
 def test_additions_are_explicit_reservations(self):
  r=reservations();self.assertFalse(r['battery_expansion']['integrated_cad']);self.assertEqual(r['vl53l1x']['pcb_mm'],(20.,24.));self.assertFalse(r['gripper']['active_sync']);self.assertTrue(r['audio']['mono_speaker'])
