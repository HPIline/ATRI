import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from atri.brain import Brain
from atri.cerebellum import Cerebellum
from atri.task_card import VALID_SKILLS, TaskCard, TaskCardError


class TestTaskCard(unittest.TestCase):
    def test_load_valid(self):
        data = {"task_id": "T-01", "name": "人脸识别", "skills": ["face"]}
        card = TaskCard.from_dict(data)
        self.assertEqual(card.task_id, "T-01")
        self.assertEqual(card.skills, ["face"])

    def test_missing_field(self):
        with self.assertRaises(TaskCardError):
            TaskCard.from_dict({"task_id": "T-01"})

    def test_unknown_skill(self):
        with self.assertRaises(TaskCardError):
            TaskCard.from_dict({"task_id": "T-01", "name": "x", "skills": ["fly"]})

    def test_roundtrip_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "card.json"
            data = {"task_id": "T-09", "name": "测试", "skills": ["face"], "params": {"a": 1}}
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            card = TaskCard.load(path)
            self.assertEqual(card.params["a"], 1)

    def test_valid_skills_match_brain_registry(self):
        brain = Brain(Cerebellum(sleeper=lambda dt: None))
        self.assertEqual(set(VALID_SKILLS), set(brain.skills))
        self.assertNotIn("idle", VALID_SKILLS)

    def test_timeout_must_be_finite_positive(self):
        for value in (float("nan"), float("inf"), float("-inf"), -5.0, 0.0, "abc", True, None):
            with self.assertRaises(TaskCardError):
                TaskCard.from_dict(
                    {"task_id": "T", "name": "x", "skills": ["face"], "timeout_s": value}
                )

    def test_timeout_accepts_positive_number(self):
        card = TaskCard.from_dict(
            {"task_id": "T", "name": "x", "skills": ["face"], "timeout_s": 0.5}
        )
        self.assertEqual(card.timeout_s, 0.5)

    def test_default_timeout(self):
        card = TaskCard.from_dict({"task_id": "T", "name": "x", "skills": ["face"]})
        self.assertGreater(card.timeout_s, 0.0)

    def test_load_rejects_nan_literal(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nan.json"
            path.write_text(
                '{"task_id": "N", "name": "x", "skills": ["face"], "timeout_s": NaN}',
                encoding="utf-8",
            )
            with self.assertRaises(TaskCardError):
                TaskCard.load(path)

    def test_load_rejects_infinity_literal(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "inf.json"
            path.write_text(
                '{"task_id": "N", "name": "x", "skills": ["face"], "timeout_s": Infinity}',
                encoding="utf-8",
            )
            with self.assertRaises(TaskCardError):
                TaskCard.load(path)

    def test_load_wraps_malformed_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaises(TaskCardError):
                TaskCard.load(path)

    def test_load_wraps_missing_file(self):
        with self.assertRaises(TaskCardError):
            TaskCard.load(Path(tempfile.gettempdir()) / "atri-not-exist.json")

    def test_load_wraps_undecodable_bytes(self):
        """编码损坏的任务卡要转成 TaskCardError。

        UnicodeDecodeError 是 ValueError 的子类，既不是 OSError 也不是
        JSONDecodeError，只捕获后两者会让它裸抛成 traceback。
        """
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gbk.json"
            path.write_bytes(b'\xff\xfe{"task_id": "T", "name": "x", "skills": ["face"]}')
            with self.assertRaises(TaskCardError):
                TaskCard.load(path)

    def test_unknown_top_level_field_warns_but_loads(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            card = TaskCard.from_dict(
                {"task_id": "U-01", "name": "x", "skills": ["face"], "wat": 1}
            )
        self.assertEqual(card.task_id, "U-01")
        self.assertIn("wat", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
