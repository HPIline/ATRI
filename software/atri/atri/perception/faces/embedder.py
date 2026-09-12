"""人脸特征提取器（embedder）。

把一张对齐好的人脸变成**定长向量**，这是"认人"的核心：
- ``SFaceEmbedder``：OpenCV 官方 SFace（opencv_zoo），128 维，离线 CPU 可跑。
- ``MockEmbedder``：确定性假特征，供 CI 跑管线测试；**不可用于任何真实识别**。

输出向量一律做 **L2 归一化**，因此余弦相似度退化成点积 —— 比对变成一次矩阵乘法。

关于"裁剪"：每种特征提取器都自带它的裁剪口径（``crop``），
因为裁剪方式必须和模型训练时一致，不能由上层随便决定。
SFace 优先用官方 ``alignCrop``（与训练口径一致），关键点缺失时才退回五点对齐/bbox 裁剪。
"""
from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

import numpy as np

from ..base import PerceptionError
from .align import OUTPUT_SIZE, align_5pt, crop_by_bbox
from .detector import FaceBox

# 官方模型与出处（下载与 sha256 校验见 tools/fetch_models.py）
# https://github.com/opencv/opencv_zoo/tree/main/models/face_recognition_sface
SFACE_MODEL_SHA256 = "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79"
SFACE_MODEL_SIZE = 38696353
DEFAULT_SFACE_MODEL = "models/face_recognition_sface_2021dec.onnx"

SFACE_DIM = 128


def l2_normalize(vec: Any) -> np.ndarray:
    """L2 归一化；零向量直接报错（零向量无法比对，静默放行会算出 NaN）。"""
    arr = np.asarray(vec, dtype=np.float32).reshape(-1)
    norm = float(np.linalg.norm(arr))
    if norm < 1e-12:
        raise PerceptionError("特征向量范数为 0，无法归一化")
    return arr / norm


class FaceEmbedder(ABC):
    """人脸特征提取器接口。"""

    name: str = "base"
    dim: int = 0

    def crop(self, frame: Any, box: FaceBox) -> Any:
        """按检测框裁出待提取的人脸。默认：有关键点就五点对齐，否则按 bbox 裁。"""
        if box.landmarks:
            return align_5pt(frame, box.landmarks, OUTPUT_SIZE)
        return crop_by_bbox(frame, box.bbox)

    @abstractmethod
    def embed(self, face_bgr: Any) -> np.ndarray:
        """输入裁好的人脸，返回 **已 L2 归一化** 的定长向量。"""


class SFaceEmbedder(FaceEmbedder):
    """SFace 特征提取器（128 维）。"""

    def __init__(
        self,
        model_path: str = DEFAULT_SFACE_MODEL,
        cv2_module: Any = None,
        use_align_crop: bool = True,
    ) -> None:
        self.model_path = str(model_path)
        self._cv2 = cv2_module
        self.use_align_crop = use_align_crop
        self._recognizer: Any = None
        # 记录每种裁剪路径各用了多少次：评测报告要能说清用的是哪条路
        self.crop_stats: Dict[str, int] = {"align_crop": 0, "five_point": 0, "bbox": 0}

    @property
    def name(self) -> str:  # type: ignore[override]
        return "sface"

    @property
    def dim(self) -> int:  # type: ignore[override]
        return SFACE_DIM

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
        if self._recognizer is not None:
            return self._recognizer
        import os

        if not os.path.exists(self.model_path):
            raise PerceptionError(
                f"SFace 模型不存在: {self.model_path}\n"
                f"请先运行： python tools/fetch_models.py"
            )
        cv = self._get_cv2()
        self._recognizer = cv.FaceRecognizerSF_create(self.model_path, "")
        return self._recognizer

    def crop(self, frame: Any, box: FaceBox) -> Any:
        cv = self._get_cv2()
        if self.use_align_crop and box.raw is not None:
            try:
                aligned = self._ensure().alignCrop(frame, np.asarray(box.raw, dtype=np.float32))
                if aligned is not None and getattr(aligned, "size", 0):
                    self.crop_stats["align_crop"] += 1
                    return aligned
            except Exception:
                # alignCrop 失败不静默吞掉结果，退到五点对齐并记账
                pass
        if box.landmarks:
            self.crop_stats["five_point"] += 1
            return align_5pt(frame, box.landmarks, OUTPUT_SIZE)
        self.crop_stats["bbox"] += 1
        return crop_by_bbox(frame, box.bbox)

    def embed(self, face_bgr: Any) -> np.ndarray:
        if face_bgr is None:
            raise PerceptionError("embed 收到空图像")
        recognizer = self._ensure()
        cv = self._get_cv2()
        if not hasattr(face_bgr, "shape"):
            face_bgr = np.asarray(face_bgr)
        if len(face_bgr.shape) != 3 or face_bgr.shape[0] < 8 or face_bgr.shape[1] < 8:
            raise PerceptionError(f"人脸图不合法: shape={getattr(face_bgr, 'shape', None)}")
        # SFace 期望 112×112
        if face_bgr.shape[0] != OUTPUT_SIZE or face_bgr.shape[1] != OUTPUT_SIZE:
            face_bgr = cv.resize(face_bgr, (OUTPUT_SIZE, OUTPUT_SIZE))
        feat = recognizer.feature(face_bgr)
        return l2_normalize(feat)


class MockEmbedder(FaceEmbedder):
    """确定性假特征：同一张图永远得到同一向量。**仅供测试，不可用于真实识别。**"""

    def __init__(self, dim: int = 16, seed_salt: str = "mock") -> None:
        self._dim = dim
        self._salt = seed_salt

    @property
    def name(self) -> str:  # type: ignore[override]
        return "mock"

    @property
    def dim(self) -> int:  # type: ignore[override]
        return self._dim

    def embed(self, face_bgr: Any) -> np.ndarray:
        arr = np.asarray(face_bgr)
        digest = hashlib.sha256(self._salt.encode("utf-8") + arr.tobytes()).digest()
        seed = int.from_bytes(digest[:8], "big")
        rng = np.random.default_rng(seed)
        return l2_normalize(rng.standard_normal(self._dim))
