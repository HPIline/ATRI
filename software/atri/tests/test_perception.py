import sys
import unittest
from types import SimpleNamespace
from unittest import mock

from atri.perception import (
    MockPerception,
    OpenCVPerception,
    PerceptionError,
    PerceptionResult,
)
from atri.skills.base import SkillContext, perception_data


class FakeCascade:
    def __init__(self, path, faces=((10, 20, 30, 40),)):
        self.path = path
        self.faces = faces

    def detectMultiScale(self, gray, **kwargs):
        return list(self.faces)


class FakeQRDetector:
    def __init__(self, data='{"action":"walk","steps":3}'):
        self.data = data

    def detectAndDecode(self, frame):
        return self.data, None, None


class FakeContour:
    def __init__(self, area, x, y, w, h):
        self.area = area
        self.x = x
        self.y = y
        self.w = w
        self.h = h


class FakeCV2:
    COLOR_BGR2GRAY = 6
    COLOR_BGR2HSV = 40
    RETR_EXTERNAL = 0
    CHAIN_APPROX_SIMPLE = 1
    data = SimpleNamespace(haarcascades="/fake/haarcascades/")

    def __init__(self, faces=((10, 20, 30, 40),), qr_data='{"action":"walk","steps":3}', contours=None):
        self.faces = faces
        self.qr_data = qr_data
        self.contours = contours or [FakeContour(100, 50, 60, 20, 20)]

    def cvtColor(self, img, code):
        return img

    def equalizeHist(self, img):
        return img

    def CascadeClassifier(self, path):
        return FakeCascade(path, self.faces)

    def QRCodeDetector(self):
        return FakeQRDetector(self.qr_data)

    def inRange(self, img, lower, upper):
        return img

    def findContours(self, mask, mode, method):
        return self.contours, None

    def contourArea(self, contour):
        return contour.area

    def boundingRect(self, contour):
        return contour.x, contour.y, contour.w, contour.h


class TestPerceptionResult(unittest.TestCase):
    def test_to_dict(self):
        result = PerceptionResult(kind="face", data={"name": "A"}, confidence=0.9)
        self.assertEqual(result.to_dict()["kind"], "face")
        self.assertEqual(result.to_dict()["name"], "A")


class TestMockPerception(unittest.TestCase):
    def test_defaults(self):
        p = MockPerception()
        face = p.detect_face()
        qr = p.detect_qr()
        ball = p.detect_ball()
        self.assertEqual(face.kind, "face")
        self.assertEqual(face.data["name"], "测试员A")
        self.assertIs(face.data["found"], True)
        self.assertEqual(qr.data["payload"]["action"], "walk")
        self.assertIs(qr.data["found"], True)
        self.assertEqual(ball.data["distance_cm"], 12.0)
        self.assertIs(ball.data["found"], True)

    def test_custom(self):
        p = MockPerception(
            face={"name": "测试员B", "confidence": 0.98},
            qr={"payload": {"action": "turn", "deg": 30}},
            ball={"x_cm": -2.0, "distance_cm": 8.0},
        )
        self.assertEqual(p.detect_face().data["name"], "测试员B")
        self.assertEqual(p.detect_qr().data["payload"]["deg"], 30)
        self.assertEqual(p.detect_ball().data["x_cm"], -2.0)

    def test_available_is_true(self):
        self.assertTrue(MockPerception().available())


