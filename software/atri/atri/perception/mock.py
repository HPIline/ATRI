"""Mock 视觉感知：无硬件时提供确定性的感知数据。"""
from __future__ import annotations

from typing import Any, Dict, Optional

from ..config import body_yaw_deg_from_angles
from .base import PerceptionBackend, PerceptionResult

DEFAULT_FACE = {"name": "测试员A", "found": True}
DEFAULT_QR = {"payload": {"action": "walk", "steps": 3}, "found": True}
DEFAULT_BALL = {"x_cm": 1.5, "distance_cm": 12.0, "found": True}
DEFAULT_OBJECT = {"target": "红块", "x_cm": 0.5, "distance_cm": 8.0, "found": True}
DEFAULT_SPEECH = {"keyword": "跳舞", "found": True}


class MockPerception(PerceptionBackend):
    name = "mock"

    def __init__(
        self,
        face: Optional[Dict[str, Any]] = None,
        qr: Optional[Dict[str, Any]] = None,
        ball: Optional[Dict[str, Any]] = None,
        obj: Optional[Dict[str, Any]] = None,
        speech: Optional[Dict[str, Any]] = None,
        face_confidence: float = 0.93,
        qr_confidence: float = 0.99,
        ball_confidence: float = 0.9,
        object_confidence: float = 0.9,
        speech_confidence: float = 0.95,
    ) -> None:
        self.face = dict(DEFAULT_FACE)
        self.qr = dict(DEFAULT_QR)
        self.ball = dict(DEFAULT_BALL)
        self.object = dict(DEFAULT_OBJECT)
        self.speech = dict(DEFAULT_SPEECH)
        if face is not None:
            self.face.update(face)
        if qr is not None:
            self.qr.update(qr)
        if ball is not None:
            self.ball.update(ball)
        if obj is not None:
            self.object.update(obj)
        if speech is not None:
            self.speech.update(speech)
        self.face_confidence = face_confidence
        self.qr_confidence = qr_confidence
        self.ball_confidence = ball_confidence
        self.object_confidence = object_confidence
        self.speech_confidence = speech_confidence

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

    def detect_object(self, frame: Any = None) -> PerceptionResult:
        return PerceptionResult(
            kind="object",
            data=dict(self.object),
            confidence=self.object_confidence,
        )

    def detect_speech(self, audio: Any = None) -> PerceptionResult:
        return PerceptionResult(
            kind="speech",
            data=dict(self.speech),
            confidence=self.speech_confidence,
        )


class ServoMockPerception(MockPerception):
    """带"相机随动"一维几何的 Mock：机器人累计转过 body yaw 后，目标在画面里的
    横向偏移按 ``x_cm = x_true - gain * yaw`` 减小，用于让踢球/搬运的闭环在
    无硬件仿真里真的收敛（而不是对固定观测空转到上限）。

    无硬件时它是"闭环真正能跑"的关键：普通 MockPerception 返回常量横向偏移，
    闭环每一轮都测到同一个数，永远进不了死区；本类把机器人当前髋 roll 转向占位
    反馈进下一次观测，模拟"朝目标转过去 → 目标在画面里往中间靠"的一维几何。
    """

    name = "servo-mock"

    def __init__(
        self,
        bus: Any,
        ball_x_true: float = 3.0,
        object_x_true: float = 3.0,
        place_x_true: float = 5.0,
        gain_cm_per_deg: float = 1.5,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._bus = bus
        self._ball_x_true = float(ball_x_true)
        self._object_x_true = float(object_x_true)
        self._place_x_true = float(place_x_true)
        self._gain = float(gain_cm_per_deg)

    def _body_yaw_deg(self) -> float:
        return body_yaw_deg_from_angles(getattr(self._bus, "angles", {}))

    def detect_ball(self, frame: Any = None) -> PerceptionResult:
        x_cm = self._ball_x_true - self._gain * self._body_yaw_deg()
        data = dict(self.ball)
        data["x_cm"] = round(x_cm, 2)
        data["found"] = True
        return PerceptionResult(kind="ball", data=data, confidence=self.ball_confidence)

    def detect_object(self, frame: Any = None) -> PerceptionResult:
        x_cm = self._object_x_true - self._gain * self._body_yaw_deg()
        data = dict(self.object)
        data["x_cm"] = round(x_cm, 2)
        data["found"] = True
        return PerceptionResult(kind="object", data=data, confidence=self.object_confidence)

    def detect_place(self, frame: Any = None) -> PerceptionResult:
        """放置区（T-03 的第二目标）：同一套一维几何，用于验证"对准后才释放"。

        只有本类提供该通道；纯 ``MockPerception`` 不给 ``detect_place``，
        于是 T-03 在纯 Mock 下会明确回报"放置区通道未接入"（而不是假装看见）。
        """
        x_cm = self._place_x_true - self._gain * self._body_yaw_deg()
        data = {
            "found": True,
            "x_cm": round(x_cm, 2),
            "distance_source": "mock-geometry",
        }
        return PerceptionResult(kind="place", data=data, confidence=self.object_confidence)
