"""人脸识别管线单测：检测 → 裁剪 → 特征 → 比对 → 拒识。

用假检测器 + 受控假特征提取器（不加载真模型），把管线逻辑测穿：
多人脸取最可信、小脸跳过、单脸失败不毁整帧、无人脸、拒识。
"""
from __future__ import annotations

import unittest

try:
    import numpy as np

    HAS_NUMPY = True
except ImportError:  # pragma: no cover
    np = None  # type: ignore
    HAS_NUMPY = False


@unittest.skipUnless(HAS_NUMPY, "需要 numpy")
class TestFacePipeline(unittest.TestCase):
    def setUp(self) -> None:
        from atri.perception.faces import FaceBox, FaceDetector, FaceEmbedder, FaceRecognizer, FaceDB

        class FakeDetector(FaceDetector):
            name = "fake"

            def __init__(self, boxes):
                self._boxes = list(boxes)

            def detect(self, frame):
                return list(self._boxes)

        class KeyedEmbedder(FaceEmbedder):
            """用裁剪图左上角像素值当"身份"，返回预设向量 —— 完全可控。"""

            name = "keyed"
            dim = 4

            def __init__(self, table, fail_on=None):
                self.table = dict(table)
                self.fail_on = set(fail_on or [])

            def embed(self, face_bgr):
                key = int(np.asarray(face_bgr).reshape(-1)[0])
                if key in self.fail_on:
                    raise RuntimeError(f"故意失败 key={key}")
                vec = np.asarray(self.table.get(key, [0.0, 0.0, 0.0, 1.0]), dtype=np.float32)
                return vec / np.linalg.norm(vec)

        self.FaceBox = FaceBox
        self.FaceRecognizer = FaceRecognizer
        self.FaceDB = FaceDB
        self.FakeDetector = FakeDetector
        self.KeyedEmbedder = KeyedEmbedder

    @staticmethod
    def _frame(key: int, size: int = 200):
        """构造一张整块同色的假图；左上角像素即身份 key。"""
        return np.full((size, size, 3), key, dtype=np.uint8)

    def _recognizer(self, boxes, table, fail_on=None, db=None, min_face_px=40):
        return self.FaceRecognizer(
            detector=self.FakeDetector(boxes),
            embedder=self.KeyedEmbedder(table, fail_on),
            db=db,
            min_face_px=min_face_px,
        )

    def test_recognizes_known_face(self):
        db = self.FaceDB(embedder="keyed", dim=4, threshold=0.5)
        db.enroll("甲", [[1.0, 0.0, 0.0, 0.0]])
        rec = self._recognizer([self.FaceBox(bbox=(0, 0, 100, 100))], {10: [1.0, 0.0, 0.0, 0.0]}, db=db)
        result = rec.recognize(self._frame(10))
        self.assertTrue(result.found)
        self.assertEqual(result.recognized_name, "甲")
        self.assertAlmostEqual(result.faces[0].similarity, 1.0, places=5)

    def test_rejects_unknown_face(self):
        db = self.FaceDB(embedder="keyed", dim=4, threshold=0.5)
        db.enroll("甲", [[1.0, 0.0, 0.0, 0.0]])
        # 陌生人的向量与库里任何人都不像
        rec = self._recognizer([self.FaceBox(bbox=(0, 0, 100, 100))], {20: [0.0, 0.0, 1.0, 0.0]}, db=db)
        result = rec.recognize(self._frame(20))
        self.assertTrue(result.found)
        self.assertIsNone(result.recognized_name)
        self.assertFalse(result.faces[0].recognized)

    def test_no_face_found(self):
        rec = self._recognizer([], {})
        result = rec.recognize(self._frame(0))
        self.assertFalse(result.found)
        self.assertIsNone(result.recognized_name)
        self.assertEqual(result.faces, [])

    def test_detection_only_without_db(self):
        """没配库时只做检测：能给出 bbox，但不给姓名（不能假装认识）。"""
        rec = self._recognizer([self.FaceBox(bbox=(5, 6, 100, 100))], {10: [1.0, 0, 0, 0]})
        result = rec.recognize(self._frame(10))
        self.assertTrue(result.found)
        self.assertIsNone(result.faces[0].name)
        self.assertFalse(result.faces[0].recognized)

    def test_picks_most_confident_among_multiple_faces(self):
        db = self.FaceDB(embedder="keyed", dim=4, threshold=0.5)
        db.enroll("甲", [[1.0, 0.0, 0.0, 0.0]])
        db.enroll("乙", [[0.0, 1.0, 0.0, 0.0]])
        boxes = [
            self.FaceBox(bbox=(0, 0, 100, 100)),
            self.FaceBox(bbox=(100, 0, 100, 100)),
        ]
        # 左边甲（完美匹配），右边乙（较差的匹配）
        rec = self._recognizer(
            boxes,
            {10: [1.0, 0.0, 0.0, 0.0], 20: [0.3, 0.6, 0.0, 0.0]},
            db=db,
        )
        # 用拼图让两个 crop 拿到不同的 key
        frame = np.zeros((200, 200, 3), dtype=np.uint8)
        frame[:, :100] = 10
        frame[:, 100:] = 20

        result = rec.recognize(frame)
        self.assertEqual(len(result.faces), 2)
        self.assertEqual(result.recognized_name, "甲")

    def test_small_face_is_skipped(self):
        rec = self._recognizer(
            [self.FaceBox(bbox=(0, 0, 20, 20))], {10: [1.0, 0, 0, 0]}, min_face_px=40
        )
        result = rec.recognize(self._frame(10))
        self.assertEqual(result.faces, [])  # 太小 → 不认，也不硬报
        self.assertEqual(rec.stats["skipped_small"], 1)

    def test_one_face_error_does_not_kill_frame(self):
        db = self.FaceDB(embedder="keyed", dim=4, threshold=0.5)
        db.enroll("甲", [[1.0, 0.0, 0.0, 0.0]])
        boxes = [self.FaceBox(bbox=(0, 0, 100, 100)), self.FaceBox(bbox=(100, 0, 100, 100))]
        rec = self._recognizer(
            boxes,
            {10: [1.0, 0.0, 0.0, 0.0], 20: [1.0, 0.0, 0.0, 0.0]},
            fail_on=[20],
            db=db,
        )
        frame = np.zeros((200, 200, 3), dtype=np.uint8)
        frame[:, :100] = 20  # 这张会失败
        frame[:, 100:] = 10  # 这张正常
        result = rec.recognize(frame)
        self.assertEqual(len(result.faces), 2)
        self.assertEqual(result.recognized_name, "甲")
        errors = [f for f in result.faces if f.error]
        self.assertEqual(len(errors), 1)
        self.assertEqual(rec.stats["errors"], 1)

    def test_recognize_requires_frame(self):
        from atri.perception.base import PerceptionError

        rec = self._recognizer([], {})
        with self.assertRaises(PerceptionError):
            rec.recognize(None)

    def test_to_dict_is_json_friendly(self):
        db = self.FaceDB(embedder="keyed", dim=4, threshold=0.5)
        db.enroll("甲", [[1.0, 0.0, 0.0, 0.0]])
        rec = self._recognizer([self.FaceBox(bbox=(0, 0, 100, 100))], {10: [1.0, 0, 0, 0]}, db=db)
        payload = rec.recognize(self._frame(10)).to_dict()
        self.assertEqual(payload["name"], "甲")
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["faces"][0]["bbox"], [0, 0, 100, 100])
        import json

        json.dumps(payload)  # 不抛异常即为可序列化