class TestOpenCVPerception(unittest.TestCase):
    def test_face_detected(self):
        p = OpenCVPerception(cv2_module=FakeCV2())
        result = p.detect_face(frame=[[[0, 0, 0]]])
        self.assertTrue(result.data["found"])
        self.assertEqual(result.data["bbox"], [10, 20, 30, 40])

    def test_face_not_detected(self):
        p = OpenCVPerception(cv2_module=FakeCV2(faces=()))
        result = p.detect_face(frame=[[[0, 0, 0]]])
        self.assertFalse(result.data["found"])

    def test_qr_detected_and_json_parsed(self):
        p = OpenCVPerception(cv2_module=FakeCV2())
        result = p.detect_qr(frame=[[[0, 0, 0]]])
        self.assertTrue(result.data["found"])
        self.assertEqual(result.data["payload"], {"action": "walk", "steps": 3})

    def test_ball_detected(self):
        p = OpenCVPerception(
            cv2_module=FakeCV2(),
            focal_px=300.0,
            ball_diameter_cm=4.0,
            pixels_per_cm=10.0,
        )
        result = p.detect_ball(frame=[[[0, 0, 0]] * 120 for _ in range(100)])
        self.assertTrue(result.data["found"])
        self.assertEqual(result.data["x_cm"], 0.0)
        self.assertGreater(result.data["distance_cm"], 0.0)

    def test_ball_distance_none_without_focal(self):
        p = OpenCVPerception(cv2_module=FakeCV2(), focal_px=None, pixels_per_cm=10.0)
        result = p.detect_ball(frame=[[[0, 0, 0]] * 120 for _ in range(100)])
        self.assertIsNone(result.data["distance_cm"])

    def test_pixels_per_cm_must_be_positive(self):
        for value in (0, -1, float("nan"), float("inf")):
            with self.assertRaises(PerceptionError):
                OpenCVPerception(pixels_per_cm=value)

    def test_available_false_without_cv2(self):
        """无 cv2 时 available() 必须为 False；显式注入 import 失败，不依赖宿主机是否装了 cv2。"""
        with mock.patch.dict(sys.modules, {"cv2": None}):
            p = OpenCVPerception(cv2_module=None)
            self.assertFalse(p.available())

    def test_missing_frame_raises(self):
        p = OpenCVPerception(cv2_module=FakeCV2())
        with self.assertRaises(PerceptionError):
            p.detect_face(frame=None)


class TestSkillContextPerception(unittest.TestCase):
    """B-1/B-6：感知通道状态与感知异常的转换。"""

    def _ctx(self, observation=None, perception=None):
        return SkillContext(
            task_id="P-01",
            task_name="感知",
            params={},
            cerebellum=None,
            observation=observation,
            perception=perception,
        )

    def test_channel_ready(self):
        ctx = self._ctx(observation={"face": {"found": True}})
        self.assertTrue(ctx.channel_ready("face"))
        self.assertFalse(ctx.channel_ready("ball"))

        class WithBall:
            def detect_ball(self):
                raise AssertionError("不应调用")

        self.assertTrue(self._ctx(perception=WithBall()).channel_ready("ball"))

    def test_perceive_converts_perception_error(self):
        class Broken:
            def detect_ball(self):
                raise PerceptionError("摄像头掉线")

        data = self._ctx(perception=Broken()).perceive("ball")
        self.assertIs(data.get("found"), False)
        self.assertIn("摄像头掉线", data.get("error", ""))

    def test_perceive_rejects_non_dict_observation_value(self):
        data = self._ctx(observation={"qr": ["walk", 3]}).perceive("qr")
        self.assertIs(data.get("found"), False)
        self.assertIn("list", data.get("error", ""))

    def test_perception_data_required_channel_empty(self):
        data, reason = perception_data(self._ctx(), "ball")
        self.assertEqual(data, {})
        self.assertIsNotNone(reason)

    def test_perception_data_optional_channel_absent(self):
        data, reason = perception_data(self._ctx(), "object", optional=True)
        self.assertEqual(data, {})
        self.assertIsNone(reason)

    def test_perception_data_requires_bool_found(self):
        """found 只接受 bool：仓库内所有生产者都写 bool，非 bool 只可能来自外部注入。

        字符串 "False"、"0" 在 Python 里为真，若按真值判定会让"没看见"被当成
        "看见了"并真的下发动作，故一律判非法。
        """
        for value in ("False", "0", "true", 1, 1.0, [1], {"a": 1}):
            with self.subTest(found=value):
                ctx = self._ctx(observation={"ball": {"found": value,
                                                      "x_cm": 1.0,
                                                      "distance_cm": 12.0}})
                _, reason = perception_data(ctx, "ball")
                self.assertIsNotNone(reason, f"found={value!r} 应判失败")
                self.assertIn("found", reason)

    def test_perception_data_accepts_bool_true(self):
        ctx = self._ctx(observation={"ball": {"found": True, "x_cm": 1.0}})
        data, reason = perception_data(ctx, "ball")
        self.assertIsNone(reason)
        self.assertEqual(data["x_cm"], 1.0)


if __name__ == "__main__":
    unittest.main()
