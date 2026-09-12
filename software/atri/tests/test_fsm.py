import threading
import time
import unittest

from atri.fsm import FSMError, FSMState, TaskFSM, TaskTimeoutError


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
        self.assertIn("RuntimeError", result["error"])
        self.assertIn("boom", result["error"])
        self.assertEqual(result["history"][-1], "ERROR")

    def test_illegal_transition(self):
        fsm = TaskFSM(verbose=False)
        with self.assertRaises(FSMError):
            fsm.transition(FSMState.DONE)

    def test_run_does_not_raise_for_reuse(self):
        fsm = TaskFSM(verbose=False)
        self.assertTrue(fsm.run(lambda: None, lambda: "first")["ok"])
        second = fsm.run(lambda: None, lambda: "second")
        self.assertTrue(second["ok"])
        self.assertEqual(second["history"][0], "STANDBY")

    def test_run_after_error_resets(self):
        fsm = TaskFSM(verbose=False)

        def boom():
            raise RuntimeError("boom")

        self.assertFalse(fsm.run(lambda: None, boom)["ok"])
        self.assertTrue(fsm.run(lambda: None, lambda: "recovered")["ok"])

    def test_reset_clears_state(self):
        fsm = TaskFSM(verbose=False)
        fsm.run(lambda: None, lambda: "done")
        self.assertEqual(fsm.reset(), FSMState.STANDBY)
        self.assertEqual(fsm.history, [FSMState.STANDBY])

    def test_timeout_interrupts_and_calls_on_timeout(self):
        fsm = TaskFSM(verbose=False)
        resets = []
        started = time.monotonic()
        result = fsm.run(
            lambda: None,
            lambda: time.sleep(0.25),
            timeout_s=0.05,
            on_timeout=lambda: resets.append(True),
        )
        self.assertFalse(result["ok"])
        self.assertIn("TaskTimeoutError", result["error"])
        self.assertEqual(result["history"][-1], "ERROR")
        self.assertEqual(resets, [True])
        self.assertLess(time.monotonic() - started, 1.0)

    def test_timeout_reset_runs_on_main_thread_exactly_once(self):
        """定时器线程只置位；复位必须回到主线程，且只执行一次。"""
        fsm = TaskFSM(verbose=False)
        resets = []
        result = fsm.run(
            lambda: None,
            lambda: time.sleep(0.15),
            timeout_s=0.02,
            on_timeout=lambda: resets.append(threading.current_thread().name),
        )
        self.assertFalse(result["ok"])
        self.assertIn("TaskTimeoutError", result["error"])
        self.assertEqual(resets, ["MainThread"])

    def test_timeout_sets_abort_event(self):
        fsm = TaskFSM(verbose=False)
        seen = {}

        def execute():
            time.sleep(0.1)
            seen["set"] = fsm.abort_event.is_set()
            return "late"

        result = fsm.run(lambda: None, execute, timeout_s=0.02)
        self.assertFalse(result["ok"])
        self.assertTrue(seen.get("set"), "超时后 abort_event 应已置位")

    def test_timeout_error_from_execute_triggers_reset(self):
        fsm = TaskFSM(verbose=False)
        resets = []

        def execute():
            raise TaskTimeoutError("预算耗尽")

        result = fsm.run(
            lambda: None, execute, timeout_s=5.0, on_timeout=lambda: resets.append(True)
        )
        self.assertFalse(result["ok"])
        self.assertIn("TaskTimeoutError", result["error"])
        self.assertEqual(resets, [True])

    def test_without_timeout_runs_to_completion(self):
        fsm = TaskFSM(verbose=False)
        result = fsm.run(lambda: None, lambda: time.sleep(0.05))
        self.assertTrue(result["ok"])


if __name__ == "__main__":
    unittest.main()
