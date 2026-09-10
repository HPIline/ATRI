import json
import unittest
from types import SimpleNamespace

from atri.perception import (
    MockPerception,
    OpenCVPerception,
    PerceptionError,
    PerceptionResult,
)


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
        self.assertEqual(qr.data["payload"]["action"], "walk")
        self.assertEqual(ball.data["distance_cm"], 12.0)

    def test_custom(self):
        p = MockPerception(
            face={"name": "测试员B", "confidence": 0.98},
            qr={"payload": {"action": "turn", "deg": 30}},
            ball={"x_cm": -2.0, "distance_cm": 8.0},
        )
        self.assertEqual(p.detect_face().data["name"], "测试员B")
        self.assertEqual(p.detect_qr().data["payload"]["deg"], 30)
        self.assertEqual(p.detect_ball().data["x_cm"], -2.0)


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

    def test_missing_frame_raises(self):
        p = OpenCVPerception(cv2_module=FakeCV2())
        with self.assertRaises(PerceptionError):
            p.detect_face(frame=None)


if __name__ == "__main__":
    unittest.main()
