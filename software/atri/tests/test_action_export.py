import json
import tempfile
import unittest
from pathlib import Path

from atri.action_export import export_walk, frames_to_action
from atri.action_library import validate_action, ACTION_SCHEMA_VERSION
from atri.config import MAX_STEPS


class TestActionExport(unittest.TestCase):
    def test_frames_to_action_valid(self):
        action = frames_to_action(
            "test_walk",
            [{"left_hip_pitch": 1.0}, {"left_hip_pitch": 0.0}],
            duration_s=0.1,
        )
        self.assertEqual(action["schema_version"], ACTION_SCHEMA_VERSION)
        self.assertEqual(action["action_id"], "test_walk")
        self.assertEqual(len(action["frames"]), 2)
        self.assertEqual(validate_action(action), [])

    def test_export_walk_writes_valid_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "walk.json"
            export_walk(out, steps=2, period_s=0.2)
            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(data["action_id"], "walk")
            self.assertEqual(validate_action(data), [])

    def test_export_walk_rejects_out_of_range_steps(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "walk.json"
            with self.assertRaises(ValueError):
                export_walk(out, steps=MAX_STEPS + 1)


if __name__ == "__main__":
    unittest.main()
