"""OpenCV 视觉感知实现。

仅在需要真实摄像头/图片检测时依赖 opencv-python。代码在 Mac 上编写与测试，
真机摄像头检测放到 Windows 仿真/样机联调阶段运行。
"""
from __future__ import annotations

import json
import math
from typing import Any, Dict, Optional, Tuple

from .base import PerceptionBackend, PerceptionError, PerceptionResult


class OpenCVPerception(PerceptionBackend):
    name = "opencv"

    # 常见色块的 HSV 两段区间。红绕 0 断开，必须两段并起来。
    OBJECT_HSV = {
        "红块": (((0, 80, 80), (10, 255, 255)), ((170, 80, 80), (180, 255, 255))),
        "蓝块": (((100, 80, 80), (130, 255, 255)),),
        "绿块": (((35, 80, 80), (85, 255, 255)),),
    }

    def __init__(
        self,
        cv2_module: Any = None,
        face_cascade_path: Optional[str] = None,
        ball_hsv_lower: Tuple[int, int, int] = (35, 80, 80),
        ball_hsv_upper: Tuple[int, int, int] = (85, 255, 255),
        object_hsv_ranges: Optional[Tuple[Tuple[Tuple[int, int, int], Tuple[int, int, int]], ...]] = None,
        ball_diameter_cm: float = 4.0,
        object_size_cm: float = 4.0,
        focal_px: Optional[float] = None,
        pixels_per_cm: float = 10.0,
        frame_source: Any = None,
        object_target: str = "红块",
        qr_decoder: str = "opencv",
    ) -> None:
        """初始化 OpenCV 感知后端。

        cv2_module 仅供测试注入 fake cv2；正常使用传 None，首次检测时自动 import cv2。
        frame_source 可选：技能层不传 frame 时从这里 grab() 一帧（摄像头 / 图片文件）。
        qr_decoder 选二维码解码器（``opencv`` / ``aruco`` / ``wechat``，见
        :mod:`atri.perception.qr`）；主用哪个由 ``software/atri/tools/qr_eval.py``
        的对照实测决定（实测结论：wechat 判据条件下 100%，且单帧最快）。
        """
        self._cv2 = cv2_module
        self.face_cascade_path = face_cascade_path
        self.ball_hsv_lower = ball_hsv_lower
        self.ball_hsv_upper = ball_hsv_upper
        self.object_target = object_target
        # 红块色相绕 0 断开，两段并起来。
        self.object_hsv_ranges = object_hsv_ranges or self.OBJECT_HSV.get(
            object_target, self.OBJECT_HSV["红块"]
        )
        self.ball_diameter_cm = ball_diameter_cm
        self.object_size_cm = object_size_cm
        self.focal_px = self._checked_positive("focal_px", focal_px, allow_none=True)
        self.pixels_per_cm = self._checked_positive("pixels_per_cm", pixels_per_cm, allow_none=False)
        self.frame_source = frame_source
        self.qr_decoder_name = qr_decoder
        self._qr_decoder: Any = None

    @staticmethod
    def _checked_positive(name: str, value: Any, allow_none: bool) -> Optional[float]:
        """标定参数必须是正有限数：像素当量为 0 会在换算时除零。"""
        if value is None and allow_none:
            return None
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise PerceptionError(f"{name} 必须是正有限数，收到 {value!r}") from exc
        if not math.isfinite(number) or number <= 0.0:
            raise PerceptionError(f"{name} 必须是正有限数，收到 {value!r}")
        return number

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

    def _require_frame(self, frame: Any) -> Any:
        """调用方没给帧时，从 frame_source 取一帧；两边都没有才报错。"""
        if frame is not None:
            return frame
        if self.frame_source is not None:
            grabbed = self.frame_source.grab()
            if grabbed is None:
                raise PerceptionError("frame_source.grab() 返回空帧")
            return grabbed
        raise PerceptionError("detect_* 需要传入图像帧 frame（BGR numpy 数组），或在构造时注入 frame_source")

    def detect_face(self, frame: Any = None) -> PerceptionResult:
        frame = self._require_frame(frame)
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

    def _get_qr_decoder(self) -> Any:
        """惰性构造二维码解码器；把本后端的 cv2（可能是注入的 fake）传下去。"""
        if self._qr_decoder is None:
            from .qr import build_qr_decoder

            self._qr_decoder = build_qr_decoder(
                self.qr_decoder_name, cv2_module=self._get_cv2()
            )
        return self._qr_decoder

    def detect_qr(self, frame: Any = None) -> PerceptionResult:
        frame = self._require_frame(frame)
        result = self._get_qr_decoder().decode(frame)
        if not result.found:
            data: Dict[str, Any] = {"found": False}
            if result.error:
                data["error"] = result.error
            return PerceptionResult(kind="qr", data=data, confidence=0.0)
        try:
            payload: Any = json.loads(result.data)
        except (TypeError, ValueError):
            payload = result.data
        return PerceptionResult(
            kind="qr",
            data={"found": True, "payload": payload, "decoder": result.decoder},
            confidence=1.0,
            raw=result.points,
        )

    def _largest_hsv_blob(
        self, frame: Any, ranges: Tuple[Tuple[Tuple[int, int, int], Tuple[int, int, int]], ...]
    ) -> Optional[Tuple[Any, int, int, int, int, float, float]]:
        cv = self._get_cv2()
        hsv = cv.cvtColor(frame, cv.COLOR_BGR2HSV)
        mask = None
        for lower, upper in ranges:
            part = cv.inRange(hsv, lower, upper)
            mask = part if mask is None else cv.bitwise_or(mask, part)
        contours, _ = cv.findContours(
            mask, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE
        )
        if not contours:
            return None
        areas = [cv.contourArea(c) for c in contours]
        best = contours[max(range(len(areas)), key=areas.__getitem__)]
        x, y, w, h = cv.boundingRect(best)
        cx = x + w / 2.0
        cy = y + h / 2.0
        return best, x, y, w, h, cx, cy

    def _frame_width(self, frame: Any) -> int:
        if hasattr(frame, "shape") and len(frame.shape) >= 2:
            return int(frame.shape[1])
        height = len(frame)
        return len(frame[0]) if height else 0

    def _estimate_distance_cm(self, diameter_px: float, size_cm: float) -> Tuple[Optional[float], str]:
        """有焦距用针孔模型；没有焦距用像素当量（标为 uncalibrated，不能当实测距离）。"""
        if diameter_px <= 0:
            return None, "none"
        if self.focal_px:
            return round(size_cm * self.focal_px / float(diameter_px), 2), "calibrated"
        if self.pixels_per_cm:
            return round(size_cm * self.pixels_per_cm / float(diameter_px), 2), "uncalibrated"
        return None, "none"

    def detect_ball(self, frame: Any = None) -> PerceptionResult:
        frame = self._require_frame(frame)
        blob = self._largest_hsv_blob(frame, ((self.ball_hsv_lower, self.ball_hsv_upper),))
        if blob is None:
            return PerceptionResult(kind="ball", data={"found": False}, confidence=0.0)
        best, x, y, w, h, cx, cy = blob
        width = self._frame_width(frame)
        x_cm = (cx - width / 2.0) / self.pixels_per_cm
        ball_diameter_px = max(w, h)
        distance_cm, dist_source = self._estimate_distance_cm(ball_diameter_px, self.ball_diameter_cm)
        return PerceptionResult(
            kind="ball",
            data={
                "found": True,
                "x_cm": round(x_cm, 2),
                "distance_cm": distance_cm,
                "distance_source": dist_source,
                "bbox": [int(x), int(y), int(w), int(h)],
                "center_px": [int(cx), int(cy)],
            },
            confidence=0.85,
            raw=best,
        )

    def detect_object(self, frame: Any = None, target: Optional[str] = None) -> PerceptionResult:
        frame = self._require_frame(frame)
        name = target or self.object_target
        ranges = self.OBJECT_HSV.get(name, self.object_hsv_ranges)
        blob = self._largest_hsv_blob(frame, ranges)
        if blob is None:
            return PerceptionResult(kind="object", data={"found": False, "target": name}, confidence=0.0)
        best, x, y, w, h, cx, cy = blob
        width = self._frame_width(frame)
        x_cm = (cx - width / 2.0) / self.pixels_per_cm
        diameter_px = max(w, h)
        distance_cm, dist_source = self._estimate_distance_cm(diameter_px, self.object_size_cm)
        return PerceptionResult(
            kind="object",
            data={
                "found": True,
                "target": name,
                "x_cm": round(x_cm, 2),
                "distance_cm": distance_cm,
                "distance_source": dist_source,
                "bbox": [int(x), int(y), int(w), int(h)],
                "center_px": [int(cx), int(cy)],
            },
            confidence=0.8,
            raw=best,
        )
