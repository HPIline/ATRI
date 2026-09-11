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

    def test_non_finite_duration_rejected(self):
        for value in (float("nan"), float("inf"), float("-inf")):
            data = make_valid_action()
            data["frames"][0]["duration_s"] = value
            errors = validate_action(data)
            self.assertTrue(any("duration_s" in e for e in errors), (value, errors))

    def test_out_of_limit_joint_rejected(self):
        data = make_valid_action()
        data["frames"][0]["joints"] = {"right_knee_pitch": 99999.0}
        errors = validate_action(data)
        self.assertTrue(any("right_knee_pitch" in e and "限位" in e for e in errors), errors)

    def test_non_numeric_joint_rejected(self):
        for value in ([1.0], "8.0", True, None):
            data = make_valid_action()
            data["frames"][0]["joints"] = {"left_hip_pitch": value}
            errors = validate_action(data)
            self.assertTrue(any("left_hip_pitch" in e for e in errors), (value, errors))

    def test_non_finite_joint_rejected(self):
        for value in (float("nan"), float("inf")):
            data = make_valid_action()
            data["frames"][0]["joints"] = {"head_yaw": value}
            errors = validate_action(data)
            self.assertTrue(errors, value)

    def test_huge_integer_values_rejected_without_crash(self):
        data = make_valid_action()
        data["frames"][0]["duration_s"] = 10 ** 400
        self.assertTrue(validate_action(data))
        data = make_valid_action()
        data["frames"][0]["joints"] = {"left_hip_pitch": 10 ** 400}
        errors = validate_action(data)
        self.assertTrue(any("left_hip_pitch" in e for e in errors), errors)


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

    def test_load_wraps_undecodable_bytes(self):
        """编码损坏的动作库要转成 ActionLibraryError，不得裸抛 UnicodeDecodeError。"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gbk.json"
            path.write_bytes(b'\xff\xfe{"schema_version": "1.0", "action_id": "k"}')
            with self.assertRaises(ActionLibraryError):
                load_action(path)

    def test_load_wraps_malformed_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaises(ActionLibraryError):
                load_action(path)

    def test_load_wraps_missing_file(self):
        with self.assertRaises(ActionLibraryError):
            load_action(Path(tempfile.gettempdir()) / "atri-no-such-action.json")

    def test_load_action_rejects_non_standard_literals(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nonfinite.json"
            for literal in ("NaN", "Infinity", "-Infinity"):
                text = (
                    '{"schema_version": "1.0", "action_id": "kick", "frames": '
                    '[{"duration_s": 0.1, "joints": {"head_yaw": ' + literal + "}}]}"
                )
                path.write_text(text, encoding="utf-8")
                with self.assertRaises(ActionLibraryError):
                    load_action(path)


if __name__ == "__main__":
    unittest.main()
