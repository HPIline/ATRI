import unittest

from atri.brain import Brain
from atri.cerebellum import Cerebellum, MockServoBus
from atri.task_card import TaskCard


class TestBrain(unittest.TestCase):
    def setUp(self):
        self.cere = Cerebellum(servo_bus=MockServoBus())
        self.brain = Brain(self.cere)

    def _run(self, skills, obs=None):
        card = TaskCard.from_dict({"task_id": "U-01", "name": "unit", "skills": skills})
        return self.brain.execute_task(card, observation=obs or {})

    def test_face(self):
        result = self._run(["face"], {"face": {"name": "测试员B", "confidence": 0.9}})
        self.assertTrue(result["ok"])
        self.assertEqual(result["result"]["results"][0]["name"], "测试员B")

    def test_qr(self):
        result = self._run(["qr"], {"qr": {"payload": {"action": "walk", "steps": 2}}})
        self.assertTrue(result["ok"])

    def test_carry(self):
        result = self._run(["carry"], {"object": {"target": "蓝块", "distance_cm": 4.0}})
        self.assertTrue(result["ok"])

    def test_kick(self):
        result = self._run(["kick"], {"ball": {"x_cm": -2.0, "distance_cm": 10.0}})
        self.assertTrue(result["ok"])

    def test_dance(self):
        result = self._run(["dance"], {"speech": {"keyword": "跳舞"}})
        self.assertTrue(result["ok"])


if __name__ == "__main__":
    unittest.main()
