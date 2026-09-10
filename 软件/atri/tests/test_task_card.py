import json
import tempfile
import unittest
from pathlib import Path

from atri.task_card import TaskCard, TaskCardError


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
            data = {"task_id": "T-09", "name": "测试", "skills": ["idle"], "params": {"a": 1}}
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            card = TaskCard.load(path)
            self.assertEqual(card.params["a"], 1)


if __name__ == "__main__":
    unittest.main()
