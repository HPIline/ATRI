"""Mock 视觉感知：无硬件时提供确定性的感知数据。"""
from __future__ import annotations

from typing import Any, Dict, Optional

from .base import PerceptionBackend, PerceptionResult

DEFAULT_FACE = {"name": "测试员A", "found": True}
DEFAULT_QR = {"payload": {"action": "walk", "steps": 3}, "found": True}
DEFAULT_BALL = {"x_cm": 1.5, "distance_cm": 12.0, "found": True}


class MockPerception(PerceptionBackend):
    name = "mock"

    def __init__(
        self,
        face: Optional[Dict[str, Any]] = None,
        qr: Optional[Dict[str, Any]] = None,
        ball: Optional[Dict[str, Any]] = None,
        face_confidence: float = 0.93,
        qr_confidence: float = 0.99,
        ball_confidence: float = 0.9,
    ) -> None:
        self.face = dict(DEFAULT_FACE)
        self.qr = dict(DEFAULT_QR)
        self.ball = dict(DEFAULT_BALL)
        if face is not None:
            self.face.update(face)
        if qr is not None:
            self.qr.update(qr)
        if ball is not None:
            self.ball.update(ball)
        self.face_confidence = face_confidence
        self.qr_confidence = qr_confidence
        self.ball_confidence = ball_confidence

    def detect_face(self, frame: Any = None) -> PerceptionResult:
        return PerceptionResult(
            kind="face",
            data=dict(self.face),
            confidence=self.face_confidence,
        )

    def detect_qr(self, frame: Any = None) -> PerceptionResult:
        return PerceptionResult(
            kind="qr",
            data=dict(self.qr),
            confidence=self.qr_confidence,
        )

    def detect_ball(self, frame: Any = None) -> PerceptionResult:
        return PerceptionResult(
            kind="ball",
            data=dict(self.ball),
            confidence=self.ball_confidence,
        )
