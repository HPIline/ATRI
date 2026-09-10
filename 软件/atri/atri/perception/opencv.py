"""OpenCV 视觉感知实现。

仅在需要真实摄像头/图片检测时依赖 opencv-python。代码在 Mac 上编写与测试，
真机摄像头检测放到 Windows 仿真/样机联调阶段运行。
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from .base import PerceptionBackend, PerceptionError, PerceptionResult


class OpenCVPerception(PerceptionBackend):
    name = "opencv"

    def __init__(
        self,
        cv2_module: Any = None,
        face_cascade_path: Optional[str] = None,
        ball_hsv_lower: Tuple[int, int, int] = (35, 80, 80),
        ball_hsv_upper: Tuple[int, int, int] = (85, 255, 255),
        ball_diameter_cm: float = 4.0,
        focal_px: Optional[float] = None,
        pixels_per_cm: float = 10.0,
    ) -> None:
        """初始化 OpenCV 感知后端。

        cv2_module 仅供测试注入 fake cv2；正常使用传 None，首次检测时自动 import cv2。
        """
        self._cv2 = cv2_module
        self.face_cascade_path = face_cascade_path
        self.ball_hsv_lower = ball_hsv_lower
        self.ball_hsv_upper = ball_hsv_upper
        self.ball_diameter_cm = ball_diameter_cm
        self.focal_px = focal_px
        self.pixels_per_cm = pixels_per_cm

    def available(self) -> bool:
        try:
            self._get_cv2()
            return True
        except PerceptionError:
            return False

    def _get_cv2(self) -> Any:
        if self._cv2 is None:
            try:
                import cv2  # type: ignore
            except ImportError as exc:
                raise PerceptionError(
                    "OpenCV 未安装：请执行 pip install opencv-python（真机视觉运行时才需要）"
                ) from exc
            self._cv2 = cv2
        return self._cv2

    def _require_frame(self, frame: Any) -> None:
        if frame is None:
            raise PerceptionError("detect_* 需要传入图像帧 frame（BGR numpy 数组）")

    def detect_face(self, frame: Any = None) -> PerceptionResult:
        self._require_frame(frame)
        cv = self._get_cv2()
        gray = cv.cvtColor(frame, cv.COLOR_BGR2GRAY)
        gray = cv.equalizeHist(gray)
        cascade_path = self.face_cascade_path
        if cascade_path is None:
            cascade_path = cv.data.haarcascades + "haarcascade_frontalface_default.xml"
        cascade = cv.CascadeClassifier(cascade_path)
        faces = cascade.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=5,
            minSize=(30, 30),
        )
        if len(faces) == 0:
            return PerceptionResult(kind="face", data={"found": False}, confidence=0.0)
        x, y, w, h = faces[0]
        return PerceptionResult(
            kind="face",
            data={"found": True, "bbox": [int(x), int(y), int(w), int(h)]},
            confidence=0.8,
            raw=faces,
        )

    def detect_qr(self, frame: Any = None) -> PerceptionResult:
        self._require_frame(frame)
        cv = self._get_cv2()
        detector = cv.QRCodeDetector()
        data, points, _ = detector.detectAndDecode(frame)
        if not data:
            return PerceptionResult(kind="qr", data={"found": False}, confidence=0.0)
        try:
            payload: Any = json.loads(data)
        except (TypeError, ValueError):
            payload = data
        return PerceptionResult(
            kind="qr",
            data={"found": True, "payload": payload},
            confidence=1.0,
            raw=points,
        )

    def detect_ball(self, frame: Any = None) -> PerceptionResult:
        self._require_frame(frame)
        cv = self._get_cv2()
        hsv = cv.cvtColor(frame, cv.COLOR_BGR2HSV)
        mask = cv.inRange(hsv, self.ball_hsv_lower, self.ball_hsv_upper)
        contours, _ = cv.findContours(
            mask, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE
        )
        if not contours:
            return PerceptionResult(kind="ball", data={"found": False}, confidence=0.0)

        areas = [cv.contourArea(c) for c in contours]
        best = contours[max(range(len(areas)), key=areas.__getitem__)]
        x, y, w, h = cv.boundingRect(best)
        cx = x + w / 2.0
        cy = y + h / 2.0
        if hasattr(frame, "shape") and len(frame.shape) >= 2:
            height, width = frame.shape[:2]
        else:
            height = len(frame)
            width = len(frame[0]) if height else 0
        x_cm = (cx - width / 2.0) / self.pixels_per_cm

        ball_diameter_px = max(w, h)
        distance_cm = 0.0
        if self.focal_px and ball_diameter_px > 0:
            distance_cm = self.ball_diameter_cm * self.focal_px / float(ball_diameter_px)

        return PerceptionResult(
            kind="ball",
            data={
                "found": True,
                "x_cm": round(x_cm, 2),
                "distance_cm": round(distance_cm, 2),
                "bbox": [int(x), int(y), int(w), int(h)],
                "center_px": [int(cx), int(cy)],
            },
            confidence=0.85,
            raw=best,
        )
