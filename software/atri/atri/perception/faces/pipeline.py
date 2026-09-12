"""人脸识别管线：检测 → 裁剪对齐 → 特征提取 → 库比对。

这是 T-01 的主入口。上层（技能/工具/评测脚本）只跟 :class:`FaceRecognizer` 打交道，
不直接碰 detector/embedder/db 三件套。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional

from ..base import PerceptionError
from .detector import FaceBox, FaceDetector
from .embedder import FaceEmbedder
from .face_db import FaceDB, MatchResult


@dataclass
class FaceResult:
    """单张脸的识别结果。"""

    box: FaceBox
    name: Optional[str] = None
    similarity: float = 0.0
    recognized: bool = False
    margin: float = 0.0
    error: Optional[str] = None

    def to_dict(self) -> dict:
        data = self.box.to_dict()
        data.update(
            {
                "name": self.name,
                "similarity": round(self.similarity, 4),
                "recognized": self.recognized,
                "margin": round(self.margin, 4),
            }
        )
        if self.error:
            data["error"] = self.error
        return data


@dataclass
class FrameResult:
    """一帧的识别结果。"""

    faces: List[FaceResult] = field(default_factory=list)
    best: Optional[FaceResult] = None
    frame_size: Optional[tuple] = None

    @property
    def found(self) -> bool:
        return len(self.faces) > 0

    @property
    def recognized_name(self) -> Optional[str]:
        """最可信且过阈值的那张脸的姓名；没有人被认出来则为 None。"""
        return self.best.name if self.best else None

    def to_dict(self) -> dict:
        return {
            "found": self.found,
            "count": len(self.faces),
            "name": self.recognized_name,
            "faces": [f.to_dict() for f in self.faces],
        }


class FaceRecognizer:
    """检测 + 识别一体。"""

    def __init__(
        self,
        detector: FaceDetector,
        embedder: FaceEmbedder,
        db: Optional[FaceDB] = None,
        min_face_px: int = 40,
    ) -> None:
        """db 为 None 时只做检测（返回 bbox，不返回姓名）。"""
        self.detector = detector
        self.embedder = embedder
        self.db = db
        self.min_face_px = int(min_face_px)
        self.stats = {"frames": 0, "faces": 0, "skipped_small": 0, "errors": 0}

    def detect(self, frame: Any) -> List[FaceBox]:
        return self.detector.detect(frame)

    def recognize(self, frame: Any) -> FrameResult:
        """识别一帧里的所有人脸。

        小脸跳过（低于 min_face_px）：像素太少时特征不可靠，
        硬认出来的是噪声，不如不认。
        """
        if frame is None:
            raise PerceptionError("recognize 需要传入图像帧")
        boxes = self.detector.detect(frame)
        shape = getattr(frame, "shape", None)
        result = FrameResult(
            frame_size=(int(shape[1]), int(shape[0])) if shape is not None else None
        )
        self.stats["frames"] += 1

        for box in boxes:
            self.stats["faces"] += 1
            if min(box.width, box.height) < self.min_face_px:
                self.stats["skipped_small"] += 1
                continue
            face = FaceResult(box=box)
            try:
                crop = self.embedder.crop(frame, box)
                vector = self.embedder.embed(crop)
                if self.db is not None:
                    match: MatchResult = self.db.match(vector)
                    face.name = match.name
                    face.similarity = match.similarity
                    face.recognized = match.recognized
                    face.margin = match.margin
            except Exception as exc:  # 单张脸失败不该毁掉整帧
                self.stats["errors"] += 1
                face.error = str(exc)
            result.faces.append(face)

        recognized = [f for f in result.faces if f.recognized]
        if recognized:
            result.best = max(recognized, key=lambda f: (f.similarity, f.margin))
        return result
