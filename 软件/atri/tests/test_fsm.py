import unittest

from atri.fsm import FSMError, FSMState, TaskFSM


class TestFSM(unittest.TestCase):
    def test_happy_path(self):
        fsm = TaskFSM(verbose=False)
        result = fsm.run(lambda: None, lambda: "done")
        self.assertTrue(result["ok"])
        self.assertEqual(result["history"], ["STANDBY", "ENTERING", "EXECUTING", "FEEDBACK", "DONE"])

    def test_error_path(self):
        fsm = TaskFSM(verbose=False)
        def boom():
            raise RuntimeError("boom")
        result = fsm.run(lambda: None, boom)
        self.assertFalse(result["ok"])
        self.assertIn("boom", result["error"])
        self.assertEqual(result["history"][-1], "ERROR")

    def test_illegal_transition(self):
        fsm = TaskFSM(verbose=False)
        with self.assertRaises(FSMError):
            fsm.transition(FSMState.DONE)


if __name__ == "__main__":
    unittest.main()
