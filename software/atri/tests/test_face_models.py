"""真模型烟雾测试：需要 models/ 下的 ONNX 文件（没有就跳过，不算失败）。

CI 里会先跑 ``python tools/fetch_models.py`` 再跑本文件，用来证明
"代码能真的把模型加载起来并算出 128 维特征"，而不是只有假对象在自娱自乐。

不依赖任何人脸图片：噪声图用来验"不误报"，纯色块用来验"出向量"。
"""
from __future__ import annotations

import unittest
from pathlib import Path

try:
    import numpy as np

    HAS_NUMPY = True
except ImportError:  # pragma: no cover
    np = None  # type: ignore
    HAS_NUMPY = False

REPO_ROOT = Path(__file__).resolve().parents[3]
MODELS = REPO_ROOT / "models"
YUNET = MODELS / "face_detection_yunet_2023mar.onnx"
SFACE = MODELS / "face_recognition_sface_2021dec.onnx"

needs_numpy = unittest.skipUnless(HAS_NUMPY, "需要 numpy")
needs_yunet = unittest.skipUnless(YUNET.exists(), f"缺少模型 {YUNET}（先跑 tools/fetch_models.py）")
needs_sface = unittest.skipUnless(SFACE.exists(), f"缺少模型 {SFACE}（先跑 tools/fetch_models.py）")


@needs_numpy
@needs_yunet
class TestYuNetRealModel(unittest.TestCase):
    def test_loads_and_finds_no_face_in_noise(self):
        from atri.perception.faces import YuNetDetector

        det = YuNetDetector(str(YUNET))
        noise = (np.random.default_rng(0).random((240, 320, 3)) * 255).astype(np.uint8)
        self.assertEqual(det.detect(noise), [])  # 噪声里不该"看出"人脸

    def test_missing_model_error_is_actionable(self):
        from atri.perception.base import PerceptionError
        from atri.perception.faces import YuNetDetector

        with self.assertRaises(PerceptionError) as ctx:
            YuNetDetector("/nope/yunet.onnx").detect(np.zeros((64, 64, 3), np.uint8))
        self.assertIn("fetch_models", str(ctx.exception))


@needs_numpy
@needs_sface
class TestSFaceRealModel(unittest.TestCase):
    def test_embedding_is_128d_and_normalized(self):
        from atri.perception.faces import SFaceEmbedder

        emb = SFaceEmbedder(str(SFACE))
        vec = emb.embed(np.full((112, 112, 3), 128, np.uint8))
        self.assertEqual(vec.shape, (128,))
        self.assertAlmostEqual(float(np.linalg.norm(vec)), 1.0, places=5)

    def test_same_input_gives_same_vector(self):
        from atri.perception.faces import SFaceEmbedder

        emb = SFaceEmbedder(str(SFACE))
        img = np.full((112, 112, 3), 90, np.uint8)
        np.testing.assert_allclose(emb.embed(img), emb.embed(img), atol=1e-6)

    def test_different_input_gives_different_vector(self):
        from atri.perception.faces import SFaceEmbedder

        emb = SFaceEmbedder(str(SFACE))
        a = emb.embed(np.full((112, 112, 3), 30, np.uint8))
        b = emb.embed(np.full((112, 112, 3), 220, np.uint8))
        self.assertLess(float(a @ b), 0.999)

    def test_dim_matches_declared_constant(self):
        from atri.perception.faces import SFaceEmbedder
        from atri.perception.faces.embedder import SFACE_DIM

        emb = SFaceEmbedder(str(SFACE))
        self.assertEqual(emb.dim, SFACE_DIM)
        self.assertEqual(emb.embed(np.full((112, 112, 3), 10, np.uint8)).shape[0], SFACE_DIM)


if __name__ == "__main__":
    unittest.main()
