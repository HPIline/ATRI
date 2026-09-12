"""二维码解码器测试。

分三层：
1. **纯逻辑**（不需要 cv2）：注册表、未知名字报错、模型缺失时的可用性提示；
2. **真解码往返**（需要 cv2 + qrcode）：真生成 → 真解码 → 逐字节比对；
3. **真模型**（需要 WeChat 四个模型文件）：缺失即跳过，不算失败。

第 2 层是关键：它是"这个二维码真的能被读出来"的最小可信证据，
而不是"我调用了 cv2 的一个函数"。
"""
from __future__ import annotations

import unittest
from pathlib import Path

from atri.perception.base import PerceptionError
from atri.perception.qr import (
    DECODER_NAMES,
    OpenCVQrDecoder,
    WeChatQrDecoder,
    build_qr_decoder,
    decoder_status,
)

try:
    import cv2  # noqa: F401

    HAS_CV2 = True
except ImportError:  # pragma: no cover
    HAS_CV2 = False

try:
    import qrcode  # noqa: F401

    HAS_QRCODE = True
except ImportError:  # pragma: no cover
    HAS_QRCODE = False

REPO_ROOT = Path(__file__).resolve().parents[3]
WECHAT_MODEL_DIR = REPO_ROOT / "models" / "wechat_qrcode"
HAS_WECHAT_MODELS = all(
    (WECHAT_MODEL_DIR / name).exists()
    for name in (
        "detect_2021nov.prototxt",
        "detect_2021nov.caffemodel",
        "sr_2021nov.prototxt",
        "sr_2021nov.caffemodel",
    )
)

PAYLOAD = '{"schema":"atri.path.v1","path":[{"action":"walk","steps":3},{"action":"turn","deg":90.0}]}'


class TestDecoderRegistry(unittest.TestCase):
    def test_expected_decoders_registered(self):
        self.assertEqual(set(DECODER_NAMES), {"opencv", "aruco", "wechat"})

    def test_unknown_decoder_rejected(self):
        with self.assertRaises(PerceptionError) as ctx:
            build_qr_decoder("magic")
        self.assertIn("未知二维码解码器", str(ctx.exception))

    def test_status_lists_all_with_reason(self):
        status = {item["decoder"]: item for item in decoder_status(WECHAT_MODEL_DIR)}
        self.assertEqual(set(status), {"opencv", "aruco", "wechat"})
        for item in status.values():
            if not item["available"]:
                self.assertTrue(item["reason"], "不可用时必须给出原因")

    def test_wechat_missing_models_reports_actionable_reason(self):
        decoder = WeChatQrDecoder(model_dir="/nonexistent/wechat")
        ok, reason = decoder.available()
        self.assertFalse(ok)
        self.assertIn("fetch_models", reason)
        self.assertIn("detect_2021nov.prototxt", reason)

    def test_decode_none_frame_raises(self):
        with self.assertRaises(PerceptionError):
            OpenCVQrDecoder(cv2_module=object()).decode(None)


class FakeQRDetector:
    def __init__(self, data):
        self.data = data

    def detectAndDecode(self, frame):
        return self.data, None, None


class FakeCv2:
    """最小假 cv2：只需提供两个检测器构造入口。"""

    def __init__(self, data=PAYLOAD):
        self._data = data

    def QRCodeDetector(self):
        return FakeQRDetector(self._data)

    def QRCodeDetectorAruco(self):
        return FakeQRDetector(self._data)


class TestDecoderWithFakeCv2(unittest.TestCase):
    def test_opencv_decoder_returns_payload(self):
        decoder = OpenCVQrDecoder(cv2_module=FakeCv2())
        result = decoder.decode([[0]])
        self.assertTrue(result.found)
        self.assertEqual(result.data, PAYLOAD)
        self.assertEqual(result.decoder, "opencv")

    def test_empty_result_is_found_false(self):
        decoder = OpenCVQrDecoder(cv2_module=FakeCv2(data=""))
        result = decoder.decode([[0]])
        self.assertFalse(result.found)
        self.assertEqual(result.data, "")

    def test_decoder_swallows_cv2_exception(self):
        """cv2 在退化输入上会抛，技能层不该因此把整张任务卡推进 ERROR。"""

        class ExplodingCv2(FakeCv2):
            def QRCodeDetector(self):
                raise RuntimeError("cv2 炸了")

        decoder = OpenCVQrDecoder(cv2_module=ExplodingCv2())
        result = decoder.decode([[0]])
        self.assertFalse(result.found)
        self.assertIn("RuntimeError", result.error)


