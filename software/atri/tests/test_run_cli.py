"""`python3 -m atri.run` 命令行入口的外部输入处理测试。

任务卡与观测文件都是外部输入：读取/解码/解析失败必须转成退出码 2 加一行错误，
不能裸抛 traceback。UnicodeDecodeError 是 ValueError 子类，既不是 OSError
也不是 JSONDecodeError，是最容易漏掉的一类。
"""
from __future__ import annotations

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from atri import run

TASK_CARD_DIR = Path(__file__).resolve().parents[1] / "task_cards"


def _any_card() -> Path:
    return sorted(TASK_CARD_DIR.glob("*.json"))[0]


class TestRunCliObservationFile(unittest.TestCase):
    def _run(self, argv):
        saved = sys.argv
        sys.argv = argv
        out, err = io.StringIO(), io.StringIO()
        try:
            with redirect_stdout(out), redirect_stderr(err):
                code = run.main()
        finally:
            sys.argv = saved
        return code, out.getvalue() + err.getvalue()

    def test_undecodable_observation_returns_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            obs = Path(tmp) / "obs.json"
            obs.write_bytes(b'\xff\xfe{"face": {"name": "A"}}')
            code, text = self._run(
                ["atri-run", str(_any_card()), "--observation", str(obs)]
            )
        self.assertEqual(code, 2)
        self.assertIn("观测", text)

    def test_malformed_observation_returns_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            obs = Path(tmp) / "obs.json"
            obs.write_text("{not json", encoding="utf-8")
            code, _ = self._run(
                ["atri-run", str(_any_card()), "--observation", str(obs)]
            )
        self.assertEqual(code, 2)

    def test_missing_observation_returns_2(self):
        code, _ = self._run(
            [
                "atri-run",
                str(_any_card()),
                "--observation",
                str(Path(tempfile.gettempdir()) / "atri-no-such-obs.json"),
            ]
        )
        self.assertEqual(code, 2)

    def test_non_object_observation_returns_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            obs = Path(tmp) / "obs.json"
            obs.write_text("[1, 2, 3]", encoding="utf-8")
            code, _ = self._run(
                ["atri-run", str(_any_card()), "--observation", str(obs)]
            )
        self.assertEqual(code, 2)

    def test_undecodable_task_card_returns_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            card = Path(tmp) / "card.json"
            card.write_bytes(b'\xff\xfe{"task_id": "T", "name": "x", "skills": ["face"]}')
            code, text = self._run(["atri-run", str(card)])
        self.assertEqual(code, 2)
        self.assertIn("任务卡", text)


if __name__ == "__main__":
    unittest.main()
