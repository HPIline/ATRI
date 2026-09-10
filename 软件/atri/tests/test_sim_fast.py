import unittest

from atri.sim import main


class TestSimFast(unittest.TestCase):
    def test_fast_demo_passes(self):
        self.assertEqual(main(["--fast"]), 0)


if __name__ == "__main__":
    unittest.main()