@unittest.skipUnless(HAS_CV2 and HAS_QRCODE, "需要 cv2 与 qrcode")
class TestRealRoundTrip(unittest.TestCase):
    """真生成 → 真解码。这是"二维码确实能被读出来"的最小可信证据。"""

    def _make_frame(self, payload=PAYLOAD, ecc="M", box_size=10):
        import cv2

        generator = __import__("atri.qrgen", fromlist=["QRCodeGenerator"]).QRCodeGenerator(
            error_correction=ecc, box_size=box_size
        )
        out = Path(self._tmpdir.name) / "qr.png"
        generator.generate_payload(payload, out)
        frame = cv2.imread(str(out), cv2.IMREAD_COLOR)
        self.assertIsNotNone(frame)
        return frame

    def setUp(self):
        import tempfile

        self._tmpdir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_opencv_decodes_what_we_generated(self):
        frame = self._make_frame()
        result = build_qr_decoder("opencv").decode(frame)
        self.assertTrue(result.found)
        self.assertEqual(result.data, PAYLOAD)

    def test_aruco_decodes_what_we_generated(self):
        frame = self._make_frame()
        result = build_qr_decoder("aruco").decode(frame)
        self.assertTrue(result.found)
        self.assertEqual(result.data, PAYLOAD)

    def test_payload_survives_parse(self):
        from atri.path_plan import parse_payload

        frame = self._make_frame()
        result = build_qr_decoder("opencv").decode(frame)
        path = parse_payload(result.data)
        self.assertEqual(len(path.segments), 2)
        self.assertEqual(path.total_steps, 3)

    def test_higher_ecc_still_decodes(self):
        for ecc in ("L", "M", "Q", "H"):
            with self.subTest(ecc=ecc):
                frame = self._make_frame(ecc=ecc, box_size=8)
                result = build_qr_decoder("opencv").decode(frame)
                self.assertTrue(result.found)

    def test_blank_image_finds_nothing(self):
        import numpy as np

        result = build_qr_decoder("opencv").decode(np.full((240, 240, 3), 255, np.uint8))
        self.assertFalse(result.found)


@unittest.skipUnless(HAS_CV2 and HAS_QRCODE and HAS_WECHAT_MODELS, "需要 WeChat 模型文件")
class TestWeChatDecoderReal(unittest.TestCase):
    def test_wechat_decodes_what_we_generated(self):
        import cv2
        import tempfile

        from atri.qrgen import QRCodeGenerator

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "qr.png"
            QRCodeGenerator(error_correction="M").generate_payload(PAYLOAD, out)
            frame = cv2.imread(str(out), cv2.IMREAD_COLOR)
        decoder = WeChatQrDecoder(model_dir=WECHAT_MODEL_DIR)
        ok, reason = decoder.available()
        self.assertTrue(ok, reason)
        result = decoder.decode(frame)
        self.assertTrue(result.found)
        self.assertEqual(result.data, PAYLOAD)


class CountingFrameSource:
    """假取帧来源：记录被取了几次。"""

    def __init__(self, frame="FRAME"):
        self.frame = frame
        self.calls = 0

    def grab(self):
        self.calls += 1
        return self.frame


class TestPerceptionFrameSource(unittest.TestCase):
    """补的是原先缺的一环：`SkillContext.perceive()` 调 `detect_qr()` 时不传 frame，
    没有取帧来源的感知后端在真机上永远拿不到图。"""

    def test_perception_uses_frame_source_when_no_frame_given(self):
        from atri.perception import OpenCVPerception

        source = CountingFrameSource()
        perception = OpenCVPerception(cv2_module=FakeCv2(), frame_source=source)
        result = perception.detect_qr()
        self.assertTrue(result.data["found"])
        self.assertEqual(source.calls, 1)
        # FakeCv2 返回的是**路径**格式 payload（PAYLOAD 常量）
        self.assertEqual(len(result.data["payload"]["path"]), 2)

    def test_explicit_frame_wins_over_source(self):
        from atri.perception import OpenCVPerception

        source = CountingFrameSource()
        perception = OpenCVPerception(cv2_module=FakeCv2(), frame_source=source)
        perception.detect_qr(frame=[[0]])
        self.assertEqual(source.calls, 0)

    def test_missing_frame_and_no_source_still_raises(self):
        from atri.perception import OpenCVPerception

        perception = OpenCVPerception(cv2_module=FakeCv2())
        with self.assertRaises(PerceptionError):
            perception.detect_qr()

    def test_decoder_name_is_honoured(self):
        from atri.perception import OpenCVPerception

        perception = OpenCVPerception(cv2_module=FakeCv2(), qr_decoder="aruco")
        self.assertEqual(perception.detect_qr(frame=[[0]]).data["decoder"], "aruco")


if __name__ == "__main__":
    unittest.main()
