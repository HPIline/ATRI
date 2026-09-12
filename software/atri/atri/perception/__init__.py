"""视觉感知模块：人脸 / 二维码 / 球 / 搬运目标检测。

- MockPerception：无硬件/无 OpenCV 时使用，返回确定性观测
- OpenCVPerception：真实摄像头检测实现（可选依赖 opencv-python）
- PerceptionResult：统一返回结构
- FrameSource 系列（sources）：摄像头 / 图片文件 / 噪声帧，把"从哪取帧"独立出来

**人脸识别子模块不在下面急切导入**：``atri.perception.faces`` 依赖 numpy 与 opencv，
急切导入会破坏"核心包零第三方依赖"这条底线（CI 主 job 不装 numpy）。需要时显式写::

    from atri.perception.faces import FaceRecognizer, YuNetDetector, SFaceEmbedder, FaceDB

（Python 3.7+ 的模块级 __getattr__ 让 ``from atri.perception import FaceRecognizer`` 也能用，
但仍然只在真正访问时才导入 numpy。）
"""
from __future__ import annotations

from typing import Any

from .base import PerceptionBackend, PerceptionError, PerceptionResult
from .mock import MockPerception
from .opencv import OpenCVPerception
from .sources import CameraSource, FrameSource, ImageFileSource, MockFrameSource

__all__ = [
    "PerceptionBackend",
    "PerceptionError",
    "PerceptionResult",
    "MockPerception",
    "OpenCVPerception",
    "FrameSource",
    "ImageFileSource",
    "CameraSource",
    "MockFrameSource",
    "FaceRecognizer",
    "FaceDB",
    "FaceBox",
    "YuNetDetector",
    "HaarDetector",
    "SFaceEmbedder",
]

_LAZY_FACES = {
    "FaceRecognizer",
    "FaceResult",
    "FrameResult",
    "FaceDB",
    "MatchResult",
    "Person",
    "FaceBox",
    "FaceDetector",
    "YuNetDetector",
    "HaarDetector",
    "FaceEmbedder",
    "SFaceEmbedder",
    "MockEmbedder",
}


def __getattr__(name: str) -> Any:
    """惰性转发人脸子模块（PEP 562）：不 import 就不会要求 numpy/opencv。"""
    if name in _LAZY_FACES:
        from . import faces

        return getattr(faces, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
