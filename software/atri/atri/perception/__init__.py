"""视觉感知模块：人脸 / 二维码 / 球 / 搬运目标检测。

- MockPerception：无硬件/无 OpenCV 时使用，返回确定性观测
- OpenCVPerception：真实摄像头检测实现（可选依赖 opencv-python）
- PerceptionResult：统一返回结构
"""
from .base import PerceptionBackend, PerceptionError, PerceptionResult
from .mock import MockPerception
from .opencv import OpenCVPerception

__all__ = [
    "PerceptionBackend",
    "PerceptionError",
    "PerceptionResult",
    "MockPerception",
    "OpenCVPerception",
]