@unittest.skipUnless(HAS_NUMPY, "需要 numpy")
class TestDetectorContract(unittest.TestCase):
    def test_yunet_missing_model_raises_clear_error(self):
        from atri.perception.base import PerceptionError
        from atri.perception.faces import YuNetDetector

        det = YuNetDetector(model_path="/nonexistent/yunet.onnx")
        frame = np.zeros((64, 64, 3), dtype=np.uint8)
        with self.assertRaises(PerceptionError) as ctx:
            det.detect(frame)
        self.assertIn("fetch_models", str(ctx.exception))

    def test_detector_rejects_non_image(self):
        from atri.perception.base import PerceptionError
        from atri.perception.faces import YuNetDetector

        det = YuNetDetector(model_path="/nonexistent/yunet.onnx")
        with self.assertRaises(PerceptionError):
            det.detect([[1, 2, 3]])

    def test_sface_missing_model_raises_clear_error(self):
        from atri.perception.base import PerceptionError
        from atri.perception.faces import SFaceEmbedder

        emb = SFaceEmbedder(model_path="/nonexistent/sface.onnx")
        with self.assertRaises(PerceptionError) as ctx:
            emb.embed(np.zeros((112, 112, 3), dtype=np.uint8))
        self.assertIn("fetch_models", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
