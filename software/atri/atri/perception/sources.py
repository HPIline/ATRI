"""图像帧来源：把"从哪拿一帧"和"怎么识别一帧"分开。

- ``ImageFileSource``：从图片文件取帧。**没有摄像头也能端到端验证 T-01**，且完全可复现。
- ``CameraSource``：打开本机摄像头（macOS 首次会弹权限）。真机联调用。
- ``MockFrameSource``：确定性噪声帧，供测试。

cv2 一律惰性导入：核心包不装 numpy/opencv 也能 import 本模块。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional

from .base import PerceptionError


class FrameSource(ABC):
    """一帧的来源。"""

    name: str = "base"

    @abstractmethod
    def grab(self) -> Any:
        """取一帧 BGR 图像。"""

    def close(self) -> None:
        """释放资源（文件源无需释放）。"""

    def __enter__(self) -> "FrameSource":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


class ImageFileSource(FrameSource):
    """从图片文件取帧（每次 grab 返回同一张，便于可复现复跑）。"""

    name = "image-file"

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if not self.path.exists():
            raise PerceptionError(f"图片不存在: {self.path}")
        self._frame: Optional[Any] = None

    def grab(self) -> Any:
        if self._frame is None:
            import cv2
            import numpy as np

            data = np.fromfile(str(self.path), dtype=np.uint8)
            frame = cv2.imdecode(data, cv2.IMREAD_COLOR)
            if frame is None:
                raise PerceptionError(f"图片解码失败: {self.path}")
            self._frame = frame
        return self._frame


class CameraSource(FrameSource):
    """本机摄像头。"""

    name = "camera"

    def __init__(self, index: int = 0, warmup: int = 5) -> None:
        self.index = int(index)
        self.warmup = int(warmup)
        self._cap: Optional[Any] = None

    def _ensure(self) -> Any:
        if self._cap is None:
            import cv2

            cap = cv2.VideoCapture(self.index)
            if not cap.isOpened():
                raise PerceptionError(
                    f"打不开摄像头 index={self.index}。"
                    "macOS 需在 系统设置→隐私与安全性→摄像头 里授权给终端；"
                    "或先确认设备没被其它程序占用。"
                )
            for _ in range(self.warmup):  # 丢掉前几帧，等自动曝光稳定
                cap.read()
            self._cap = cap
        return self._cap

    def grab(self) -> Any:
        cap = self._ensure()
        ok, frame = cap.read()
        if not ok or frame is None:
            raise PerceptionError("摄像头读取失败")
        return frame

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None


class MockFrameSource(FrameSource):
    """确定性噪声帧。**不含任何人脸** —— 只用于验证管线不崩、且不会误报。"""

    name = "mock"

    def __init__(self, width: int = 320, height: int = 240, seed: int = 0) -> None:
        self.width = width
        self.height = height
        self.seed = seed

    def grab(self) -> Any:
        import numpy as np

        rng = np.random.default_rng(self.seed)
        return (rng.random((self.height, self.width, 3)) * 255).astype("uint8")
