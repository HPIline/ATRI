"""人脸检测器实现。

- ``YuNetDetector``：主力。OpenCV 官方 YuNet（opencv_zoo），232 KB ONNX，CPU 可跑，
  输出 bbox + 5 关键点，比 Haar 稳得多。
- ``HaarDetector``：对照组。级联分类器随 opencv 包自带、零下载，只认正脸、易误检，
  留作基准数字用（报告里出对照），不作为默认。

两者都返回 :class:`FaceBox`，上层不关心用的是哪个。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, List, Optional, Sequence, Tuple

from ..base import PerceptionError

# 官方模型与出处（下载与 sha256 校验见 tools/fetch_models.py）
# https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet
YUNET_MODEL_SHA256 = "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"
YUNET_MODEL_SIZE = 232589
DEFAULT_YUNET_MODEL = "models/face_detection_yunet_2023mar.onnx"


@dataclass
class FaceBox:
    """一张被检出的人脸。

    bbox: (x, y, w, h)，整数像素
    landmarks: 5 个关键点 [(x, y) × 5]，顺序为 YuNet 原样输出；无关键点的检测器留空
    score: 检测置信度
    raw: 检测器原始输出行（YuNet 是 15 列 ndarray），供 SFace 的 alignCrop 复用
    """

    bbox: Tuple[int, int, int, int]
    score: float = 1.0
    landmarks: List[Tuple[float, float]] = field(default_factory=list)
    raw: Any = None

    @property
    def width(self) -> int:
        return int(self.bbox[2])

    @property
    def height(self) -> int:
        return int(self.bbox[3])

    @property
    def area(self) -> int:
        return self.width * self.height

    def to_dict(self) -> dict:
        return {
            "bbox": [int(v) for v in self.bbox],
            "score": round(float(self.score), 4),
            "landmarks": [[round(float(x), 2), round(float(y), 2)] for x, y in self.landmarks],
        }


class FaceDetector(ABC):
    """人脸检测器接口。"""

    name: str = "base"

    @abstractmethod
    def detect(self, frame: Any) -> List[FaceBox]:
        """检测一帧里的所有人脸，按检测分降序返回。无人脸时返回空列表。"""


def _frame_shape(frame: Any) -> Tuple[int, int]:
    """取帧的 (height, width)；不合法就报错，不猜。"""
    shape = getattr(frame, "shape", None)
    if shape is None or len(shape) < 2:
        raise PerceptionError("检测需要 BGR 图像帧（带 shape 的 numpy 数组）")
    return int(shape[0]), int(shape[1])


class YuNetDetector(FaceDetector):
    """YuNet 检测器（OpenCV DNN，ONNX）。"""

    name = "yunet"

    def __init__(
        self,
        model_path: str = DEFAULT_YUNET_MODEL,
        input_size: Tuple[int, int] = (320, 320),
        score_threshold: float = 0.6,
        nms_threshold: float = 0.3,
        top_k: int = 50,
        cv2_module: Any = None,
    ) -> None:
        """cv2_module 仅供测试注入 fake；正常传 None 自动 import cv2。"""
        self.model_path = str(model_path)
        self.input_size = input_size
        self.score_threshold = score_threshold
        self.nms_threshold = nms_threshold
        self.top_k = top_k
        self._cv2 = cv2_module
        self._detector: Any = None

    def _get_cv2(self) -> Any:
        if self._cv2 is None:
            try:
                import cv2  # type: ignore
            except ImportError as exc:  # pragma: no cover - 环境问题
                raise PerceptionError(
                    "OpenCV 未安装：请执行 pip install \"opencv-contrib-python==4.11.0.86\""
                ) from exc
            self._cv2 = cv2
        return self._cv2

    def _ensure(self) -> Any:
        """惰性建模型：加载失败要报清楚，不要静默降级。"""
        if self._detector is not None:
            return self._detector
        import os

        if not os.path.exists(self.model_path):
            raise PerceptionError(
                f"YuNet 模型不存在: {self.model_path}\n"
                f"请先运行： python tools/fetch_models.py"
            )
        cv = self._get_cv2()
        w, h = self.input_size
        self._detector = cv.FaceDetectorYN_create(
            self.model_path, "", (int(w), int(h)),
            float(self.score_threshold), float(self.nms_threshold), int(self.top_k),
        )
        return self._detector

    def detect(self, frame: Any) -> List[FaceBox]:
        height, width = _frame_shape(frame)
        det = self._ensure()
        det.setInputSize((width, height))
        _, faces = det.detect(frame)
        if faces is None:
            return []
        boxes: List[FaceBox] = []
        for row in faces:
            x, y, w, h = (int(round(float(v))) for v in row[:4])
            landmarks = [(float(row[4 + 2 * i]), float(row[5 + 2 * i])) for i in range(5)]
            score = float(row[14])
            boxes.append(FaceBox(bbox=(x, y, w, h), score=score, landmarks=landmarks, raw=row))
        boxes.sort(key=lambda b: b.score, reverse=True)
        return boxes


class HaarDetector(FaceDetector):
    """Haar 级联检测器（对照组基准）。无关键点。"""

    name = "haar"

    def __init__(
        self,
        cascade_path: Optional[str] = None,
        scale_factor: float = 1.1,
        min_neighbors: int = 5,
        min_size: Tuple[int, int] = (30, 30),
        cv2_module: Any = None,
    ) -> None:
        self.cascade_path = cascade_path
        self.scale_factor = scale_factor
        self.min_neighbors = min_neighbors
        self.min_size = min_size
        self._cv2 = cv2_module

    def _get_cv2(self) -> Any:
        if self._cv2 is None:
            try:
                import cv2  # type: ignore
            except ImportError as exc:  # pragma: no cover - 环境问题
                raise PerceptionError("OpenCV 未安装") from exc
            self._cv2 = cv2
        return self._cv2

    def detect(self, frame: Any) -> List[FaceBox]:
        _frame_shape(frame)
        cv = self._get_cv2()
        gray = cv.cvtColor(frame, cv.COLOR_BGR2GRAY)
        gray = cv.equalizeHist(gray)
        path = self.cascade_path
        if path is None:
            path = cv.data.haarcascades + "haarcascade_frontalface_default.xml"
        cascade = cv.CascadeClassifier(path)
        faces = cascade.detectMultiScale(
            gray,
            scaleFactor=self.scale_factor,
            minNeighbors=self.min_neighbors,
            minSize=self.min_size,
        )
        boxes: List[FaceBox] = []
        for x, y, w, h in faces:
            boxes.append(
                FaceBox(bbox=(int(x), int(y), int(w), int(h)), score=0.8, landmarks=[])
            )
        boxes.sort(key=lambda b: b.area, reverse=True)
        return boxes
