import json
import tempfile
import unittest
from pathlib import Path

from atri.action_library import (
    ActionLibraryError,
    validate_action,
    load_action,
    ACTION_SCHEMA_VERSION,
)


def make_valid_action(**overrides):
    data = {
        "schema_version": ACTION_SCHEMA_VERSION,
        "action_id": "walk",
        "name": "前进",
        "description": "测试动作",
        "frames": [
            {
                "index": 0,
                "duration_s": 0.2,
                "joints": {"left_hip_pitch": 8.0, "right_hip_pitch": -8.0},
            }
        ],
        "meta": {"source": "webots-calibration"},
    }
    data.update(overrides)
    return data


class TestValidateAction(unittest.TestCase):
    def test_valid(self):
        errors = validate_action(make_valid_action())
        self.assertEqual(errors, [])

    def test_missing_required(self):
        errors = validate_action({})
        self.assertIn("schema_version", " ".join(errors))

    def test_unknown_joint(self):
        data = make_valid_action()
        data["frames"][0]["joints"] = {"left_hand": 1.0}
        errors = validate_action(data)
        self.assertTrue(any("left_hand" in e for e in errors))

    def test_frame_missing_duration(self):
        data = make_valid_action()
        del data["frames"][0]["duration_s"]
        errors = validate_action(data)
        self.assertTrue(any("duration_s" in e for e in errors))

    def test_empty_frames(self):
        data = make_valid_action(frames=[])
        errors = validate_action(data)
        self.assertTrue(any("frames" in e for e in errors))


class TestLoadAction(unittest.TestCase):
    def test_load_valid_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "kick.json"
            path.write_text(json.dumps(make_valid_action(action_id="kick")), encoding="utf-8")
            data = load_action(path)
            self.assertEqual(data["action_id"], "kick")

    def test_load_invalid_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text(json.dumps({"foo": 1}), encoding="utf-8")
            with self.assertRaises(ActionLibraryError):
                load_action(path, strict=True)


if __name__ == "__main__":
    unittest.main()
