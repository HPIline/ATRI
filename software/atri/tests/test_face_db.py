"""人脸子模块单测：几何对齐 + 注册库。

**不需要 numpy 之外的任何东西**（不加载真模型、不读数据集），CI 可跑。
装了 opencv 的机器会多跑几项；没装就跳过，不用 fail 掩盖问题。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

try:
    import numpy as np

    HAS_NUMPY = True
except ImportError:  # pragma: no cover - 零依赖环境
    np = None  # type: ignore
    HAS_NUMPY = False


@unittest.skipUnless(HAS_NUMPY, "需要 numpy（pip install 'numpy<2'）")
class TestAlignGeometry(unittest.TestCase):
    def setUp(self) -> None:
        from atri.perception.faces.align import FACE_TEMPLATE_112

        self.template = FACE_TEMPLATE_112

    def test_identity_transform_is_identity(self):
        from atri.perception.faces.align import similarity_transform

        m = similarity_transform(self.template, self.template)
        np.testing.assert_allclose(m, np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]), atol=1e-6)

    def test_recovers_known_rotation_scale_translation(self):
        """构造一个已知的缩放+旋转+平移，看矩阵能不能还原它。"""
        from atri.perception.faces.align import similarity_transform

        theta = np.deg2rad(30.0)
        scale = 1.7
        rot = np.array([[np.cos(theta), -np.sin(theta)], [np.sin(theta), np.cos(theta)]])
        t = np.array([12.0, -7.0])
        src = self.template
        dst = scale * (src @ rot.T) + t
        m = similarity_transform(src, dst)
        np.testing.assert_allclose(m[:, :2], scale * rot, atol=1e-6)
        np.testing.assert_allclose(m[:, 2], t, atol=1e-6)

    def test_order_landmarks_sorts_by_x(self):
        from atri.perception.faces.align import order_landmarks

        # 故意把左右眼、左右嘴角写反
        lm = [[80, 50], [40, 51], [60, 72], [75, 92], [45, 92]]
        ordered = order_landmarks(lm)
        np.testing.assert_allclose(ordered[:, 0], [40.0, 80.0, 60.0, 45.0, 75.0])
        np.testing.assert_allclose(ordered[2], [60.0, 72.0])  # 鼻尖位置不动

    def test_order_landmarks_rejects_wrong_count(self):
        from atri.perception.base import PerceptionError
        from atri.perception.faces.align import order_landmarks

        with self.assertRaises(PerceptionError):
            order_landmarks([[1, 2], [3, 4]])

    def test_degenerate_points_rejected(self):
        from atri.perception.base import PerceptionError
        from atri.perception.faces.align import similarity_transform

        same = np.zeros((5, 2))
        with self.assertRaises(PerceptionError):
            similarity_transform(same, self.template)


@unittest.skipUnless(HAS_NUMPY, "需要 numpy")
class TestFaceDB(unittest.TestCase):
    @staticmethod
    def _db(threshold: float = 0.5):
        from atri.perception.faces import FaceDB

        return FaceDB(embedder="mock", dim=4, threshold=threshold)

    def test_enroll_and_save_load_roundtrip(self):
        from atri.perception.faces import FaceDB

        db = self._db()
        db.enroll("甲", [[1.0, 0.0, 0.0, 0.0], [0.98, 0.02, 0, 0]], meta={"source": "test"})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "face_db.json"
            db.save(path)
            loaded = FaceDB.load(path)

        self.assertEqual(loaded.names, ["甲"])
        self.assertEqual(len(loaded), 2)
        self.assertAlmostEqual(loaded.threshold, 0.5)
        self.assertEqual(loaded.dim, 4)
        self.assertEqual(loaded.people[0].meta["source"], "test")

    def test_enroll_same_name_appends_vectors(self):
        db = self._db()
        db.enroll("甲", [[1.0, 0, 0, 0]])
        total = db.enroll("甲", [[0.9, 0.1, 0, 0]])
        self.assertEqual(total, 2)
        self.assertEqual(len(db), 2)
        self.assertEqual(db.names, ["甲"])

    def test_match_returns_best_and_recognizes(self):
        db = self._db(threshold=0.5)
        db.enroll("甲", [[1.0, 0.0, 0.0, 0.0]])
        db.enroll("乙", [[0.0, 1.0, 0.0, 0.0]])
        result = db.match([0.99, 0.01, 0.0, 0.0])
        self.assertTrue(result.recognized)
        self.assertEqual(result.name, "甲")
        self.assertGreater(result.similarity, 0.99)

    def test_match_rejects_unknown_face(self):
        """陌生人必须拒识，不能硬认成库里的某个人。"""
        db = self._db(threshold=0.5)
        db.enroll("甲", [[1.0, 0.0, 0.0, 0.0]])
        result = db.match([0.0, 0.0, 1.0, 0.0])
        self.assertFalse(result.recognized)
        self.assertIsNone(result.name)

    def test_match_on_empty_db_rejects(self):
        result = self._db().match([1.0, 0.0, 0.0, 0.0])
        self.assertFalse(result.recognized)
        self.assertEqual(result.similarity, 0.0)

    def test_margin_between_best_and_second(self):
        db = self._db(threshold=0.1)
        db.enroll("甲", [[1.0, 0.0, 0.0, 0.0]])
        db.enroll("乙", [[0.8, 0.6, 0.0, 0.0]])
        result = db.match([1.0, 0.0, 0.0, 0.0])
        self.assertEqual(result.name, "甲")
        self.assertEqual(result.second_best_name, "乙")
        self.assertAlmostEqual(result.margin, 1.0 - 0.8, places=5)

    def test_rejects_bad_threshold(self):
        from atri.perception.base import PerceptionError
        from atri.perception.faces import FaceDB

        for bad in (0.0, -0.1, 1.5):
            with self.assertRaises(PerceptionError):
                FaceDB(embedder="mock", dim=4, threshold=bad)

    def test_rejects_wrong_dim_vector(self):
        from atri.perception.base import PerceptionError

        db = self._db()
        with self.assertRaises(PerceptionError):
            db.enroll("甲", [[1.0, 0.0, 0.0]])

    def test_load_rejects_legacy_schema(self):
        """旧的 4 维假数据格式必须被挡下，绝不能当成能用的库。"""
        from atri.perception.base import PerceptionError
        from atri.perception.faces import FaceDB

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "old.json"
            path.write_text(json.dumps({"测试员A": [0.12, 0.34, 0.56, 0.78]}), encoding="utf-8")
            with self.assertRaises(PerceptionError) as ctx:
                FaceDB.load(path)
        self.assertIn("schema_version", str(ctx.exception))

    def test_load_rejects_dim_mismatch(self):
        from atri.perception.base import PerceptionError
        from atri.perception.faces import FaceDB

        payload = {
            "schema_version": 1,
            "embedder": "sface",
            "dim": 128,
            "threshold": 0.4,
            "people": [{"name": "甲", "vectors": [[1.0, 0.0]], "meta": {}}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(PerceptionError) as ctx:
                FaceDB.load(path)
        self.assertIn("向量长度", str(ctx.exception))

    def test_load_missing_file(self):
        from atri.perception.base import PerceptionError
        from atri.perception.faces import FaceDB

        with self.assertRaises(PerceptionError):
            FaceDB.load("/nonexistent/face_db.json")


@unittest.skipUnless(HAS_NUMPY, "需要 numpy")
class TestEmbedderUnit(unittest.TestCase):
    def test_l2_normalize(self):
        from atri.perception.faces import l2_normalize

        v = l2_normalize([3.0, 4.0])
        self.assertAlmostEqual(float(np.linalg.norm(v)), 1.0, places=6)

    def test_l2_normalize_rejects_zero(self):
        from atri.perception.base import PerceptionError
        from atri.perception.faces import l2_normalize

        with self.assertRaises(PerceptionError):
            l2_normalize([0.0, 0.0])

    def test_mock_embedder_is_deterministic_and_normalized(self):
        from atri.perception.faces import MockEmbedder

        emb = MockEmbedder(dim=16)
        img = np.zeros((112, 112, 3), np.uint8)
        a = emb.embed(img)
        b = emb.embed(img)
        np.testing.assert_allclose(a, b)
        self.assertAlmostEqual(float(np.linalg.norm(a)), 1.0, places=6)
        self.assertEqual(a.shape, (16,))

    def test_mock_embedder_differs_for_different_images(self):
        from atri.perception.faces import MockEmbedder

        emb = MockEmbedder(dim=16)
        a = emb.embed(np.zeros((112, 112, 3), np.uint8))
        b = emb.embed(np.full((112, 112, 3), 200, np.uint8))
        self.assertLess(float(a @ b), 0.99)


if __name__ == "__main__":
    unittest.main()
