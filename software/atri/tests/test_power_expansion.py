import unittest
from design.v2.power_expansion import candidate

class PowerExpansionTest(unittest.TestCase):
    def test_never_invents_unselected_pack(self):
        c = candidate()
        self.assertIsNone(c["secondary_pack"])
        self.assertIsNone(c["secondary_envelope_mm"])
        self.assertIn("ideal-diode", c["architecture"])

if __name__ == "__main__": unittest.main()
