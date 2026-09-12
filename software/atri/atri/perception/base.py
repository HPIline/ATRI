"""视觉感知接口定义。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


class PerceptionError(RuntimeError):
    """感知模块错误。"""


@dataclass
class PerceptionResult:
    """统一感知结果。

    kind: face / qr / ball
    data: 具体感知数据（found/name/payload/bbox/x_cm/distance_cm 等）
    confidence: 置信度 0.0~1.0
    raw: 原始检测结果（OpenCV 返回值等），便于调试
    """

    kind: str
    data: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    raw: Any = None

    def to_dict(self) -> Dict[str, Any]:
        return {"kind": self.kind, **self.data, "confidence": self.confidence}


class PerceptionBackend(ABC):
    """视觉感知后端接口。

    所有检测方法都接收可选的 frame（BGR numpy 图像）。Mock 实现可以忽略 frame。
    """

    name: str = "base"

    def available(self) -> bool:
        """该后端在当前环境是否可用；需要第三方依赖的后端覆盖它。"""
        return True

    @abstractmethod
    def detect_face(self, frame: Any = None) -> PerceptionResult:
        """检测画面中的人脸。"""

    @abstractmethod
    def detect_qr(self, frame: Any = None) -> PerceptionResult:
        """检测并解码二维码。"""

    @abstractmethod
    def detect_ball(self, frame: Any = None) -> PerceptionResult:
        """检测场地中的球。"""

    def detect_object(self, frame: Any = None) -> PerceptionResult:
        """检测搬运目标（默认红块色块）。未实现的后端视为未命中。"""
        return PerceptionResult(kind="object", data={"found": False}, confidence=0.0)
